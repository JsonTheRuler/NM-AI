"""
Submit baseline predictions for all seeds in the active round.
Run this ASAP — even a bad prediction beats 0.

Usage: python submit_baseline.py
"""

from client import (
    get_session, get_active_round, get_round_details,
    submit_prediction, build_initial_state_prediction, check_budget,
)


def main():
    session = get_session()

    # Find active round
    active = get_active_round(session)
    if not active:
        print("No active round found!")
        return

    round_id = active["id"]
    print(f"Active round: #{active['round_number']} ({active['map_width']}x{active['map_height']})")

    # Get details with initial states
    detail = get_round_details(session, round_id)
    width = detail["map_width"]
    height = detail["map_height"]
    seeds_count = detail["seeds_count"]

    print(f"Seeds: {seeds_count}, Map: {width}x{height}")

    # Check budget
    budget = check_budget(session)
    print(f"Budget: {budget['queries_used']}/{budget['queries_max']} used")

    # Submit baseline predictions for each seed using initial state only
    for i, state in enumerate(detail["initial_states"]):
        grid = state["grid"]
        prediction = build_initial_state_prediction(grid, height, width)

        result = submit_prediction(session, round_id, i, prediction)
        print(f"Seed {i}: {result}")

    print("\nBaseline predictions submitted for all seeds!")
    print("Now run query_and_improve.py to use simulation queries for better predictions.")


if __name__ == "__main__":
    main()
