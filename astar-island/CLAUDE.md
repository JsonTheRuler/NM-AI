# Astar Island — Viking Civilisation Prediction

## Your Mission
Predict the final terrain state of a 40×40 Norse world simulator after 50 years. Submit probability distributions (H×W×6 tensor) for 5 seeds per round.

## Key Files
- `client.py` — API client with all endpoints + prediction utilities
- `submit_baseline.py` — Submit initial-state-based baseline (run ASAP)
- `query_and_improve.py` — Strategic querying + cross-seed learning

## Running
```bash
pip install -r requirements.txt
python submit_baseline.py       # Submit baseline predictions immediately
python query_and_improve.py     # Use simulation queries to improve
```

## API (api.ainm.no)
- `GET /astar-island/rounds` — List rounds
- `GET /astar-island/rounds/{id}` — Round details + initial states (FREE, no query cost)
- `POST /astar-island/simulate` — Observe 15×15 viewport (costs 1 query)
- `POST /astar-island/submit` — Submit H×W×6 prediction for one seed
- `GET /astar-island/my-rounds` — Your scores
- `GET /astar-island/analysis/{round_id}/{seed_index}` — Post-round ground truth

## Constraints
- 50 queries per round, shared across all 5 seeds
- Each query reveals max 15×15 viewport of 40×40 map
- Each query runs a DIFFERENT stochastic simulation (different sim_seed)
- Hidden parameters are SHARED across all 5 seeds in a round

## 6 Terrain Classes
0=Empty (Ocean/Plains), 1=Settlement, 2=Port, 3=Ruin, 4=Forest, 5=Mountain

## CRITICAL
- **NEVER assign probability 0.0** — floor at 0.01, renormalize. KL divergence → infinity otherwise.
- **Submit something for every seed** — even uniform (1/6 each) beats 0.
- **Later rounds weighted higher** (1.05^round_number) — improve your model over time.
- Scoring uses entropy-weighted KL divergence — focus on dynamic cells, not static ones.

## Strategy
1. Initial states are FREE — use them for baseline predictions
2. Cross-seed learning: same hidden parameters across seeds
3. Build terrain transition model: P(final_class | initial_class)
4. Allocate ~10 queries per seed for map coverage
5. After each round, analyze ground truth to improve the model
