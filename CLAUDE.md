# NM i AI 2026 — Competition Project

## Overview
Three independent AI competition tasks. Each subdirectory is a separate task.
Overall score = average of normalized scores across all three tasks (33% each).

## Project Structure
```
tripletex/      — AI accounting agent (FastAPI + Claude API)
astar-island/   — Viking world prediction (Python + numpy)
norgesgruppen/  — Grocery object detection (YOLOv8 + ultralytics)
```

## Key APIs
- Competition platform: app.ainm.no
- Competition API: api.ainm.no
- MCP docs: `claude mcp add --transport http nmiai https://mcp-docs.ainm.no/mcp`

## Auth
JWT token from app.ainm.no cookies stored in `.env` as `AINM_JWT_TOKEN`.
Anthropic API key in `.env` as `ANTHROPIC_API_KEY`.

## Critical Rules
1. **Submit early, submit often** — bad runs never lower your score
2. NorgesGruppen: `ultralytics==8.1.0` exactly, no `os`/`sys`/`subprocess` in run.py
3. Astar Island: NEVER assign probability 0.0 — always floor at 0.01 and renormalize
4. Tripletex: minimize API calls and avoid 4xx errors (efficiency is scored)
