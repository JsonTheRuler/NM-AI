# STRATEGY.md — Team EasyEiendom Final Battle Plan
## NM i AI 2026 · Tripletex AI Accounting Agent

**Status:** EXECUTE THIS  
**Date:** 2026-03-20  
**Authors:** Synthesized from Strategist + Devil's Advocate

---

## 1. Decision Log

| # | Disagreement | Decision | Reason |
|---|-------------|----------|--------|
| 1 | **Model: Sonnet vs Opus** | **Opus default** | Devil's Advocate wins. The timeout math proves Opus fits within 300s even worst-case (260s). Correctness on Tier 2/3 accounting tasks (VAT, bank reconciliation, Nynorsk) matters more than 5s/turn speed. We cannot recover from conceptual errors via retries. |
| 2 | **System prompt: skeleton vs empirical** | **Empirical discovery first, then write prompt** | Devil's Advocate wins. The Strategist's prompt has dangerous gaps (VAT type IDs, module activation, payment flow). We must hit the sandbox API and record actual required fields before writing the final prompt. |
| 3 | **Loop control: 20 iterations vs hard budget** | **Hybrid: 15 iterations AND 12-call soft budget with injection** | Third option. Hard-killing at 12 calls risks aborting legitimate complex tasks. Instead: inject call count into each turn so Claude self-regulates, and switch to "conservative mode" after 2 errors. Cap at 15 iterations as safety net. |
| 4 | **Testing: manual vs automated** | **Automated verification + early platform submissions** | Devil's Advocate wins. Manual UI checking is too slow. Build programmatic verification. But the real testing ground is the competition platform itself — submit early and often. |
| 5 | **Deployment: ephemeral tunnel vs named** | **Named cloudflared tunnel + cloud Dockerfile ready** | Devil's Advocate wins on named tunnel. Set up a fixed subdomain so URL never changes. Have a Railway/Fly.io Dockerfile as hot standby but don't deploy it unless local fails. |
| 6 | **Streaming tool-use** | **Yes, core architecture** | Devil's Advocate wins. Streaming tool-use saves 1-3s per turn × 10 turns = meaningful. Implement from the start. |
| 7 | **Concurrent submissions** | **Sequential, not parallel** | Devil's Advocate wins. Risk of hitting the same task type 3× wastes our 10/task/day limit. Submit one at a time. |
| 8 | **"Verify after create" in prompt** | **Remove it** | Strategist is right. Never GET to verify a POST you just made. The response has the data. The challenge spec's tip to "verify" is a trap for efficiency. |

---

## 2. Final Architecture

### Core Loop: Agentic Tool-Use with Budget Awareness

```
POST /solve
  ├─ Parse request (prompt, files, credentials)
  ├─ Build system prompt + user message (with files as content blocks)
  ├─ Send to Claude Opus with tool definitions
  └─ LOOP (max 15 iterations):
       ├─ Claude returns tool_use or text (done signal)
       ├─ If tool_use "tripletex_api":
       │    ├─ Validate required fields (pre-flight check)
       │    ├─ Execute API call
       │    ├─ Increment call_count; track error_count if 4xx
       │    ├─ Feed result back to Claude WITH budget status
       │    └─ If error_count >= 2: inject conservative mode message
       ├─ If tool_use "task_complete": break
       ├─ If elapsed > 240s: force break, return completed
       └─ If call_count > 12: inject "budget exceeded" warning (don't hard-kill)
  Return {"status": "completed"}
```

### Tool Definitions

```python
TOOLS = [
    {
        "name": "tripletex_api",
        "description": "Call the Tripletex v2 REST API. Use this for all API operations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE"],
                    "description": "HTTP method"
                },
                "endpoint": {
                    "type": "string",
                    "description": "API path, e.g. /employee, /customer/123"
                },
                "params": {
                    "type": "object",
                    "description": "Query parameters (for GET requests, filtering, fields selection)"
                },
                "json_body": {
                    "type": "object",
                    "description": "JSON request body (for POST/PUT)"
                }
            },
            "required": ["method", "endpoint"]
        }
    },
    {
        "name": "task_complete",
        "description": "Signal that the task is done. Call ONLY when all required operations are finished.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One-line summary of what was accomplished"
                }
            },
            "required": ["summary"]
        }
    }
]
```

### Budget Injection (per turn)

After each API call result, prepend this to the tool result:

```
[BUDGET: {call_count}/{MAX_CALLS} calls used | {error_count} errors | {elapsed}s elapsed | {remaining} calls left]
```

### Conservative Mode (triggered at error_count >= 2)

Inject as a system-level message:

```
⚠️ CONSERVATIVE MODE: You have made {error_count} errors. Stop exploring.
Execute ONLY calls you are confident about. If unsure about a step, skip it.
Partial completion is better than more errors.
```

### Pre-flight Validation

Before sending any POST/PUT to Tripletex, check in code:

```python
REQUIRED_FIELDS = {
    "/employee": ["firstName", "lastName"],
    "/customer": ["name"],
    "/product": ["name"],
    "/order": ["customer", "orderDate", "deliveryDate"],
    "/orderline": ["order", "product", "count"],
    "/invoice": ["invoiceDate", "invoiceDueDate", "orders"],
    "/department": ["name", "departmentNumber"],
    "/project": ["name", "projectManager"],
}

def validate_before_send(endpoint: str, body: dict) -> str | None:
    """Returns error message if validation fails, None if OK."""
    # Strip ID suffix: /employee/123 -> /employee
    base = "/" + endpoint.strip("/").split("/")[0]
    required = REQUIRED_FIELDS.get(base, [])
    missing = [f for f in required if f not in (body or {})]
    if missing:
        return f"Missing required fields for {base}: {missing}. Add them before calling."
    return None
```

If validation fails, return the error to Claude WITHOUT making the API call. This saves a 422 and an API call.

### Streaming

Use `stream=True` on the Anthropic API call and process tool_use events as they arrive:

```python
with claude.messages.stream(
    model="claude-opus-4-0-20250514",
    max_tokens=4096,
    system=system_prompt,
    messages=messages,
    tools=TOOLS,
) as stream:
    response = stream.get_final_message()
```

This gets us the tool call faster (don't wait for full response generation).

### File Handling

Files are passed as Claude content blocks (current approach). Key rules:
- Images → `type: "image"` with base64 source
- PDFs → `type: "document"` with base64 source  
- System prompt tells Claude to fully parse all files BEFORE making any API calls

---

## 3. System Prompt

**This is the actual system prompt to use. Copy-paste it.**

```
You are a Tripletex accounting API agent. You receive a task prompt and execute
the minimum necessary API calls to complete it correctly.

You are scored on: (1) correctness, (2) fewest API calls, (3) zero 4xx errors.
A perfect task with good efficiency scores up to 6.0. A failed task scores 0.0.

## CRITICAL RULES — READ THESE FIRST
- NEVER make a GET call to verify something you just created — the POST response contains the data.
- NEVER search for an entity you just created — use the ID from the POST response directly.
- The Tripletex sandbox starts EMPTY. Don't search for pre-existing data unless the task explicitly says to modify or delete existing records.
- If a task says "create X", just POST directly. Don't GET first to "check if it exists."
- Plan your complete sequence BEFORE making any calls, but adapt based on actual responses.
- Use field values EXACTLY as they appear in the prompt. Do NOT normalize, capitalize, trim, or translate any values. Copy them character-for-character.
- Only use endpoints listed in this reference. Do NOT guess or hallucinate endpoint paths.

## DATE HANDLING
- Dates in Norwegian/European prompts use DD.MM.YYYY format.
- Convert to YYYY-MM-DD for the API. Example: 03.04.2026 → 2026-04-03 (April 3rd, NOT March 4th).
- When no date is specified, use today's date.
- For invoices: set invoiceDueDate to 14 days after invoiceDate unless specified.

## LANGUAGE HANDLING
The prompt may be in Norwegian (Bokmål), Nynorsk, English, Spanish, Portuguese, German, or French.
Parse in whatever language it arrives. Extract ALL field values exactly as written.
Do not translate proper nouns (names, company names, emails, addresses).

## FILE HANDLING
If files are attached, examine them COMPLETELY before making any API calls.
Extract ALL data: names, amounts, dates, account numbers, line items, totals.
Do not start API operations until you have fully parsed every attached document.

## API REFERENCE

### Employees
POST /employee — Required: firstName, lastName. Optional: email, phoneNumberMobile, dateOfBirth
PUT /employee/{id} — Update employee fields
GET /employee — Search with params: firstName, lastName, email, fields

### Customers
POST /customer — Required: name, isCustomer (MUST be true). Optional: email, phoneNumber, postalAddress
PUT /customer/{id} — Update customer
GET /customer — Search by name, email

### Products
POST /product — Required: name. Optional: number, priceExcludingVatCurrency, vatType (object with id)
GET /product — Search by name, number
NOTE: For vatType, you may need to GET /ledger/vatType first to find the correct ID.
Common Norwegian VAT types: 25% (standard MVA), 15% (food), 0% (exempt).

### Orders
POST /order — Required: customer (object with id), orderDate (YYYY-MM-DD), deliveryDate (YYYY-MM-DD)
GET /order — Query orders

### Order Lines
POST /orderline — Required: order (object with id), product (object with id), count (number)
Optional: unitPriceExcludingVatCurrency, description

### Invoices
POST /invoice — Required: invoiceDate, invoiceDueDate, orders (array of objects with id)
NOTE: The customer is derived from the order. Do NOT set customer directly on the invoice.
GET /invoice — Query invoices

### Credit Notes
PUT /invoice/{id}/:createCreditNote — Creates credit note for existing invoice
Check if this needs a request body (test empirically).

### Payments
POST /payment — Study the actual required fields via sandbox exploration.
May require: paymentDate, amount, kid, bankAccount, or direct invoice link.
Alternative: There may be a /invoice/{id}/:pay endpoint.

### Projects
POST /project — Required: name, projectManager (object with id — must be an employee ID)
Optional: customer (object with id), description, startDate, endDate

### Departments
POST /department — Required: name, departmentNumber (string/number)
NOTE: May require activating department accounting module first.
Try: PUT /company/settings or check /modules endpoint if you get an error.

### Travel Expenses
POST /travelExpense — Required: employee (object with id), departureDate, returnDate
GET /travelExpense — Search travel expenses
DELETE /travelExpense/{id} — Delete a travel expense

### Ledger & Accounting
GET /ledger/vatType — List available VAT types (IMPORTANT: get IDs from here, don't guess)
GET /ledger/account — Chart of accounts
GET /ledger/posting — Query ledger postings
POST /ledger/voucher — Create vouchers
DELETE /ledger/voucher/{id} — Delete vouchers

## ENTITY DEPENDENCY CHAIN
Invoice requires → Order (which requires → Customer)
Order Line requires → Order + Product
Payment requires → Invoice
Project often requires → Customer + Employee (as project manager)
Credit Note requires → existing Invoice ID
Travel Expense requires → Employee
Department may require → Module activation first

## ERROR RECOVERY
- If you get a 422: read the error message. It tells you EXACTLY what's wrong. Fix it in ONE retry.
- If you get a 404: the endpoint path is wrong or the ID doesn't exist. Check your path.
- If you get 401: auth issue — shouldn't happen; the auth is automatic.
- MAXIMUM 1 retry per failed call. If it fails twice on the same operation, move on.
- After 2 total errors: be extra careful. Only make calls you are CERTAIN about.

## RESPONSE FORMAT
All list responses: {"fullResultSize": N, "values": [...]}
All single-entity responses: {"value": {"id": ..., ...}}
Use the "id" from creation responses in subsequent calls.
Use ?fields=id,name,... to limit response size. Use ?fields=* to see everything.
```

### Why This Prompt

- **Efficiency rules first** — Claude weights early instructions more heavily
- **Required fields explicit per endpoint** — prevents 422s
- **VAT types addressed** — tells Claude to look them up, not guess
- **Date format explicit** — prevents DD.MM vs MM.DD confusion
- **"Copy character-for-character"** — prevents the "almost right" trap
- **Error budget awareness** — "after 2 total errors, be extra careful"
- **Known unknowns marked** — payment flow and credit notes say "test empirically" because we genuinely don't know yet

---

## 4. Scoring Strategy

### The Math

| Tier | Multiplier | Perfect + best efficiency | Perfect + mediocre efficiency | 80% correct |
|------|-----------|--------------------------|-------------------------------|-------------|
| 1    | ×1        | 2.0                      | ~1.3                          | 0.8         |
| 2    | ×2        | 4.0                      | ~2.6                          | 1.6         |
| 3    | ×3        | 6.0                      | ~3.9                          | 2.4         |

**Key insight:** A perfect Tier 3 with mediocre efficiency (3.9) beats a perfect Tier 1 with best efficiency (2.0) by almost 2×. **Correctness on high-tier tasks is the dominant strategy.**

### Concrete Rules

1. **Correctness is king.** Never sacrifice correctness for efficiency. A 100% correct task with 10 API calls beats a 90% correct task with 3 calls.

2. **Zero 4xx errors on simple tasks.** For Tier 1 (create employee, create customer), there is NO excuse for errors. The pre-flight validation catches missing fields. The system prompt has the required fields. Get these perfect every time.

3. **Minimize calls via these rules:**
   - Never GET after POST (you have the data)
   - Never search for entities you just created
   - Don't check if sandbox is empty — it IS empty
   - Use response IDs directly in subsequent calls
   - Use `?fields=id,name` not `?fields=*` on GETs

4. **For Tier 2/3, allow 1-2 exploratory GETs.** If you need to discover a VAT type ID or check module availability, that's a worthwhile investment. 1 extra GET that prevents a 422 is a net positive.

5. **Efficiency benchmarks recalculate every 12 hours.** Our scores can decay if other teams find more efficient solutions. Track minimum-call-count per task type and optimize.

6. **Best score per task is kept.** Bad runs don't hurt us. Submit aggressively — even a risky submission can only help, never harm.

### Target Scores

- **Tier 1 (10 tasks estimated):** 1.5 avg × 10 = 15.0
- **Tier 2 (10 tasks estimated):** 3.0 avg × 10 = 30.0  
- **Tier 3 (10 tasks estimated):** 4.0 avg × 10 = 40.0
- **Realistic total target: 70-85 points**

---

## 5. Task Coverage — Priority Order

### Phase 1: Lock in Tier 1 (Friday evening → Saturday morning)

| Priority | Task Type | Expected Min Calls | Notes |
|----------|-----------|-------------------|-------|
| 1 | Create employee | 1 | POST /employee — simplest possible task |
| 2 | Create customer | 1 | POST /customer with isCustomer:true |
| 3 | Create product | 1-2 | POST /product, may need GET /ledger/vatType |
| 4 | Create department | 1-2 | May need module activation first |
| 5 | Update employee | 2 | GET /employee + PUT /employee/{id} |
| 6 | Update customer | 2 | GET /customer + PUT /customer/{id} |
| 7 | Delete travel expense | 2 | GET /travelExpense + DELETE |

### Phase 2: Tackle Tier 2 (Saturday)

| Priority | Task Type | Expected Min Calls | Notes |
|----------|-----------|-------------------|-------|
| 8 | Create simple invoice | 4-5 | Customer → Product → Order+OrderLine → Invoice |
| 9 | Create project | 2-3 | Need employee as project manager |
| 10 | Travel expense creation | 2-3 | Need employee first |
| 11 | Invoice with payment | 5-7 | Full invoice chain + payment registration |
| 12 | Credit note | 5-6 | Create invoice chain → credit note |
| 13 | Complex employee setup | 2-3 | Employee + roles/permissions |
| 14 | Multi-line invoice | 5-7 | Multiple products/order lines |

### Phase 3: Tier 3 (Opens Saturday, focus Sunday)

| Priority | Task Type | Expected Min Calls | Notes |
|----------|-----------|-------------------|-------|
| 15 | Bank reconciliation from CSV | 5-15 | Parse CSV, create vouchers |
| 16 | Error correction in ledger | 5-10 | Find error, reverse, correct |
| 17 | Year-end closing | 10-20 | Multiple accounting operations |
| 18+ | Other complex workflows | varies | React and adapt |

### Unknown Tasks

We don't know all 30 types. The agentic architecture handles unknowns well because Claude can reason about novel tasks. When we encounter a new task type:
1. Check the submission result for what checks were performed
2. Update system prompt with learned patterns
3. Re-submit with improved knowledge

---

## 6. Deployment Plan

### Primary: Named cloudflared Tunnel (Local)

```bash
# One-time setup (do this NOW)
cloudflared tunnel create tripletex-agent
cloudflared tunnel route dns tripletex-agent agent.yourdomain.com
# Or use the free *.trycloudflare.com URL from `cloudflared tunnel --url`

# Run the server
cd /Users/mactias/Documents/NM-AI/tripletex
python main.py &

# Run the tunnel (persistent)
cloudflared tunnel run tripletex-agent
```

**If no custom domain:** Use `cloudflared tunnel --url http://localhost:8000` but wrap in a restart loop:

```bash
while true; do
    cloudflared tunnel --url http://localhost:8000 2>&1 | tee tunnel.log
    echo "Tunnel died, restarting in 5s..."
    sleep 5
done
```

### Machine Hardening

- Wired ethernet (not WiFi)
- Disable macOS sleep: `sudo pmset -a disablesleep 1`
- Run in tmux: server in one pane, tunnel in another, logs in third
- Disable automatic macOS updates for the weekend

### Backup: Cloud Deployment

Have a `Dockerfile` ready but don't deploy unless local fails:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Deploy to Railway/Fly.io in <5 minutes if needed.

### Logging

Log EVERYTHING to a file with timestamps:

```python
import logging
logging.basicConfig(
    filename="agent.log",
    level=logging.INFO,
    format="%(asctime)s | %(message)s"
)

# Log every API call and response
# Log every Claude tool-use decision
# Log call count, error count, elapsed time per task
# Log the final score when we check the platform
```

---

## 7. Testing Protocol

### Pre-Competition Testing (Do This Friday Evening)

#### Step 1: API Discovery (2 hours)

For each critical operation, do it manually and record the exact API behavior:

```bash
# Run these against the sandbox and document results:
# 1. Create employee — what fields, what response format
# 2. Create customer — confirm isCustomer:true is required
# 3. Create product with VAT — what vatType IDs exist
# 4. Create full invoice chain (customer → product → order → orderline → invoice)
# 5. Register payment on invoice — what endpoint, what fields
# 6. Create credit note — what endpoint, what body
# 7. Create department — does it need module activation?
# 8. Create travel expense — what fields required
# 9. Delete travel expense
```

Record findings and UPDATE the system prompt with actual discovered data (especially VAT type IDs and payment flow).

#### Step 2: Automated Test Harness

```python
# test_harness.py
TEST_CASES = [
    {
        "prompt": "Opprett en ansatt med fornavn Ola og etternavn Nordmann med e-post ola@test.no",
        "verify": lambda api: api.get("/employee", params={"firstName": "Ola", "fields": "id,firstName,lastName,email"}),
        "expect": {"firstName": "Ola", "lastName": "Nordmann"},
        "max_calls": 1,
    },
    {
        "prompt": "Create a customer called Acme AS with email info@acme.no",
        "verify": lambda api: api.get("/customer", params={"name": "Acme", "fields": "id,name,email"}),
        "expect": {"name": "Acme AS"},
        "max_calls": 1,
    },
    # Add test cases in all 7 languages
    {
        "prompt": "Erstellen Sie einen Mitarbeiter mit dem Vornamen Hans und dem Nachnamen Müller",
        "verify": lambda api: api.get("/employee", params={"firstName": "Hans", "fields": "id,firstName,lastName"}),
        "expect": {"firstName": "Hans", "lastName": "Müller"},
        "max_calls": 1,
    },
    # ... more for each task type
]
```

**Important:** The sandbox is persistent, so either:
- Use unique names per test run (timestamp suffix), OR
- Accept that verification may find entities from prior runs (filter by most recent)

#### Step 3: Platform Submissions (Saturday onwards)

- Submit every 5-10 minutes during active hours
- After each result: check the platform dashboard for score + checks performed
- Log: task type → score → number of API calls → errors
- Maintain a tracking spreadsheet:

```
| Task Type | Best Score | Attempts | Known Issues | Min Calls Achieved |
|-----------|-----------|----------|--------------|-------------------|
| create_employee | 2.0 | 3 | none | 1 |
| create_invoice | 1.8 | 5 | VAT type wrong once | 5 |
```

- Submit **sequentially** (one at a time, not concurrent)

---

## 8. Prioritized TODO

### 🔴 CRITICAL — Do Before Competition (Friday Evening)

- [ ] **1. Rewrite main.py to agentic tool-use loop** (~2h)
  - Replace single-shot JSON planning with tool-use loop
  - Implement TOOLS definitions
  - Implement budget tracking + injection
  - Implement conservative mode on 2+ errors
  - Implement streaming (`messages.stream()`)
  - Implement 240s hard timeout with graceful exit
  - Implement pre-flight validation for required fields

- [ ] **2. API Discovery Session** (~2h)
  - Manually hit every critical endpoint in the sandbox
  - Record actual required fields, response formats, error messages
  - Discover VAT type IDs in sandbox
  - Test payment registration flow end-to-end
  - Test credit note creation
  - Test department creation (module activation?)
  - Update system prompt with ALL discovered data

- [ ] **3. Write final system prompt** (~30min)
  - Start from the template in §3 above
  - Fill in empirically discovered data from step 2
  - Test with a few prompts to verify Claude follows the rules

- [ ] **4. Set up deployment** (~30min)
  - Named cloudflared tunnel OR persistent restart loop
  - tmux session with server + tunnel + log tail
  - Disable sleep, confirm wired ethernet
  - Prepare Dockerfile as backup

### 🟡 IMPORTANT — Do Saturday Morning

- [ ] **5. Build test harness** (~1h)
  - Automated verification for at least 10 task types
  - Multi-language test cases
  - Call-count and error tracking

- [ ] **6. First wave of platform submissions** (~ongoing)
  - Submit continuously, monitor results
  - Track every task type encountered
  - Update system prompt based on failures

- [ ] **7. Payment & credit note handling** (~1h)
  - Based on API discovery results and first failed submissions
  - May need custom logic or additional system prompt sections

### 🟢 NICE TO HAVE — Saturday Afternoon / Sunday

- [ ] **8. Efficiency optimization pass**
  - For each task type where we score 1.0 correctness but low efficiency
  - Identify which API calls are unnecessary
  - Add task-specific hints to system prompt

- [ ] **9. Tier 3 preparation**
  - When Tier 3 opens, analyze the new task types
  - Explore bank reconciliation, voucher, and ledger APIs
  - Update system prompt for complex accounting workflows

- [ ] **10. Dynamic model selection** (ONLY if Opus timeouts observed)
  - Not expected to be needed based on math
  - If we see actual timeouts: fall back to Sonnet for that specific retry
  - Do NOT implement preemptively — premature optimization

---

## Appendix A: Code Skeleton for main.py Rewrite

```python
"""
Tripletex AI Agent — Agentic Tool-Use Architecture
Team EasyEiendom · NM i AI 2026
"""

import base64
import json
import logging
import os
import time
from pathlib import Path

import anthropic
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    filename="agent.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Tripletex AI Agent")
claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

MODEL = "claude-opus-4-0-20250514"
MAX_ITERATIONS = 15
TIMEOUT_SECONDS = 240
CALL_BUDGET_SOFT = 12
MAX_ERRORS_BEFORE_CONSERVATIVE = 2

SYSTEM_PROMPT = """..."""  # Paste full prompt from §3

TOOLS = [...]  # Paste from §2

REQUIRED_FIELDS = {
    "/employee": ["firstName", "lastName"],
    "/customer": ["name"],
    "/product": ["name"],
    "/order": ["customer", "orderDate", "deliveryDate"],
    "/orderline": ["order", "product", "count"],
    "/invoice": ["invoiceDate", "invoiceDueDate", "orders"],
    "/department": ["name", "departmentNumber"],
    "/project": ["name", "projectManager"],
}


def validate_body(endpoint: str, body: dict | None) -> str | None:
    base = "/" + endpoint.strip("/").split("/")[0]
    required = REQUIRED_FIELDS.get(base, [])
    missing = [f for f in required if f not in (body or {})]
    return f"Missing required fields for {base}: {missing}" if missing else None


def call_tripletex(base_url: str, token: str, method: str, endpoint: str,
                   params: dict = None, json_body: dict = None) -> dict:
    url = f"{base_url}{endpoint}"
    auth = ("0", token)
    resp = getattr(requests, method.lower())(
        url, auth=auth, params=params,
        **({"json": json_body} if json_body and method.upper() in ("POST", "PUT") else {})
    )
    try:
        data = resp.json()
    except Exception:
        data = resp.text
    logger.info(f"API {method} {endpoint} → {resp.status_code}")
    return {"status_code": resp.status_code, "data": data}


def build_user_message(prompt: str, files: list[dict]) -> list:
    """Build user message content blocks including files."""
    parts = [{"type": "text", "text": f"TASK:\n{prompt}"}]
    for f in files:
        fname = f["filename"].lower()
        if fname.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            ext = fname.rsplit(".", 1)[-1]
            if ext == "jpg":
                ext = "jpeg"
            parts.append({
                "type": "image",
                "source": {"type": "base64", "media_type": f"image/{ext}", "data": f["content_base64"]}
            })
        elif fname.endswith(".pdf"):
            parts.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": f["content_base64"]}
            })
    return parts


@app.post("/solve")
async def solve(request: Request):
    body = await request.json()
    prompt = body["prompt"]
    files = body.get("files", [])
    creds = body["tripletex_credentials"]
    base_url = creds["base_url"]
    token = creds["session_token"]

    logger.info(f"=== NEW TASK === Prompt: {prompt[:100]}...")

    messages = [{"role": "user", "content": build_user_message(prompt, files)}]

    start_time = time.time()
    call_count = 0
    error_count = 0

    for iteration in range(MAX_ITERATIONS):
        elapsed = time.time() - start_time
        if elapsed > TIMEOUT_SECONDS:
            logger.warning(f"Timeout at {elapsed:.0f}s, iteration {iteration}")
            break

        # Use streaming for faster tool-call detection
        response = claude.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
        )

        # Process response
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Check for tool use
        tool_uses = [b for b in assistant_content if b.type == "tool_use"]

        if not tool_uses:
            # Claude responded with text only — assume done
            logger.info("Claude returned text (no tool use) — task complete")
            break

        # Process each tool call
        tool_results = []
        for tool_use in tool_uses:
            if tool_use.name == "task_complete":
                logger.info(f"Task complete: {tool_use.input.get('summary', 'no summary')}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": "Task marked as complete.",
                })
                messages.append({"role": "user", "content": tool_results})
                # Break out of both loops
                break

            elif tool_use.name == "tripletex_api":
                inp = tool_use.input
                method = inp.get("method", "GET")
                endpoint = inp.get("endpoint", "")
                params = inp.get("params")
                json_body = inp.get("json_body")

                # Pre-flight validation
                if method.upper() in ("POST", "PUT"):
                    validation_error = validate_body(endpoint, json_body)
                    if validation_error:
                        logger.warning(f"Pre-flight validation failed: {validation_error}")
                        budget_msg = f"[BUDGET: {call_count}/{CALL_BUDGET_SOFT} calls | {error_count} errors | {elapsed:.0f}s elapsed]\n"
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": budget_msg + f"VALIDATION ERROR (no API call made): {validation_error}",
                        })
                        continue

                # Execute the API call
                result = call_tripletex(base_url, token, method, endpoint, params, json_body)
                call_count += 1

                if 400 <= result["status_code"] < 500:
                    error_count += 1
                    logger.warning(f"4xx error #{error_count}: {result['status_code']} on {method} {endpoint}")

                # Build result with budget info
                budget_msg = f"[BUDGET: {call_count}/{CALL_BUDGET_SOFT} calls | {error_count} errors | {time.time() - start_time:.0f}s elapsed]"

                conservative_msg = ""
                if error_count >= MAX_ERRORS_BEFORE_CONSERVATIVE:
                    conservative_msg = "\n⚠️ CONSERVATIVE MODE: Multiple errors detected. Only make calls you are CERTAIN about."

                if call_count > CALL_BUDGET_SOFT:
                    conservative_msg += "\n⚠️ BUDGET WARNING: You have exceeded the soft call budget. Wrap up immediately."

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": f"{budget_msg}{conservative_msg}\n\nHTTP {result['status_code']}:\n{json.dumps(result['data'], indent=2, ensure_ascii=False)[:3000]}",
                })
            else:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": f"Unknown tool: {tool_use.name}",
                    "is_error": True,
                })
        else:
            # for/else: only runs if we didn't break (no task_complete)
            messages.append({"role": "user", "content": tool_results})
            continue
        break  # task_complete was called

    elapsed = time.time() - start_time
    logger.info(f"=== DONE === {call_count} calls, {error_count} errors, {elapsed:.1f}s")
    return JSONResponse({"status": "completed"})


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**This skeleton is ~80% of the final implementation.** Fill in the SYSTEM_PROMPT and TOOLS constants, do the API discovery to refine the prompt, and it's ready.

---

## Appendix B: Key Differences from Current main.py

| Current | New |
|---------|-----|
| Single-shot: Claude returns JSON array of calls | Agentic: Claude makes one call at a time, sees results |
| `{CREATED_ID}` string replacement (1 ID only) | Natural: Claude reads response, uses ID in next call |
| No error recovery | Claude sees 4xx, adjusts, retries once |
| No timeout management | 240s hard timeout with graceful exit |
| No efficiency awareness | Budget injection every turn |
| No pre-flight validation | Required field check before API calls |
| Sonnet | Opus |
| No logging | Full logging to file |
