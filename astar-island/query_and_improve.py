"""
Query the simulator strategically and build improved predictions.
Uses cross-seed learning: hidden parameters are shared across all 5 seeds.

Strategy:
- Allocate ~10 queries per seed (50 total)
- Cover as much of the map as possible per seed
- Build transition model from initial → final terrain
- Apply learned transitions to predict unobserved areas

Usage: python query_and_improve.py
"""

import numpy as np

from client import (
    get_session, get_active_round, get_round_details, check_budget,
    simulate, submit_prediction, generate_viewport_grid,
    TERRAIN_TO_CLASS, build_initial_state_prediction,
)


def allocate_queries(seeds_count: int = 5, total_budget: int = 50) -> list[int]:
    """Allocate queries across seeds. Spread evenly."""
    per_seed = total_budget // seeds_count
    allocation = [per_seed] * seeds_count
    # Distribute remaining queries to first seeds
    for i in range(total_budget % seeds_count):
        allocation[i] += 1
    return allocation


def collect_observations(session, round_id: str, seed_index: int,
                         num_queries: int, map_w: int, map_h: int) -> list[dict]:
    """Collect simulation observations for one seed, spreading viewports across the map."""
    viewports = generate_viewport_grid(map_w, map_h, vp_size=15)
    observations = []

    for i, (vx, vy, vw, vh) in enumerate(viewports):
        if i >= num_queries:
            break

        result = simulate(session, round_id, seed_index, vx, vy, vw, vh)
        if "error" in result:
            print(f"  Error on query {i}: {result}")
            continue

        observations.append({
            "viewport": (vx, vy, vw, vh),
            "grid": result["grid"],
            "settlements": result.get("settlements", []),
            "queries_used": result.get("queries_used", 0),
        })
        print(f"  Seed {seed_index}, query {i+1}/{num_queries}: "
              f"viewport ({vx},{vy},{vw},{vh}), "
              f"budget {result.get('queries_used', '?')}/{result.get('queries_max', '?')}")

    return observations


def build_transition_model(initial_grids: list, all_observations: dict,
                           map_h: int, map_w: int) -> dict:
    """Learn terrain transition probabilities from all observations across all seeds.

    Returns: dict mapping initial_terrain_class → numpy array of shape (6,)
             representing probability distribution over final classes.
    """
    # Count transitions: initial_class → final_class
    transitions = {}
    for cls in range(6):
        transitions[cls] = np.ones(6) * 0.01  # Small prior

    for seed_idx, obs_list in all_observations.items():
        initial_grid = np.array(initial_grids[seed_idx])

        for obs in obs_list:
            vx, vy, vw, vh = obs["viewport"]
            final_grid = np.array(obs["grid"])

            for dy in range(vh):
                for dx in range(vw):
                    map_y, map_x = vy + dy, vx + dx
                    if map_y >= map_h or map_x >= map_w:
                        continue

                    initial_val = initial_grid[map_y][map_x]
                    final_val = final_grid[dy][dx]

                    if initial_val in TERRAIN_TO_CLASS and final_val in TERRAIN_TO_CLASS:
                        init_cls = TERRAIN_TO_CLASS[initial_val]
                        final_cls = TERRAIN_TO_CLASS[final_val]
                        transitions[init_cls][final_cls] += 1.0

    # Normalize
    for cls in transitions:
        total = transitions[cls].sum()
        if total > 0:
            transitions[cls] = transitions[cls] / total

    return transitions


def build_improved_prediction(initial_grid: list, observations: list[dict],
                              transition_model: dict,
                              map_h: int, map_w: int) -> np.ndarray:
    """Build prediction combining direct observations with transition model."""
    # Start with transition-model-based prediction for the whole map
    prediction = np.full((map_h, map_w, 6), 1 / 6)
    grid = np.array(initial_grid)

    for y in range(map_h):
        for x in range(map_w):
            val = grid[y][x]
            if val in TERRAIN_TO_CLASS:
                cls = TERRAIN_TO_CLASS[val]
                prediction[y, x] = transition_model.get(cls, np.ones(6) / 6)

    # Override with direct observation counts where we have them
    obs_counts = np.zeros((map_h, map_w, 6))
    obs_total = np.zeros((map_h, map_w))

    for obs in observations:
        vx, vy, vw, vh = obs["viewport"]
        final_grid = np.array(obs["grid"])

        for dy in range(vh):
            for dx in range(vw):
                map_y, map_x = vy + dy, vx + dx
                if map_y >= map_h or map_x >= map_w:
                    continue
                final_val = final_grid[dy][dx]
                if final_val in TERRAIN_TO_CLASS:
                    cls = TERRAIN_TO_CLASS[final_val]
                    obs_counts[map_y, map_x, cls] += 1.0
                    obs_total[map_y, map_x] += 1.0

    # Blend: where we have observations, weight them heavily
    for y in range(map_h):
        for x in range(map_w):
            if obs_total[y, x] > 0:
                obs_dist = obs_counts[y, x] / obs_total[y, x]
                # Blend: 70% observation, 30% transition model
                prediction[y, x] = 0.7 * obs_dist + 0.3 * prediction[y, x]

    # Safety: floor and renormalize
    prediction = np.maximum(prediction, 0.01)
    prediction = prediction / prediction.sum(axis=-1, keepdims=True)
    return prediction


def main():
    session = get_session()

    active = get_active_round(session)
    if not active:
        print("No active round found!")
        return

    round_id = active["id"]
    detail = get_round_details(session, round_id)
    width = detail["map_width"]
    height = detail["map_height"]
    seeds_count = detail["seeds_count"]

    print(f"Round #{active['round_number']}: {width}x{height}, {seeds_count} seeds")

    budget = check_budget(session)
    remaining = budget["queries_max"] - budget["queries_used"]
    print(f"Budget: {remaining} queries remaining")

    if remaining <= 0:
        print("No queries left! Submitting transition-model predictions based on any prior data.")
        return

    # Allocate queries
    allocation = allocate_queries(seeds_count, remaining)
    print(f"Query allocation per seed: {allocation}")

    # Collect initial grids
    initial_grids = [state["grid"] for state in detail["initial_states"]]

    # Phase 1: Collect observations from all seeds
    all_observations = {}
    for seed_idx in range(seeds_count):
        if allocation[seed_idx] <= 0:
            all_observations[seed_idx] = []
            continue

        print(f"\nQuerying seed {seed_idx} ({allocation[seed_idx]} queries)...")
        obs = collect_observations(session, round_id, seed_idx,
                                   allocation[seed_idx], width, height)
        all_observations[seed_idx] = obs

    # Phase 2: Build cross-seed transition model
    print("\nBuilding transition model from all observations...")
    transition_model = build_transition_model(initial_grids, all_observations, height, width)

    print("Learned transitions (initial → final class probabilities):")
    class_names = ["Empty", "Settlement", "Port", "Ruin", "Forest", "Mountain"]
    for cls, probs in transition_model.items():
        top_3 = sorted(enumerate(probs), key=lambda x: -x[1])[:3]
        top_str = ", ".join(f"{class_names[i]}:{p:.2f}" for i, p in top_3)
        print(f"  {class_names[cls]:12s} → {top_str}")

    # Phase 3: Build and submit improved predictions
    print("\nSubmitting improved predictions...")
    for seed_idx in range(seeds_count):
        prediction = build_improved_prediction(
            initial_grids[seed_idx],
            all_observations[seed_idx],
            transition_model,
            height, width,
        )
        result = submit_prediction(session, round_id, seed_idx, prediction)
        print(f"Seed {seed_idx}: {result}")

    print("\nDone! Check scores at /my-rounds endpoint.")


if __name__ == "__main__":
    main()
