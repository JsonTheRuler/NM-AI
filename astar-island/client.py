"""
Astar Island API Client — NM i AI 2026
Handles all API interactions: rounds, simulation queries, predictions, analysis.
"""

import os
from pathlib import Path

import numpy as np
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_URL = "https://api.ainm.no"


def get_session() -> requests.Session:
    """Create authenticated session using JWT token."""
    token = os.environ.get("AINM_JWT_TOKEN")
    if not token:
        raise ValueError("AINM_JWT_TOKEN not set in .env")
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    return session


def get_active_round(session: requests.Session) -> dict | None:
    """Find the currently active round."""
    rounds = session.get(f"{BASE_URL}/astar-island/rounds").json()
    return next((r for r in rounds if r["status"] == "active"), None)


def get_round_details(session: requests.Session, round_id: str) -> dict:
    """Get full round details including initial states for all seeds."""
    return session.get(f"{BASE_URL}/astar-island/rounds/{round_id}").json()


def check_budget(session: requests.Session) -> dict:
    """Check remaining query budget."""
    return session.get(f"{BASE_URL}/astar-island/budget").json()


def simulate(session: requests.Session, round_id: str, seed_index: int,
             viewport_x: int = 0, viewport_y: int = 0,
             viewport_w: int = 15, viewport_h: int = 15) -> dict:
    """Run one simulation query. Costs 1 from the 50-query budget."""
    return session.post(f"{BASE_URL}/astar-island/simulate", json={
        "round_id": round_id,
        "seed_index": seed_index,
        "viewport_x": viewport_x,
        "viewport_y": viewport_y,
        "viewport_w": viewport_w,
        "viewport_h": viewport_h,
    }).json()


def submit_prediction(session: requests.Session, round_id: str,
                      seed_index: int, prediction: np.ndarray) -> dict:
    """Submit H×W×6 probability tensor for one seed."""
    # Safety: floor at 0.01 and renormalize to prevent KL divergence blowup
    prediction = np.maximum(prediction, 0.01)
    prediction = prediction / prediction.sum(axis=-1, keepdims=True)

    return session.post(f"{BASE_URL}/astar-island/submit", json={
        "round_id": round_id,
        "seed_index": seed_index,
        "prediction": prediction.tolist(),
    }).json()


def get_my_rounds(session: requests.Session) -> list:
    """Get all rounds with team scores and budget info."""
    return session.get(f"{BASE_URL}/astar-island/my-rounds").json()


def get_analysis(session: requests.Session, round_id: str, seed_index: int) -> dict:
    """Post-round analysis: your prediction vs ground truth."""
    return session.get(f"{BASE_URL}/astar-island/analysis/{round_id}/{seed_index}").json()


# --- Query Strategy ---

def generate_viewport_grid(map_w: int = 40, map_h: int = 40, vp_size: int = 15) -> list[tuple]:
    """Generate non-overlapping viewport positions to cover the full map.
    Returns list of (x, y, w, h) tuples."""
    viewports = []
    y = 0
    while y < map_h:
        x = 0
        h = min(vp_size, map_h - y)
        while x < map_w:
            w = min(vp_size, map_w - x)
            viewports.append((x, y, w, h))
            x += vp_size
        y += vp_size
    return viewports


def query_full_map(session: requests.Session, round_id: str, seed_index: int,
                   map_w: int = 40, map_h: int = 40) -> np.ndarray:
    """Query enough viewports to cover the full map for one seed.
    Uses ~9 queries (3×3 grid of 15×15 viewports for 40×40 map)."""
    full_grid = np.full((map_h, map_w), -1, dtype=int)
    viewports = generate_viewport_grid(map_w, map_h)

    for vx, vy, vw, vh in viewports:
        result = simulate(session, round_id, seed_index, vx, vy, vw, vh)
        if "grid" in result:
            grid = np.array(result["grid"])
            full_grid[vy:vy + vh, vx:vx + vw] = grid
        if result.get("queries_used", 0) >= result.get("queries_max", 50):
            print(f"Budget exhausted after querying seed {seed_index}")
            break

    return full_grid


# --- Prediction Building ---

# Terrain class mapping for predictions
# 0=Empty (Ocean/Plains/Empty), 1=Settlement, 2=Port, 3=Ruin, 4=Forest, 5=Mountain
TERRAIN_TO_CLASS = {
    0: 0,   # Empty → class 0
    1: 1,   # Settlement → class 1
    2: 2,   # Port → class 2
    3: 3,   # Ruin → class 3
    4: 4,   # Forest → class 4
    5: 5,   # Mountain → class 5
    10: 0,  # Ocean → class 0 (Empty)
    11: 0,  # Plains → class 0 (Empty)
}


def build_prediction_from_observations(observations: list[np.ndarray],
                                       height: int = 40, width: int = 40) -> np.ndarray:
    """Build probability tensor from multiple simulation observations.

    Args:
        observations: List of full-map grids (height × width) from simulate calls.
                     Use -1 for unobserved cells.
        height: Map height
        width: Map width

    Returns:
        height × width × 6 probability tensor
    """
    # Count occurrences of each class per cell
    counts = np.ones((height, width, 6)) * 0.01  # Start with small uniform prior

    for grid in observations:
        for y in range(height):
            for x in range(width):
                cell_val = grid[y, x]
                if cell_val >= 0 and cell_val in TERRAIN_TO_CLASS:
                    class_idx = TERRAIN_TO_CLASS[cell_val]
                    counts[y, x, class_idx] += 1.0

    # Normalize to probabilities
    prediction = counts / counts.sum(axis=-1, keepdims=True)
    return prediction


def build_initial_state_prediction(initial_grid: list[list[int]],
                                   height: int = 40, width: int = 40) -> np.ndarray:
    """Build a baseline prediction from the initial state alone.
    Assigns high probability to static terrain (ocean, mountain) and
    uniform-ish probabilities to dynamic cells."""
    prediction = np.full((height, width, 6), 1 / 6)

    grid = np.array(initial_grid)
    for y in range(height):
        for x in range(width):
            val = grid[y, x]
            if val == 10:  # Ocean — almost always stays ocean
                prediction[y, x] = [0.95, 0.01, 0.01, 0.01, 0.01, 0.01]
            elif val == 5:  # Mountain — usually stays mountain
                prediction[y, x] = [0.05, 0.01, 0.01, 0.01, 0.01, 0.91]
            elif val == 4:  # Forest — often stays but can change
                prediction[y, x] = [0.10, 0.05, 0.02, 0.05, 0.73, 0.05]
            elif val == 11:  # Plains — dynamic, could become anything
                prediction[y, x] = [0.40, 0.15, 0.05, 0.10, 0.25, 0.05]
            elif val == 1:  # Settlement — may survive or become ruin
                prediction[y, x] = [0.05, 0.40, 0.10, 0.30, 0.10, 0.05]
            elif val == 2:  # Port — similar to settlement
                prediction[y, x] = [0.05, 0.15, 0.35, 0.30, 0.10, 0.05]
            elif val == 0:  # Empty
                prediction[y, x] = [0.50, 0.10, 0.05, 0.10, 0.20, 0.05]

    # Safety: floor and renormalize
    prediction = np.maximum(prediction, 0.01)
    prediction = prediction / prediction.sum(axis=-1, keepdims=True)
    return prediction
