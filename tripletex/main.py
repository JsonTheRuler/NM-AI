"""
Tripletex AI Accounting Agent — NM i AI 2026
FastAPI endpoint that receives accounting tasks, interprets them with Claude,
and executes the appropriate Tripletex API calls.
"""

import base64
import json
import os
from pathlib import Path

import anthropic
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

load_dotenv(Path(__file__).parent.parent / ".env")

app = FastAPI(title="Tripletex AI Agent")
claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Tripletex API helper
TRIPLETEX_API_DOCS = """
You are an AI accounting agent for Tripletex. You receive a task prompt (possibly in Norwegian,
English, Spanish, Portuguese, Nynorsk, German, or French) and must execute the correct
Tripletex API calls to complete it.

Available Tripletex v2 API endpoints:
- GET/POST /employee - Manage employees
- GET/POST /customer - Manage customers
- GET/POST /product - Manage products
- GET/POST /invoice - Create/manage invoices
- GET/POST /order - Manage orders
- GET/POST /orderline - Manage order lines
- GET/POST /project - Manage projects
- GET/POST /department - Manage departments
- GET/POST /travelExpense - Manage travel expenses
- GET/POST /payment - Register payments
- GET/POST /voucher - Manage vouchers
- GET/POST /account - Chart of accounts
- PUT /invoice/{id}/:createCreditNote - Credit notes
- And many more...

Authentication: Basic Auth with username "0" and the session token as password.

IMPORTANT RULES:
1. Minimize the number of API calls — efficiency is scored.
2. Avoid 4xx errors — error cleanliness is scored.
3. Parse the prompt carefully to extract ALL required field values.
4. Some tasks require creating prerequisites first (e.g., customer before invoice).
5. After creating entities, verify they exist with correct values if unsure.
6. Return the exact API calls you want to make as a structured plan.
"""


def call_tripletex(base_url: str, token: str, method: str, endpoint: str,
                   params: dict | None = None, json_body: dict | None = None) -> dict:
    """Make an authenticated Tripletex API call."""
    auth = ("0", token)
    url = f"{base_url}{endpoint}"

    if method.upper() == "GET":
        resp = requests.get(url, auth=auth, params=params)
    elif method.upper() == "POST":
        resp = requests.post(url, auth=auth, json=json_body, params=params)
    elif method.upper() == "PUT":
        resp = requests.put(url, auth=auth, json=json_body, params=params)
    elif method.upper() == "DELETE":
        resp = requests.delete(url, auth=auth, params=params)
    else:
        return {"error": f"Unknown method: {method}"}

    try:
        return {"status_code": resp.status_code, "data": resp.json()}
    except Exception:
        return {"status_code": resp.status_code, "data": resp.text}


def decode_files(files: list[dict]) -> list[dict]:
    """Decode base64-encoded file attachments."""
    decoded = []
    for f in files:
        data = base64.b64decode(f["content_base64"])
        filename = f["filename"]
        path = Path("/tmp") / filename
        path.write_bytes(data)
        decoded.append({"filename": filename, "path": str(path), "size": len(data)})
    return decoded


def build_prompt(task_prompt: str, files: list[dict], base_url: str) -> str:
    """Build the Claude prompt with task details and API context."""
    file_info = ""
    if files:
        file_info = "\n\nAttached files:\n"
        for f in files:
            file_info += f"- {f['filename']} ({f['size']} bytes)\n"

    return f"""{TRIPLETEX_API_DOCS}

BASE_URL: {base_url}

TASK PROMPT:
{task_prompt}
{file_info}

Analyze the task and return a JSON array of API calls to execute, in order.
Each call should have: {{"method": "GET|POST|PUT|DELETE", "endpoint": "/path", "params": {{}}, "json_body": {{}}}}

Think step by step:
1. What is the task asking?
2. What entities need to be created/modified?
3. What is the optimal sequence of API calls?
4. What are the required fields for each call?

Return ONLY a JSON array of API calls. No explanation."""


@app.post("/solve")
async def solve(request: Request):
    """Main endpoint — receives a task and executes it."""
    body = await request.json()
    prompt = body["prompt"]
    files = body.get("files", [])
    creds = body["tripletex_credentials"]
    base_url = creds["base_url"]
    token = creds["session_token"]

    # Decode any file attachments
    decoded_files = decode_files(files) if files else []

    # Build messages for Claude
    messages = [{"role": "user", "content": build_prompt(prompt, decoded_files, base_url)}]

    # If there are image/PDF files, add them as vision content
    if files:
        content_parts = [{"type": "text", "text": build_prompt(prompt, decoded_files, base_url)}]
        for f in files:
            if f["filename"].lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                content_parts.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": f"image/{f['filename'].split('.')[-1].lower()}",
                        "data": f["content_base64"],
                    }
                })
            elif f["filename"].lower().endswith(".pdf"):
                content_parts.append({
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": f["content_base64"],
                    }
                })
        messages = [{"role": "user", "content": content_parts}]

    # Ask Claude to plan the API calls
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=messages,
    )

    # Parse the planned API calls
    try:
        plan_text = response.content[0].text.strip()
        # Extract JSON from response (may be wrapped in markdown code blocks)
        if "```" in plan_text:
            plan_text = plan_text.split("```")[1]
            if plan_text.startswith("json"):
                plan_text = plan_text[4:]
        api_calls = json.loads(plan_text)
    except (json.JSONDecodeError, IndexError) as e:
        return JSONResponse({"status": "error", "detail": f"Failed to parse LLM plan: {e}"})

    # Execute the API calls in sequence
    results = []
    for call in api_calls:
        result = call_tripletex(
            base_url=base_url,
            token=token,
            method=call.get("method", "GET"),
            endpoint=call.get("endpoint", ""),
            params=call.get("params"),
            json_body=call.get("json_body"),
        )
        results.append(result)

        # If a POST created a resource, extract the ID for subsequent calls
        if result["status_code"] in (200, 201) and isinstance(result["data"], dict):
            created_id = result["data"].get("value", {}).get("id")
            if created_id:
                # Make the ID available for subsequent calls by doing string replacement
                for future_call in api_calls[api_calls.index(call) + 1:]:
                    endpoint = future_call.get("endpoint", "")
                    if "{id}" in endpoint or "{CREATED_ID}" in endpoint:
                        future_call["endpoint"] = endpoint.replace("{id}", str(created_id)).replace("{CREATED_ID}", str(created_id))
                    if future_call.get("json_body"):
                        body_str = json.dumps(future_call["json_body"])
                        if "{CREATED_ID}" in body_str or '"{id}"' in body_str:
                            body_str = body_str.replace("{CREATED_ID}", str(created_id)).replace('"{id}"', str(created_id))
                            future_call["json_body"] = json.loads(body_str)

    return JSONResponse({"status": "completed"})


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
