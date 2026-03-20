"""
Tripletex AI Accounting Agent — NM i AI 2026
Team EasyEiendom

Agentic tool-use loop with Claude Opus.
"""

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

# ─── Config ────────────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("agent.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Tripletex AI Agent")
claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

MODEL = "claude-opus-4-0-20250514"
MAX_ITERATIONS = 15
TIMEOUT_SECONDS = 250  # hard cutoff (300s server timeout, 50s buffer)
CALL_BUDGET_SOFT = 12
MAX_ERRORS_BEFORE_CONSERVATIVE = 2

# ─── System Prompt ─────────────────────────────────────────────────────────────
# ⚠️  UPDATE AFTER API DISCOVERY FRIDAY EVENING

SYSTEM_PROMPT = """You are a Tripletex accounting API agent. You receive a task prompt (in any of 7 languages)
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

- 422: Read the error message carefully. It tells you EXACTLY what's wrong. Fix that ONE thing, retry ONCE.
- 404: Wrong endpoint path or nonexistent ID.
- 400: Bad request body. Check field types and required fields.
- After 2 total errors: ONLY make calls you are absolutely certain about.
"""

# ─── Tool Definitions ──────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "tripletex_api",
        "description": "Call the Tripletex v2 REST API. Use for all API operations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE"],
                    "description": "HTTP method",
                },
                "endpoint": {
                    "type": "string",
                    "description": "API path, e.g. /employee, /customer/123, /order/5/:invoiceOrder",
                },
                "params": {
                    "type": "object",
                    "description": "Query parameters (for filtering, fields, pagination, action params)",
                },
                "json_body": {
                    "type": "object",
                    "description": "JSON request body (for POST/PUT)",
                },
            },
            "required": ["method", "endpoint"],
        },
    },
    {
        "name": "task_complete",
        "description": "Signal that the accounting task is fully done. Call ONLY when all required operations are finished.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One-line summary of what was accomplished",
                },
            },
            "required": ["summary"],
        },
    },
]

# ─── Advisory Validation ───────────────────────────────────────────────────────
# These are HINTS, not hard blocks. If wrong, Claude can override.

KNOWN_REQUIRED_FIELDS = {
    "/employee": ["firstName", "lastName"],
    "/customer": ["name"],
    "/product": ["name"],
    "/order": ["customer", "orderDate"],
    "/orderline": ["order", "count"],
    "/department": ["name"],
    "/project": ["name", "projectManager"],
}


def advisory_check(endpoint: str, body: dict | None) -> str | None:
    """Return advisory warning if required fields seem missing. Not blocking."""
    base = "/" + endpoint.strip("/").split("/")[0]
    required = KNOWN_REQUIRED_FIELDS.get(base, [])
    if not required or not body:
        return None
    missing = [f for f in required if f not in body]
    if missing:
        return f"⚠️ Advisory: {base} typically requires {missing}. Proceeding anyway — fix if you get a 422."
    return None


# ─── API Caller ────────────────────────────────────────────────────────────────


def call_tripletex(
    base_url: str,
    token: str,
    method: str,
    endpoint: str,
    params: dict | None = None,
    json_body: dict | None = None,
) -> dict:
    """Execute a single Tripletex API call. Returns {status_code, data}."""
    url = f"{base_url}{endpoint}"
    auth = ("0", token)
    kwargs = {"auth": auth, "timeout": 15}
    if params:
        kwargs["params"] = params
    if json_body and method.upper() in ("POST", "PUT"):
        kwargs["json"] = json_body

    try:
        resp = getattr(requests, method.lower())(url, **kwargs)
    except requests.Timeout:
        return {"status_code": 408, "data": {"error": "Request timed out (15s)"}}
    except Exception as e:
        return {"status_code": 0, "data": {"error": str(e)}}

    try:
        data = resp.json()
    except Exception:
        data = resp.text[:2000] if resp.text else ""

    return {"status_code": resp.status_code, "data": data}


# ─── File Content Blocks ──────────────────────────────────────────────────────


def build_user_content(prompt: str, files: list[dict]) -> list:
    """Build Claude message content blocks including files."""
    parts = []

    for f in files:
        fname = f.get("filename", "").lower()
        b64 = f.get("content_base64", "")
        mime = f.get("mime_type", "")

        if mime.startswith("image/") or fname.endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp")
        ):
            media_type = mime or f"image/{fname.rsplit('.', 1)[-1]}"
            if "jpg" in media_type:
                media_type = media_type.replace("jpg", "jpeg")
            parts.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    },
                }
            )
        elif mime == "application/pdf" or fname.endswith(".pdf"):
            parts.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": b64,
                    },
                }
            )
        # else: skip unknown file types

    file_note = f"\n\n({len(files)} file(s) attached above — examine fully before acting)" if files else ""
    parts.append({"type": "text", "text": f"TASK:\n{prompt}{file_note}"})

    return parts


# ─── Main Solve Endpoint ──────────────────────────────────────────────────────


@app.post("/solve")
async def solve(request: Request):
    try:
        return await _solve_inner(request)
    except Exception as e:
        logger.exception(f"Fatal error in /solve: {e}")
        # NEVER crash. Always return completed.
        return JSONResponse({"status": "completed"})


async def _solve_inner(request: Request):
    body = await request.json()
    prompt = body["prompt"]
    files = body.get("files", [])
    creds = body["tripletex_credentials"]
    base_url = creds["base_url"]
    token = creds["session_token"]

    logger.info(f"{'='*60}")
    logger.info(f"NEW TASK | Prompt: {prompt[:150]}...")
    logger.info(f"Files: {len(files)} | Base URL: {base_url}")

    messages = [{"role": "user", "content": build_user_content(prompt, files)}]

    start_time = time.time()
    call_count = 0
    error_count = 0
    task_completed = False

    for iteration in range(MAX_ITERATIONS):
        elapsed = time.time() - start_time
        if elapsed > TIMEOUT_SECONDS:
            logger.warning(f"Timeout at {elapsed:.0f}s after {iteration} iterations")
            break

        # ── Call Claude ──────────────────────────────────────────────
        try:
            with claude.messages.stream(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=TOOLS,
            ) as stream:
                response = stream.get_final_message()
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            break

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # ── Extract tool uses ────────────────────────────────────────
        tool_uses = [b for b in assistant_content if b.type == "tool_use"]

        if not tool_uses:
            # Text-only response = Claude thinks it's done
            text_parts = [b.text for b in assistant_content if hasattr(b, "text")]
            logger.info(f"Iteration {iteration}: text only (done) — {' '.join(text_parts)[:100]}")
            break

        # ── Process each tool call ───────────────────────────────────
        tool_results = []
        should_break = False

        for tool_use in tool_uses:
            if tool_use.name == "task_complete":
                summary = tool_use.input.get("summary", "no summary")
                logger.info(f"Task complete: {summary}")
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": "Task marked as complete.",
                    }
                )
                task_completed = True
                should_break = True

            elif tool_use.name == "tripletex_api":
                inp = tool_use.input
                method = inp.get("method", "GET")
                endpoint = inp.get("endpoint", "")
                params = inp.get("params")
                json_body = inp.get("json_body")

                logger.info(
                    f"Iteration {iteration}: {method} {endpoint}"
                    + (f" body_keys={list(json_body.keys())}" if json_body else "")
                )

                # Advisory pre-flight (warn but don't block)
                advisory = None
                if method.upper() in ("POST", "PUT") and "/:invoiceOrder" not in endpoint:
                    advisory = advisory_check(endpoint, json_body)

                # Execute the API call
                result = call_tripletex(
                    base_url, token, method, endpoint, params, json_body
                )
                call_count += 1

                is_error = 400 <= result["status_code"] < 500
                if is_error:
                    error_count += 1
                    logger.warning(
                        f"4xx error #{error_count}: {result['status_code']} on {method} {endpoint}"
                    )

                # Build result message with budget + advisory
                elapsed_now = time.time() - start_time
                budget_line = (
                    f"[BUDGET: {call_count}/{CALL_BUDGET_SOFT} calls | "
                    f"{error_count} errors | {elapsed_now:.0f}s/{TIMEOUT_SECONDS}s]"
                )

                extras = ""
                if advisory:
                    extras += f"\n{advisory}"
                if error_count >= MAX_ERRORS_BEFORE_CONSERVATIVE:
                    extras += (
                        f"\n⚠️ CONSERVATIVE MODE: {error_count} errors so far. "
                        "Only make calls you are CERTAIN about. Partial completion > more errors."
                    )
                if call_count > CALL_BUDGET_SOFT:
                    extras += (
                        "\n⚠️ BUDGET WARNING: Exceeded soft call budget. Wrap up immediately."
                    )

                # Truncate large responses to save context
                data_str = json.dumps(
                    result["data"], indent=2, ensure_ascii=False
                )
                if len(data_str) > 4000:
                    data_str = data_str[:4000] + "\n... (truncated)"

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": f"{budget_line}{extras}\n\nHTTP {result['status_code']}:\n{data_str}",
                    }
                )
            else:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": f"Unknown tool: {tool_use.name}",
                        "is_error": True,
                    }
                )

        # Append tool results for next iteration
        messages.append({"role": "user", "content": tool_results})

        if should_break:
            break

    # ── Done ─────────────────────────────────────────────────────────
    elapsed_total = time.time() - start_time
    logger.info(
        f"DONE | calls={call_count} errors={error_count} "
        f"elapsed={elapsed_total:.1f}s completed_signal={task_completed}"
    )
    logger.info(f"{'='*60}")

    return JSONResponse({"status": "completed"})


# ─── Health Check ──────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL}


# ─── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
