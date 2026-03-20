# Team RAMil — NM i AI 2026: Tripletex Competition Plan

> **Lead Strategist synthesis** — incorporating architecture, scoring optimization, and risk mitigation perspectives.

---

## TL;DR

Replace the fragile single-shot LLM approach with a **structured execution plan** model using Claude's tool_use, named variable context, and dependency resolution. Target zero 4xx errors and minimum API calls to capture efficiency bonuses. Focus first on Tier 1 and 2 (open now), prepare Tier 3 before Saturday.

---

## 1. Scoring Analysis & Strategy

### The Math

```
Task score = correctness (0–1) × tier_multiplier × (1 + efficiency_bonus)

- Tier 1: max 2.0 (perfect + best efficiency)
- Tier 2: max 4.0
- Tier 3: max 6.0

Total leaderboard = sum of best scores across all 30 task types
```

### Critical Insight: Efficiency Bonus Only Triggers at 100% Correctness

Non-perfect submissions get: `correctness × tier_multiplier` — period.  
**Only flawless executions unlock the efficiency multiplier.**

This means: **don't optimize for fewer API calls at the expense of correctness.** Get it right first. Then cut calls.

### Score Targets

| Tier  | Tasks | Max/task | Target | Priority |
|-------|-------|----------|--------|----------|
| Tier 1 | 5    | 2.0      | 2.0 each = 10.0 | ★★★ Now |
| Tier 2 | 5    | 4.0      | 4.0 each = 20.0 | ★★★ Now |
| Tier 3 | 20   | 6.0      | 6.0 each = 120.0 | ★★ Saturday |

**Max theoretical total: 150 points.** Tier 3 is 80% of total score potential.

### Priority Order

1. **Perfect Tier 2** first — 4× multiplier, already open, high ROI
2. **Perfect Tier 1** — foundation, easiest to get right  
3. **Tier 3 architecture** — before Saturday, design handles these

---

## 2. Architecture Decisions

### Current Problems with `main.py`

| Problem | Impact |
|---------|--------|
| Single `{CREATED_ID}` substitution | Breaks on multi-resource tasks (invoice needs customer AND order IDs) |
| LLM generates raw JSON → parse from markdown | Fragile; fails on any explanation text |
| No named variable tracking | Can't pass `customer_id` to both `order` AND `project` |
| No retry logic | Single 5xx = silent failure |
| Prompt has no exact API schemas | Claude hallucinates field names |
| String-replace only on endpoint/body | Misses params, headers, nested fields |

### New Architecture: Structured Execution Plan

```
POST /solve
  │
  ├─ 1. Extract task context
  │     Parse prompt + decode files → structured task description
  │
  ├─ 2. Claude generates execution plan (via tool_use)
  │     Returns typed steps with named variables and extract paths
  │
  ├─ 3. Execute plan with context tracking
  │     For each step:
  │       - Resolve all {{variable}} references
  │       - Execute API call
  │       - Extract named values from response
  │       - Store in context dict
  │       - Handle errors per policy
  │
  └─ 4. Return {"status": "completed"}
```

### Key Design: Named Variable Context

Claude produces a plan like this (via tool_use, guaranteed valid JSON):

```json
{
  "task_summary": "Create customer Acme AS, then create invoice",
  "steps": [
    {
      "step_id": "create_customer",
      "method": "POST",
      "endpoint": "/customer",
      "json_body": {
        "name": "Acme AS",
        "email": "acme@example.com",
        "isCustomer": true,
        "isPrivateIndividual": false
      },
      "extract": {
        "customer_id": "value.id"
      }
    },
    {
      "step_id": "create_order",
      "method": "POST",
      "endpoint": "/order",
      "json_body": {
        "customer": {"id": "{{customer_id}}"},
        "orderDate": "2026-03-20",
        "deliveryDate": "2026-04-20"
      },
      "extract": {
        "order_id": "value.id"
      }
    },
    {
      "step_id": "invoice_order",
      "method": "PUT",
      "endpoint": "/order/{{order_id}}/:invoiceOrder",
      "params": {
        "invoiceDate": "2026-03-20",
        "sendToCustomer": false
      },
      "extract": {
        "invoice_id": "value.id"
      }
    }
  ]
}
```

The executor resolves `{{customer_id}}` and `{{order_id}}` recursively across ALL fields (endpoint, params, json_body).

### Claude Tool Definition

```python
PLAN_TOOL = {
    "name": "execute_accounting_task",
    "description": "Plan and execute Tripletex API calls to complete the accounting task",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_summary": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step_id": {"type": "string"},
                        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
                        "endpoint": {"type": "string"},
                        "params": {"type": "object"},
                        "json_body": {"type": "object"},
                        "extract": {"type": "object", "description": "Map of variable_name -> jsonpath (e.g. value.id)"},
                        "skip_on_error": {"type": "boolean"}
                    },
                    "required": ["step_id", "method", "endpoint"]
                }
            }
        },
        "required": ["task_summary", "steps"]
    }
}
```

### Context Variable Resolution

```python
def resolve_vars(obj, context: dict):
    """Recursively substitute {{var}} in any data structure."""
    if isinstance(obj, str):
        for key, val in context.items():
            obj = obj.replace(f"{{{{{key}}}}}", str(val))
        return obj
    elif isinstance(obj, dict):
        return {k: resolve_vars(v, context) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [resolve_vars(item, context) for item in obj]
    return obj

def extract_vars(response_data: dict, extract_map: dict) -> dict:
    """Extract named values from API response using dot-path notation."""
    extracted = {}
    for var_name, path in extract_map.items():
        parts = path.split(".")
        value = response_data
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break
        if value is not None:
            extracted[var_name] = value
    return extracted
```

### Retry Logic

```python
def call_with_retry(base_url, token, method, endpoint, params=None, json_body=None, max_retries=3):
    for attempt in range(max_retries):
        result = call_tripletex(base_url, token, method, endpoint, params, json_body)
        status = result["status_code"]
        
        if status in (200, 201):
            return result
        elif status >= 500:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue
        elif status == 429:
            time.sleep(5)
            continue
        
        # 4xx: log it, don't retry (likely won't help, will tank efficiency)
        return result
    return result
```

---

## 3. System Prompt Engineering

The system prompt is the single biggest lever for correctness. It must include:

### A. Exact Field Schemas (prevents hallucination)

```
EMPLOYEE required fields:
- firstName (string, required)
- lastName (string, required) 
- email (string)
- employeeNumber (string, auto if omitted)
- roles: [{nameOfRole: "ROLE_ADMINISTRATOR|ROLE_ACCOUNT_ADMINISTRATOR|..."}]

CUSTOMER required fields:
- name (string, required)
- isCustomer: true (required)
- email (string)
- isPrivateIndividual: false (default for businesses)
- organizationNumber (string, optional)

PRODUCT required fields:
- name (string, required)
- number (string, auto if omitted)
- costExcludingVatCurrency (decimal)
- priceExcludingVatCurrency (decimal)
- vatType: {id: 3} (standard 25% VAT) or {id: 1} (no VAT)

DEPARTMENT required fields:
- name (string, required)
- departmentNumber (string, optional)

ORDER required fields:
- customer: {id: X} (required)
- orderDate: "YYYY-MM-DD" (required)

TRAVEL EXPENSE required fields:
- employee: {id: X} (required)
- travelDetails: {isForeignTravel: false}
- startDate: "YYYY-MM-DD"
- endDate: "YYYY-MM-DD"
```

### B. Invoice Creation Pattern (critical multi-step)

```
INVOICE CREATION FLOW (always use this exact pattern):
1. POST /order with customer ref and orderDate
2. POST /orderline with order ref, product/description, count, unitPriceExcludingVat
3. PUT /order/{order_id}/:invoiceOrder with params: invoiceDate, sendToCustomer=false
   → Returns the invoice with id in value.id

DO NOT use POST /invoice directly — use the order flow above.

PAYMENT REGISTRATION:
- POST /invoice/{invoice_id}/:createReminder is wrong
- Use: PUT /invoice/{invoice_id}/:payment with params: 
  paymentDate, paymentTypeId (usually 1 for bank), paidAmount
```

### C. Language Handling Note

```
The task prompt may be in: Norwegian (Bokmål), Nynorsk, English, Spanish, 
Portuguese, German, or French. Parse it natively — no translation needed.

Numbers: watch for European format (1.000,50 = 1000.50, comma is decimal separator)
Dates: convert all date formats to ISO 8601 (YYYY-MM-DD)
Names: preserve original Unicode (æ, ø, å, ä, ö, ü, é, ñ, etc.)
```

### D. Efficiency Rules (embed in system prompt)

```
EFFICIENCY RULES (critical for scoring):
1. NEVER do a GET to verify something you just created. Trust the 201 response.
2. NEVER do a GET to find something by name if you can use POST params to create it fresh.
3. Extract IDs from POST response bodies (value.id), don't re-fetch.
4. Don't fetch existing data unless the task explicitly says to modify/find existing records.
5. Each unnecessary API call reduces your efficiency score.
6. Each 4xx error reduces your efficiency score significantly.
7. Validate all required fields BEFORE making the call, not after.
```

---

## 4. Task-Specific Optimal Call Counts

### Tier 1 Tasks

| Task | Optimal Calls | Steps |
|------|---------------|-------|
| Create employee | 1 | POST /employee |
| Create customer | 1 | POST /customer |
| Create product | 1 | POST /product |
| Create department | 1 | POST /department |
| Create invoice | 3 | POST /order + POST /orderline + PUT /order/:invoiceOrder |

### Tier 2 Tasks

| Task | Optimal Calls | Steps |
|------|---------------|-------|
| Invoice + payment | 4 | POST /order + POST /orderline + PUT /order/:invoiceOrder + PUT /invoice/:payment |
| Credit note | 2 | GET /invoice (find existing) + PUT /invoice/:createCreditNote |
| Project billing | 4 | POST /project + POST /order (linked to project) + POST /orderline + PUT /order/:invoiceOrder |
| Travel expenses | 2 | POST /travelExpense + optionally POST /travelExpense/attachment |
| Order with lines | 3 | POST /customer + POST /order + POST /orderline (×N) |

### Tier 3 Tasks (Saturday)

| Task | Estimated Calls | Notes |
|------|-----------------|-------|
| Bank reconciliation from CSV | 5-10 | Parse CSV, POST vouchers/postings |
| Error correction in ledger | 4-6 | GET voucher + DELETE/reverse + POST corrected |
| Year-end closing | 8-15 | Multi-step accounting workflow |

---

## 5. Risk Mitigation Plan

### Risk 1: Claude Returns Invalid/Malformed JSON (HIGH → ELIMINATED)
**Solution**: Use `tool_use` (function calling). Claude MUST populate the tool schema. No markdown code blocks to parse. If tool_use fails, fallback to JSON extraction with strict cleaning.

```python
response = claude.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4096,
    tools=[PLAN_TOOL],
    tool_choice={"type": "tool", "name": "execute_accounting_task"},
    messages=messages,
)
plan = response.content[0].input  # Guaranteed dict, no parsing needed
```

### Risk 2: LLM Hallucinates Wrong Field Names (HIGH → MITIGATED)
**Solution**: Embed exact field schemas in system prompt. Include examples for every task type. Use `claude-sonnet-4-20250514` (best available). For Tier 3, consider `extended_thinking` for complex reasoning.

### Risk 3: Fragile ID Substitution (HIGH → FIXED)
**Solution**: Named variable context system (see Architecture section). Handles unlimited dependencies, all data types, nested structures.

### Risk 4: Module Dependencies (MEDIUM → HANDLE AT RUNTIME)
**Problem**: Travel expenses, department accounting, etc. may need modules enabled.
**Solution**: When Claude generates a step that would fail due to disabled module, include an enable-module step first. Add to system prompt: "If using travelExpense, first PUT /company/settings to enable the module."

Actually better: **Pre-enable common modules at task start** using a setup step that Claude can include if needed.

### Risk 5: Timeout (5 minutes) (MEDIUM → MANAGED)
**Solution**: 
- Set HTTP timeout: 10s per API call
- Max steps: 20 (if Claude plans more, something's wrong)
- Track elapsed time, abort gracefully at 4:30 minutes
- Claude's API call itself should complete in <30s (budget 4096 tokens)

```python
import time
start_time = time.time()
MAX_ELAPSED = 270  # 4.5 minutes

for step in steps:
    if time.time() - start_time > MAX_ELAPSED:
        break  # Return completed anyway
    execute_step(step)
```

### Risk 6: Multilingual Number/Date Parsing (MEDIUM → IN PROMPT)
**Solution**: Instruct Claude in system prompt to normalize:
- `1.500,00 NOK` → `1500.00`  
- `15 januar 2026` / `15. Januar 2026` / `january 15, 2026` → `2026-01-15`
- Amounts in different currencies: use as-is (Tripletex handles currency)

### Risk 7: Fresh Account State (MEDIUM → DESIGN AROUND)
**Critical**: Every competition submission gets a **brand new empty account**.
- Never rely on existing data (no customers, products, employees)
- Always create all dependencies explicitly
- Don't do GET to find entities — create them
- Exception: credit note/payment tasks will reference entity IDs in the prompt itself

### Risk 8: File Attachment Parsing (LOW-MEDIUM → STRUCTURED)
**Solution**: Use Claude vision for images, document API for PDFs. Extract structured data before planning:

```python
# If files present, do a pre-pass to extract data
if files:
    extraction_response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Extract all accounting data from this document as JSON: amounts, dates, names, descriptions, quantities."},
                *[build_file_content_block(f) for f in files]
            ]
        }]
    )
    extracted_data = extraction_response.content[0].text
    # Include in main planning prompt
```

### Risk 9: API Rate Limits (LOW → HANDLED)
429 response → sleep 5s → retry once. Competition sandbox shouldn't hit limits under normal use.

### Risk 10: cloudflared Tunnel Drops (LOW → RESILIENT)
**Solution**: Run cloudflared with `--no-autoupdate` and restart-on-exit. Use `nohup` or a simple shell loop:
```bash
while true; do cloudflared tunnel --url http://localhost:8000; sleep 5; done &
```

---

## 6. Complete Rewrite of `main.py`

### Full Implementation Plan

```python
"""
Tripletex AI Accounting Agent — NM i AI 2026
Rebuilt with structured execution plan architecture.
"""

import json, os, time, base64
from pathlib import Path
from typing import Any

import anthropic, requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

load_dotenv(Path(__file__).parent.parent / ".env")

app = FastAPI(title="Tripletex AI Agent")
claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# ─── Tool definition for structured output ────────────────────────────────────

PLAN_TOOL = {
    "name": "execute_accounting_task",
    "description": "Generate an ordered plan of Tripletex API calls to complete the task",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_summary": {"type": "string", "description": "Brief description of what task does"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step_id": {"type": "string", "description": "Unique name for this step"},
                        "description": {"type": "string"},
                        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
                        "endpoint": {"type": "string", "description": "API endpoint path, may use {{variable}} syntax"},
                        "params": {"type": "object", "description": "Query string params"},
                        "json_body": {"type": "object", "description": "Request body"},
                        "extract": {"type": "object", "description": "Map of var_name -> dot.path in response"},
                        "skip_on_error": {"type": "boolean", "default": False}
                    },
                    "required": ["step_id", "method", "endpoint"]
                }
            }
        },
        "required": ["task_summary", "steps"]
    }
}

# ─── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert AI accounting agent for Tripletex (Norwegian accounting software).
You receive task prompts in one of 7 languages and must generate the optimal sequence of Tripletex v2 API calls.

## API SCHEMAS (use these exact field names)

### POST /employee
Required: firstName, lastName
Optional: email, phoneNumberMobileCountry, phoneNumberMobile, employeeNumber
Roles: add {"nameOfRole": "ROLE_ADMINISTRATOR"} or "ROLE_ACCOUNT_ADMINISTRATOR" in roles array

### POST /customer  
Required: name, isCustomer (must be true)
Optional: email, organizationNumber, phoneNumber, isPrivateIndividual (false for businesses)

### POST /product
Required: name
Optional: number, costExcludingVatCurrency, priceExcludingVatCurrency, unit, vatType

### POST /department
Required: name
Optional: departmentNumber

### POST /order
Required: customer ({"id": X}), orderDate ("YYYY-MM-DD")
Optional: deliveryDate, orderComment, currency

### POST /orderline
Required: order ({"id": X}), count (quantity), unitPriceExcludingVatCurrency
Optional: product ({"id": X}), description, discount

### PUT /order/{order_id}/:invoiceOrder (creates invoice)
Params: invoiceDate (required), sendToCustomer (false), createBackOrder (false)

### POST /project
Required: name, projectManager ({"id": X}), startDate ("YYYY-MM-DD")
Optional: customer ({"id": X}), endDate, description

### POST /travelExpense
Required: employee ({"id": X}), startDate, endDate
Optional: destination, purpose, isCompleted

### PUT /invoice/{invoice_id}/:payment
Params: paymentDate ("YYYY-MM-DD"), paymentTypeId (1=bank transfer), paidAmount (decimal)

### PUT /invoice/{invoice_id}/:createCreditNote
Params: date (credit note date)

## EFFICIENCY RULES (critical for scoring)
1. NEVER GET to verify something you just created — trust the 201 response
2. Extract IDs from POST responses via extract: {"var_name": "value.id"}
3. Reference extracted IDs in subsequent steps as {{var_name}}
4. Zero unnecessary calls — every extra call and every 4xx reduces your score
5. Do NOT create entities that exist if the task says "existing" — use GET to find them first

## DATA NORMALIZATION  
- Amounts with European format: "1.500,00" = 1500.00 (comma=decimal, period=thousands)
- Dates in any format → ISO 8601 "YYYY-MM-DD"
- Preserve all Unicode characters (æ, ø, å, ä, ö, ü, etc.)
- Currency amounts: use as decimal numbers without currency symbol

## INVOICE CREATION (always use this flow)
1. POST /order → get order_id
2. POST /orderline (with order ref) → add line items
3. PUT /order/{{order_id}}/:invoiceOrder with invoiceDate param → creates and returns invoice

## FRESH ACCOUNT
Every submission starts with an EMPTY Tripletex account. Always create all dependencies.
Never assume any customers, products, employees already exist (unless the task mentions an ID).

Now generate the optimal execution plan for the given task."""

# ─── Core execution ────────────────────────────────────────────────────────────

def resolve_vars(obj: Any, context: dict) -> Any:
    """Recursively substitute {{var}} references in any data structure."""
    if isinstance(obj, str):
        for key, val in context.items():
            obj = obj.replace(f"{{{{{key}}}}}", str(val))
        return obj
    elif isinstance(obj, dict):
        return {k: resolve_vars(v, context) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [resolve_vars(item, context) for item in obj]
    return obj


def extract_vars(response_data: dict, extract_map: dict) -> dict:
    """Extract named values from response using dot-path notation."""
    extracted = {}
    for var_name, path in (extract_map or {}).items():
        value = response_data
        for part in path.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break
        if value is not None:
            extracted[var_name] = value
    return extracted


def call_tripletex(base_url: str, token: str, method: str, endpoint: str,
                   params=None, json_body=None, timeout=10) -> dict:
    auth = ("0", token)
    url = f"{base_url}{endpoint}"
    try:
        resp = getattr(requests, method.lower())(
            url, auth=auth, params=params, json=json_body, timeout=timeout
        )
        try:
            data = resp.json()
        except Exception:
            data = resp.text
        return {"status_code": resp.status_code, "data": data}
    except requests.Timeout:
        return {"status_code": 408, "data": {"error": "Request timed out"}}
    except Exception as e:
        return {"status_code": 500, "data": {"error": str(e)}}


def call_with_retry(base_url: str, token: str, method: str, endpoint: str,
                    params=None, json_body=None) -> dict:
    for attempt in range(3):
        result = call_tripletex(base_url, token, method, endpoint, params, json_body)
        status = result["status_code"]
        if status in (200, 201):
            return result
        if status >= 500 or status == 408:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
        if status == 429:
            time.sleep(5)
            continue
        return result  # 4xx: don't retry
    return result


@app.post("/solve")
async def solve(request: Request):
    start_time = time.time()
    body = await request.json()
    prompt = body["prompt"]
    files = body.get("files", [])
    creds = body["tripletex_credentials"]
    base_url = creds["base_url"]
    token = creds["session_token"]
    
    # Build user content (handle files)
    content_parts = []
    
    # Add files first (images and PDFs)
    for f in files:
        filename = f["filename"].lower()
        if filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            content_parts.append({
                "type": "image",
                "source": {"type": "base64",
                           "media_type": f"image/{filename.split('.')[-1]}",
                           "data": f["content_base64"]}
            })
        elif filename.endswith(".pdf"):
            content_parts.append({
                "type": "document",
                "source": {"type": "base64",
                           "media_type": "application/pdf",
                           "data": f["content_base64"]}
            })
    
    file_hint = f"\n\n{len(files)} file(s) attached above." if files else ""
    content_parts.append({"type": "text", "text": f"TASK:\n{prompt}{file_hint}"})
    
    # Call Claude with tool_use for guaranteed structured output
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[PLAN_TOOL],
        tool_choice={"type": "tool", "name": "execute_accounting_task"},
        messages=[{"role": "user", "content": content_parts}],
    )
    
    # Extract plan (tool_use guarantees valid structure)
    plan = response.content[0].input
    steps = plan.get("steps", [])
    
    # Execute plan with context tracking
    context = {}
    for step in steps:
        if time.time() - start_time > 270:  # 4.5 min safety cutoff
            break
        
        # Resolve variable references
        endpoint = resolve_vars(step["endpoint"], context)
        params = resolve_vars(step.get("params") or {}, context) or None
        json_body = resolve_vars(step.get("json_body") or {}, context) or None
        
        result = call_with_retry(base_url, token, step["method"], endpoint, params, json_body)
        
        # Extract variables for future steps
        if result["status_code"] in (200, 201) and isinstance(result["data"], dict):
            extracted = extract_vars(result["data"], step.get("extract", {}))
            context.update(extracted)
    
    return JSONResponse({"status": "completed"})


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## 7. Tier Progression Strategy

### Phase 1: Tier 1 Mastery (Target: 10.0 points)

**Tasks:** Create employee, customer, product, department, invoice  
**Target:** 2.0/2.0 each (perfect + efficiency)

| Task | Complexity | Key Fields to Get Right |
|------|-----------|------------------------|
| Create employee | 1 call | firstName, lastName, email, role assignment |
| Create customer | 1 call | name, isCustomer: true, email |
| Create product | 1 call | name, price fields |
| Create department | 1 call | name, departmentNumber |
| Create invoice | 3 calls | order flow, date fields, customer link |

**Test these against sandbox first.** Know exactly what fields the scorer checks.

### Phase 2: Tier 2 Mastery (Target: 20.0 points)

**Tasks:** Invoice+payment, credit notes, project billing, travel expenses, order with lines

Key challenges:
- **Invoice + payment**: Must use correct `paymentTypeId` (check via GET /ledger/paymentType)
- **Credit notes**: `PUT /invoice/{id}/:createCreditNote` — need existing invoice ID
- **Project billing**: Project needs a project manager (employee ID required)
- **Travel expenses**: May need module enabling, has complex sub-fields
- **Order with lines**: Multiple POST /orderline calls (one per line item)

### Phase 3: Tier 3 Preparation (Target: 120.0 points)

**Opens Saturday.** Design is crucial; don't improvise.

| Task | Expected Pattern |
|------|-----------------|
| Bank reconciliation from CSV | Parse CSV → identify transactions → POST /ledger/voucher with matchings |
| Error correction in ledger | GET voucher → identify error → DELETE wrong + POST corrected |
| Year-end closing | Multi-step: close periods, create year-end vouchers, post depreciation |

**Tier 3 specific architecture additions:**
- CSV parsing logic (Python `csv` module, handle Norwegian encoding)
- Ledger/voucher API deep understanding
- Extended thinking mode for Claude on complex tasks

---

## 8. Testing Approach

### Local Testing Protocol

```bash
# 1. Start server
cd /Users/ramil/.openclaw/workspace/NM-AI/tripletex
python main.py &

# 2. Start tunnel
cloudflared tunnel --url http://localhost:8000 &

# 3. Test against sandbox with real task prompts
curl -X POST http://localhost:8000/solve \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Opprett en ny ansatt: Ola Nordmann, ola@example.no. Sett ham som kontoadministrator.",
    "files": [],
    "tripletex_credentials": {
      "base_url": "https://kkpqfuj-amager.tripletex.dev/v2",
      "session_token": "YOUR_TOKEN"
    }
  }'
```

### Test Coverage Matrix

For each task type, test:
1. Norwegian prompt (primary)
2. English prompt  
3. At least one other language (Spanish or German)
4. Edge cases: special characters in names, large amounts, zero amounts

### Sandbox Verification

After each test, verify in the Tripletex UI OR via API:
```bash
curl -u "0:TOKEN" "https://kkpqfuj-amager.tripletex.dev/v2/employee?fields=*"
curl -u "0:TOKEN" "https://kkpqfuj-amager.tripletex.dev/v2/customer?fields=*"
```

### Pre-submission Checklist

- [ ] Server starts without errors
- [ ] `/health` returns 200
- [ ] `/solve` returns `{"status": "completed"}` within 10s for simple tasks
- [ ] All Tier 1 tasks verified against sandbox
- [ ] All Tier 2 tasks verified against sandbox
- [ ] cloudflared tunnel is running and accessible
- [ ] Environment variables loaded correctly
- [ ] No hardcoded credentials

---

## 9. Deployment Steps

### Prerequisites

```bash
# Install cloudflared
brew install cloudflared

# Install Python dependencies
cd /Users/ramil/.openclaw/workspace/NM-AI/tripletex
pip install -r requirements.txt

# Verify env
cat /Users/ramil/.openclaw/workspace/NM-AI/.env
# Should contain ANTHROPIC_API_KEY=sk-ant-...
```

### Production Run

```bash
# Terminal 1: Server
cd /Users/ramil/.openclaw/workspace/NM-AI/tripletex
python main.py

# Terminal 2: Tunnel (keep alive)
while true; do
  cloudflared tunnel --url http://localhost:8000 2>&1
  echo "Tunnel died, restarting in 5s..."
  sleep 5
done
```

### Or use a single startup script

```bash
#!/bin/bash
# start.sh
cd /Users/ramil/.openclaw/workspace/NM-AI/tripletex

# Start server in background
python main.py &
SERVER_PID=$!

# Wait for server to be ready
sleep 2

# Start tunnel (keep alive)
while true; do
  cloudflared tunnel --url http://localhost:8000 2>&1 | tee /tmp/tunnel.log
  echo "Tunnel died, restarting..."
  sleep 3
done
```

### Submission

1. Copy the cloudflared HTTPS URL (e.g. `https://abc123.trycloudflare.com`)
2. Go to https://app.ainm.no/submit/tripletex
3. Submit the URL
4. Watch the leaderboard

---

## 10. Open Questions & Next Actions

### Immediate Actions (do now)

1. **Install cloudflared**: `brew install cloudflared`
2. **Rewrite main.py** with the new architecture (see Section 6)
3. **Test all Tier 1 tasks** against the sandbox manually
4. **Verify exact field names** the scorer checks by testing and inspecting results on app.ainm.no

### Unknown Risks to Investigate

- [ ] What exact fields does each task scorer check? (submit and look at partial scores)
- [ ] Does `PUT /order/:invoiceOrder` require existing order lines?
- [ ] What `paymentTypeId` values are available on fresh accounts?
- [ ] Which modules are pre-enabled on fresh accounts?
- [ ] Are there VAT requirements for invoices? (vatType field)
- [ ] Does project billing require specific project type/activity?

### Saturday Preparation (Tier 3)

- Research `ledger/voucher` API thoroughly before Saturday
- Understand bank reconciliation workflow in Tripletex UI
- Add CSV parsing capability to agent
- Consider using `extended_thinking` for Tier 3 complexity

---

## 11. Architecture Decision Record

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM output format | `tool_use` (function calling) | Guarantees valid JSON, no markdown parsing |
| ID tracking | Named variable context + `{{var}}` substitution | Handles unlimited dependencies, recursive, type-safe |
| Retry strategy | 3× for 5xx, 1× for 429, no retry for 4xx | 4xx retries tank efficiency score |
| Invoice creation | Order flow (not POST /invoice) | Tripletex's correct flow; POST /invoice may not work |
| Module enabling | On-demand in plan | Don't waste calls pre-enabling unused modules |
| File handling | Pre-pass Claude vision → extracted JSON | Clean separation from planning step |
| Timeout | 270s cutoff, 10s per HTTP call | 30s buffer, prevents submission timeout |
| Correctness vs efficiency | Correctness first | Efficiency bonus only triggers at 100% correctness |
| Model | claude-sonnet-4-20250514 | Best available, strong multilingual + tool use |

---

*Plan authored by Lead Strategist — Team RAMil, NM i AI 2026*  
*Last updated: 2026-03-20*
