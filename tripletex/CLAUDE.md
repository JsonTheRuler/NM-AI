# Tripletex AI Accounting Agent

## Your Mission
Build an AI agent that receives accounting task prompts (in 7 languages) and executes the correct Tripletex API calls to complete them. Scored on correctness + API efficiency.

## Architecture
```
POST /solve → Claude parses prompt → Plans API calls → Executes them → Returns {"status": "completed"}
```

## Key Files
- `main.py` — FastAPI endpoint with Claude-powered task execution
- `requirements.txt` — Python dependencies

## Running
```bash
pip install -r requirements.txt
python main.py                                          # Start server on :8000
npx cloudflared tunnel --url http://localhost:8000       # HTTPS tunnel
```
Then submit the tunnel URL at https://app.ainm.no/submit/tripletex

## Tripletex API
- Base URL: from `tripletex_credentials.base_url` in each request
- Auth: Basic Auth with username "0" and session_token as password
- Docs: https://tripletex.no/v2-docs/ (explore via sandbox)

## Sandbox
- URL: https://kkpqfuj-amager.tripletex.dev
- Use for exploring the API before competition submissions
- Each competition submission gets a FRESH account

## Task Types (30 total, 3 tiers)
**Tier 1** (simple): Create employee, customer, product, invoice
**Tier 2** (multi-step): Invoice+payment, credit notes, project billing, travel expenses
**Tier 3** (complex, Saturday): Bank reconciliation, error correction, year-end closing

## Scoring
- Field-by-field correctness checks (0.0 - 2.0 per tier)
- Efficiency bonus for perfect submissions (fewer API calls = higher score, up to 6.0)
- Error cleanliness (4xx errors reduce bonus)
- Best score per task kept forever

## Priority Work
1. Make the basic agent work end-to-end (parse prompt → API calls → completion)
2. Handle all Tier 1 tasks reliably
3. Handle file attachments (PDF/image via Claude vision)
4. Optimize API call efficiency
5. Handle Tier 2 tasks
6. Prepare for Tier 3

## Important
- Prompts come in 7 languages (Norwegian, English, Spanish, Portuguese, Nynorsk, German, French)
- Claude handles multilingual natively — no special translation needed
- Some tasks include PDF/image attachments with invoice data, contracts, etc.
- Each submission gets a brand new Tripletex account — always start from scratch
- 5-minute timeout per submission
