# FINAL PLAN — Team EasyEiendom · NM i AI 2026

**Status:** SHIP THIS  
**Date:** 2026-03-20  
**Synthesized from:** Mactias plan, Ramil plan, Decision A verdicts, Decision B challenges

---

## 1. Decision Log

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | **Model: Opus or Sonnet?** | **Opus** | Correctness dominates scoring. A perfect Tier 2 = 2.0+; 80% correct = 1.6 with no efficiency bonus. Opus's edge on accounting semantics (VAT, roles, Nynorsk) is worth the latency. Timeout math works: 10 turns × 20s = 200s < 300s limit. |
| 2 | **Architecture?** | **Agentic tool-use loop** | Single-shot breaks on Tier 3 (discovery tasks). The loop lets Claude see API responses, recover from errors, adapt. B's escalation ladder is theoretically better but too complex to build reliably in one evening. B agrees: "If we only have time for one architecture, build the agentic loop." |
| 3 | **Concurrency?** | **Use all 3 concurrent slots** | B is right. Spec says tasks weighted toward less-attempted — 3 concurrent submissions will likely get 3 different task types. 3× throughput for free. A's fear of duplicates is unfounded given the weighting. |
| 4 | **Error handling?** | **Claude sees errors in the loop + conservative mode at 2 errors** | Mactias's approach. Ramil's "don't retry 4xx" is fatal — a fixable 422 becomes a 0.0. But we cap at 1 retry per failed call to avoid spiraling. |
| 5 | **System prompt?** | **Merged: Mactias's behavioral rules + Ramil's API schemas. UPDATE AFTER API DISCOVERY.** | The prompt below is a draft. Friday evening API discovery replaces guessed schemas with verified ones. |
| 6 | **Pre-flight validation?** | **Advisory, not blocking** | B is right. If our REQUIRED_FIELDS dict is wrong, we'd block correct calls. Return validation warnings to Claude as context; let it decide. |
| 7 | **File handling?** | **Inline (files as content blocks)** | Skip Ramil's separate extraction call. One less LLM round-trip. Claude handles files natively in the agentic loop. |
| 8 | **Streaming?** | **Yes** | Saves 1-3s per turn. Over 10 turns = meaningful. |
| 9 | **"Verify after POST"?** | **Never** | Both plans agree. Never GET to verify a POST — trust the response. The spec tip is an efficiency trap. |
| 10 | **Invoice flow?** | **Order flow (POST /order → POST /orderline → PUT /order/:invoiceOrder)** | Ramil's insight. This is Tripletex's actual flow. VERIFY AGAINST SANDBOX. If it fails, fall back to POST /invoice. |
| 11 | **Logging?** | **Full structured logging** | Non-negotiable for debugging platform submissions. |

---

## 2. Architecture

### Core Loop

```
POST /solve
  ├─ Parse request (prompt, files, credentials)
  ├─ Build system prompt + user message (files as content blocks)
  ├─ Send to Claude Opus with tool definitions
  └─ LOOP (max 15 iterations):
       ├─ Claude returns tool_use or text
       ├─ If tool_use "tripletex_api":
       │    ├─ Advisory pre-flight check (warn Claude, don't block)
       │    ├─ Execute API call
       │    ├─ Track call_count, error_count
       │    ├─ Feed result + budget status back to Claude
       │    └─ If error_count >= 2: inject conservative mode
       ├─ If tool_use "task_complete": break
       ├─ If text only (no tool_use): assume done, break
       ├─ If elapsed > 250s: force break
       └─ If call_count > 12: inject budget warning (don't hard-kill)
  Return {"status": "completed"}
```

### Tools

Two tools only. Keep it simple:

1. **`tripletex_api`** — method, endpoint, params, json_body
2. **`task_complete`** — signal done with summary

### Budget Injection

After each API result, prepend:
```
[BUDGET: {calls}/{budget} calls | {errors} errors | {elapsed}s/{timeout}s]
```

### Conservative Mode (at 2+ errors)

```
⚠️ CONSERVATIVE MODE: {error_count} errors. Only make calls you are CERTAIN about.
Partial completion beats more errors.
```

### Graceful Degradation

- Never crash. Wrap everything in try/except.
- Always return `{"status": "completed"}` — even on internal errors.
- Log everything for post-mortem.

---

## 3. System Prompt

**⚠️ THIS IS A DRAFT. Update after Friday evening API discovery.**

```
You are a Tripletex accounting API agent. You receive a task prompt (in any of 7 languages)
and execute the minimum necessary API calls to complete it correctly.

SCORING: correctness × tier_multiplier × (1 + efficiency_bonus).
Efficiency bonus ONLY applies at 100% correctness. Every 4xx error and unnecessary call
reduces it. A perfect task with minimal calls scores up to 6.0. A failed task scores 0.0.

═══════════════════════════════════════════════════════════════
CRITICAL RULES
═══════════════════════════════════════════════════════════════

1. NEVER GET after POST — the POST response contains the created entity with its ID.
2. NEVER search for an entity you just created.
3. The sandbox starts EMPTY. Don't search for pre-existing data unless the task says
   to modify/delete existing records.
4. Copy field values EXACTLY as they appear in the prompt. Do NOT normalize, capitalize,
   trim, or translate names, emails, or addresses. Character-for-character.
5. Plan your full sequence BEFORE making calls, but ADAPT based on actual responses.
6. Use ?fields=id,name,... to limit response size. Only use ?fields=* when exploring.
7. MAXIMUM 1 retry per failed call. If it fails twice, move on.

═══════════════════════════════════════════════════════════════
DATE HANDLING
═══════════════════════════════════════════════════════════════

- European prompts: DD.MM.YYYY → convert to YYYY-MM-DD
  Example: 03.04.2026 → 2026-04-03 (April 3rd, NOT March 4th)
- German: "15. März 2026" → 2026-03-15
- French: "15 mars 2026" → 2026-03-15
- If no date specified, use today's date.
- invoiceDueDate: 14 days after invoiceDate unless specified.

═══════════════════════════════════════════════════════════════
NUMBER HANDLING
═══════════════════════════════════════════════════════════════

- European format: 1.500,00 = 1500.00 (period=thousands, comma=decimal)
- Always send as plain decimal to API: 1500.00

═══════════════════════════════════════════════════════════════
LANGUAGE HANDLING
═══════════════════════════════════════════════════════════════

Prompts come in: Norwegian (Bokmål), Nynorsk, English, Spanish, Portuguese, German, French.
- Parse natively. No translation needed.
- Field NAMES are always English (firstName, not vorname).
- Field VALUES come from the prompt — preserve exactly.
- Preserve Unicode: æ, ø, å, ä, ö, ü, é, ñ, etc.

═══════════════════════════════════════════════════════════════
FILE HANDLING
═══════════════════════════════════════════════════════════════

If files are attached, examine them COMPLETELY before making ANY API calls.
Extract ALL relevant data: names, amounts, dates, line items, totals.

═══════════════════════════════════════════════════════════════
API REFERENCE
═══════════════════════════════════════════════════════════════

### Employees
POST /employee — Required: firstName, lastName. Optional: email, phoneNumberMobile, dateOfBirth
  Roles: include in body as roles: [{"nameOfRole": "ROLE_ADMINISTRATOR"}]
  Possible roles: ROLE_ADMINISTRATOR, ROLE_ACCOUNT_ADMINISTRATOR
PUT /employee/{id} — Update fields
GET /employee — Search: firstName, lastName, email params

### Customers
POST /customer — Required: name, isCustomer (MUST be true)
  Optional: email, phoneNumber, postalAddress, isPrivateIndividual (false for businesses)
PUT /customer/{id} — Update
GET /customer — Search by name, email

### Products
POST /product — Required: name
  Optional: number, priceExcludingVatCurrency, costExcludingVatCurrency, vatType (object with id)
GET /product — Search by name, number
NOTE: GET /ledger/vatType to find correct VAT type IDs. Do NOT guess IDs.

### Orders
POST /order — Required: customer ({"id": X}), orderDate ("YYYY-MM-DD")
  Optional: deliveryDate, currency

### Order Lines
POST /orderline — Required: order ({"id": X}), product ({"id": X}) OR description, count
  Optional: unitPriceExcludingVatCurrency, discount, vatType

### Invoices (via Order Flow)
PUT /order/{order_id}/:invoiceOrder — Creates invoice from order
  Params: invoiceDate (required), sendToCustomer (false)
  Returns the invoice in the response.
  
  FULL FLOW: POST /order → POST /orderline → PUT /order/{id}/:invoiceOrder

Alternative: POST /invoice with invoiceDate, invoiceDueDate, orders: [{"id": X}]
  (Use this if the order flow fails)

### Payments
PUT /invoice/{id}/:payment — Register payment
  Params: paymentDate, paymentTypeId (check /ledger/paymentType), paidAmount

### Credit Notes
PUT /invoice/{id}/:createCreditNote — Create credit note for invoice
  Params: date

### Projects
POST /project — Required: name, projectManager ({"id": X} — must be employee)
  Optional: customer ({"id": X}), description, startDate, endDate

### Departments
POST /department — Required: name, departmentNumber
  NOTE: May need module activation. If 422 error mentions modules, try:
  PUT /company/settings or check /modules endpoint.

### Travel Expenses
POST /travelExpense — Required: employee ({"id": X}), startDate, endDate
  Optional: destination, purpose, isCompleted
GET /travelExpense — Search
DELETE /travelExpense/{id} — Delete

### Ledger
GET /ledger/vatType — List VAT types (USE THIS, don't guess IDs)
GET /ledger/account — Chart of accounts
GET /ledger/posting — Query postings
POST /ledger/voucher — Create vouchers
DELETE /ledger/voucher/{id} — Delete vouchers
GET /ledger/paymentType — Available payment types

═══════════════════════════════════════════════════════════════
ENTITY DEPENDENCY CHAIN
═══════════════════════════════════════════════════════════════

Invoice requires → Order → Customer
Order Line requires → Order + Product
Payment requires → Invoice
Project requires → Employee (as manager), optionally Customer
Credit Note requires → existing Invoice
Travel Expense requires → Employee
Department may require → Module activation

═══════════════════════════════════════════════════════════════
RESPONSE FORMAT
═══════════════════════════════════════════════════════════════

POST/PUT single entity: {"value": {"id": 123, "firstName": "Ola", ...}}
GET list: {"fullResultSize": N, "values": [...]}

Always use "id" from creation responses in subsequent calls.

═══════════════════════════════════════════════════════════════
ERROR RECOVERY
═══════════════════════════════════════════════════════════════

- 422: Read the error message. It tells you EXACTLY what's wrong. Fix ONE thing, retry ONCE.
- 404: Wrong endpoint path or nonexistent ID. Check your path.
- 400: Bad request body. Check field types and required fields.
- After 2 total errors: ONLY make calls you are absolutely certain about.
```

---

## 4. Deployment

### Primary: Local + cloudflared

```bash
# Terminal 1: Server
cd /Users/mactias/Documents/NM-AI/tripletex
python main.py

# Terminal 2: Tunnel (restart loop)
while true; do
    cloudflared tunnel --url http://localhost:8000 2>&1 | tee tunnel.log
    echo "Tunnel died, restarting in 5s..."
    sleep 5
done
```

### Machine Hardening
- Wired ethernet (not WiFi)
- Disable sleep: `sudo pmset -a disablesleep 1`
- Run in tmux: server | tunnel | log tail
- Disable auto-updates for the weekend

### Backup: Dockerfile ready
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```
Deploy to Railway/Fly.io in <5min if local fails.

### Concurrent Submissions
- Submit 3 at a time (verified team limit)
- Use the platform's built-in submission mechanism
- Monitor dashboard for scores after each batch

---

## 5. Prioritized TODO

### 🔴 FRIDAY EVENING (before competition)

1. **API Discovery (2h)** — Hit every endpoint against sandbox. Record:
   - Exact required fields and response formats
   - VAT type IDs (`GET /ledger/vatType`)
   - Payment type IDs (`GET /ledger/paymentType`)
   - Invoice creation: test order flow AND POST /invoice — which works?
   - Credit note creation: exact endpoint and body
   - Department: does it need module activation?
   - Travel expense: required fields
   
2. **Update system prompt** with discovered data (30min)

3. **Deploy main.py** — server + tunnel running (30min)

4. **Smoke test** — send 3 test prompts against sandbox (15min)

### 🟡 SATURDAY MORNING

5. **Submit first batch** — 3 concurrent, check scores
6. **Track results** — log task_type → score → calls → errors
7. **Fix failures** — update system prompt based on actual failures
8. **Continuous submission** — every few minutes, 3 at a time

### 🟢 SATURDAY AFTERNOON + SUNDAY

9. **Tier 3 prep** (when it opens) — explore ledger/voucher APIs
10. **Efficiency pass** — for tasks scoring 1.0 correctness but low efficiency
11. **Edge cases** — multilingual prompts, file attachments, unusual formats

---

## 6. Feedback Loop (B's critical insight)

After every submission result:
1. Log: task_type, score, checks_passed, checks_failed, api_calls, errors
2. If score < 1.0: analyze which fields failed → update system prompt
3. If score = 1.0 but low efficiency: identify unnecessary calls → optimize
4. Maintain tracking in `results.jsonl`:

```json
{"task": "create_employee", "score": 2.0, "calls": 1, "errors": 0, "timestamp": "..."}
{"task": "create_invoice", "score": 1.8, "calls": 6, "errors": 1, "timestamp": "..."}
```

This feedback loop is how we improve. The platform IS our test suite.

---

## 7. What We're NOT Doing

- ❌ Escalation ladder / template system (too complex for Friday evening)
- ❌ Sonnet fallback (Opus timeout math works; best-score-per-task means timeouts cost nothing)
- ❌ Separate file extraction LLM call (inline in agentic loop)
- ❌ Dynamic model selection (premature optimization)
- ❌ Hard-blocking pre-flight validation (advisory only)
- ❌ Concurrent API calls within a task (sequential is safer)

---

*This is what we ship. Read it, deploy it, submit it, iterate.*
