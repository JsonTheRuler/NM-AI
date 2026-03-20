# Decision Maker A — Verdict on Strategy Divergences

**Team EasyEiendom · NM i AI 2026**  
**Date:** 2026-03-20  
**Anchor:** `score = correctness × tier_multiplier × (1 + efficiency_bonus)`

---

## 1. Model Choice: Opus vs Sonnet

### DECISION: **Opus — with a caveat**

**Why Opus wins on paper:**
- Correctness dominates the score. A Tier 2 task at 100% correct = 2.0 base (+ efficiency). At 80% correct = 1.6, no efficiency bonus. That's a **≥25% score hit** from one wrong field.
- Accounting tasks have tricky semantics: VAT type selection, role names (`ROLE_ADMINISTRATOR` vs `ROLE_ACCOUNT_ADMINISTRATOR`), Norwegian date formats (DD.MM.YYYY → YYYY-MM-DD where getting day/month wrong is fatal), Nynorsk/French/German prompt parsing. Opus makes fewer conceptual errors here.
- Timeout math: Even with 10 agentic turns, Opus at ~15-20s/turn = 150-200s. Well within 300s. Mactias's strategy already proved this.

**The caveat:** If we observe actual timeouts in practice (Tier 3 tasks with 15+ turns), we fall back to Sonnet for that retry only. But don't implement this preemptively — premature optimization.

**Scoring impact:** Opus getting one more field right per task across 30 tasks could be 10-20 points. Sonnet being faster saves nothing if it's wrong.

---

## 2. Architecture: Agentic Loop vs Single-Shot Plan-Then-Execute

### DECISION: **Agentic loop — this is the single most important decision**

This is where the two plans fundamentally diverge, and the agentic loop is **clearly superior**. Here's why, grounded in the spec:

**The fatal flaw of single-shot planning:**

Ramil's plan has Claude generate ALL steps upfront, then a dumb executor runs them. This means:
1. **Claude never sees API responses.** If a POST returns an unexpected structure, or a field name was wrong, or a module needs activation first — the plan marches forward blindly.
2. **No error recovery.** Ramil's plan has `call_with_retry` for 5xx errors, but a 422 (validation error) on step 2 of 5 means steps 3-5 execute with garbage context. The competition spec says "Tripletex returns detailed error messages. Parse them to retry with corrections." — you can't parse what Claude never sees.
3. **Variable extraction is fragile.** The `{{customer_id}}` system works only if response shapes match what Claude predicted. Real APIs surprise you. An agentic loop lets Claude adapt.
4. **No adaptive complexity handling.** Tier 3 tasks ("bank reconciliation from CSV", "error correction in ledger") are inherently discovery-oriented. You might need to GET the ledger to find the error before knowing what to fix. A single-shot plan can't do this.

**Why the agentic loop wins on every scoring dimension:**

| Dimension | Single-shot | Agentic loop |
|-----------|------------|--------------|
| Correctness | Brittle — one wrong prediction cascades | Resilient — Claude adjusts per response |
| 4xx errors | Can't avoid them (blind execution) | Claude sees the 422, fixes on retry |
| API call count | Slightly fewer (no round-trips) | Slightly more, but quality calls |
| Timeout risk | Lower (one LLM call) | Manageable (10 turns × 20s = 200s) |

**The math that settles it:** A single-shot plan that gets 80% correct on a Tier 2 task scores 1.6. An agentic loop that uses 3 extra API calls but gets 100% correct scores ≥2.0 (even with mediocre efficiency). That's **+25% at minimum**.

**One thing Ramil's architecture does better:** `tool_choice: {"type": "tool", "name": "execute_accounting_task"}` forces structured output in one call. This is actually a good idea for **simple Tier 1 tasks** where the plan is obvious (1-2 calls). But for anything with dependencies or unknowns, the agentic loop is mandatory.

**Hybrid approach worth considering:** For known-simple tasks (if we can classify them from the prompt), use Ramil's single-shot for speed. For everything else, agentic loop. But don't over-engineer this — default to agentic loop.

---

## 3. Error Handling: Replanning vs No Replanning

### DECISION: **Mactias's approach (Claude sees errors) — non-negotiable**

Ramil's plan explicitly says: "4xx: log it, don't retry (likely won't help, will tank efficiency)." This is **dangerously wrong** for correctness.

Consider this scenario:
- Task: "Create an invoice for customer Acme AS with product Widget at 1500 NOK + 25% MVA"
- Claude's plan: POST /order → POST /orderline with `vatType: {"id": 3}` → PUT /order/:invoiceOrder
- Reality: vatType ID 3 doesn't exist on this fresh sandbox. It's actually ID 7.
- Ramil's system: 422 error, moves on, invoice never created. Score: **0.0**.
- Mactias's system: Claude sees the 422 ("Invalid vatType"), does GET /ledger/vatType, finds correct ID, retries. Score: **≥2.0** (with a small efficiency penalty for the extra calls, but who cares — it works).

The spec literally says: "If your agent achieves a perfect correctness score (1.0), you receive an efficiency bonus." The bonus is a cherry on top. The correctness is the cake. Ramil's approach throws away the cake to protect the cherry.

**Mactias's conservative mode (inject warning at 2+ errors)** is the right balance: be willing to retry, but don't spiral into trial-and-error.

---

## 4. Tier Prioritization

### DECISION: **Both are wrong in different ways. Correct order: Tier 2 > Tier 1 ≈ Tier 3 prep**

**Mactias says:** Tier 1 first (Friday evening), Tier 2 (Saturday), Tier 3 (Sunday)  
**Ramil says:** Tier 2 first, then Tier 1, then Tier 3

**Ramil is closer to right on ordering**, but both miss a key nuance from the spec:

> "Each submission receives one task, weighted toward tasks you've attempted less."

You don't get to choose which tier you work on. The system assigns tasks. So "prioritization" really means:
1. **What do you optimize your system prompt and testing for first?**
2. **When do you stop tweaking Tier 1 and focus on making Tier 2 work?**

**The correct strategy:**
- **Friday evening:** Get the agentic loop working. Test against sandbox with Tier 1 tasks (they're simplest for debugging). Do API discovery.
- **Saturday morning:** Submit to the platform. You'll get a mix of Tier 1 and 2. Focus system prompt refinements on whatever is failing.
- **Saturday (when Tier 3 opens):** Add Tier 3 knowledge to the system prompt. The agentic architecture handles novel tasks better than a pre-planned approach.

**Ramil's point about Tier 3 being 80% of total score potential** (20 tasks × 6.0 max = 120 out of 150) is **the single most important strategic insight in either plan**. This means our architecture MUST handle Tier 3 well. Agentic loop is essential for this.

---

## 5. System Prompt Completeness

### DECISION: **Merge the best of both, but Ramil's API schema detail is more important than Mactias's behavioral rules**

Both prompts have good elements:

**Mactias's prompt strengths:**
- "NEVER GET after POST" — critical efficiency rule
- "Copy field values character-for-character" — prevents subtle correctness bugs
- Date handling section with DD.MM.YYYY conversion
- Error budget awareness ("after 2 total errors, be extra careful")
- Entity dependency chain visualization

**Ramil's prompt strengths:**
- Exact field schemas per endpoint (prevents 422s)
- Invoice creation flow (order → orderline → invoiceOrder) — **this is gold**
- `PUT /order/{id}/:invoiceOrder` instead of `POST /invoice` — this is likely the correct Tripletex flow
- `PUT /invoice/{id}/:payment` with specific params
- `vatType: {id: 3}` for standard 25% VAT

**What's missing from BOTH:**
- **Actual empirically-verified field schemas.** Both plans acknowledge this. Mactias's plan says "discover first, then write prompt" — this is correct. Ramil guesses at schemas.
- **Response format examples.** Neither shows Claude what a successful POST response looks like (`{"value": {"id": 123, ...}}`). This matters for the agentic loop — Claude needs to know where to find the ID.
- **Module activation patterns.** Both mention it vaguely. We need the actual endpoint.

**Final prompt strategy:**
1. Start with Mactias's behavioral rules (efficiency, no GET-after-POST, character-exact values)
2. Add Ramil's field schemas as the API reference section
3. After API discovery Friday evening, replace guessed schemas with verified ones
4. Add response format examples

---

## 6. Other Critical Gaps

### 6a. Invoice Creation Flow — CRITICAL

Ramil's plan suggests `PUT /order/{id}/:invoiceOrder` as the invoice creation method. Mactias's plan uses `POST /invoice`. **Neither has verified this empirically.**

This is potentially a make-or-break difference. If `/invoice` POST doesn't work on fresh accounts (which is plausible — Tripletex often requires the order flow), then Mactias's entire system prompt is teaching Claude the wrong approach.

**ACTION REQUIRED:** Before writing the final system prompt, test BOTH approaches against the sandbox. Use whichever works. If both work, use `/order/:invoiceOrder` (it's more standard Tripletex).

### 6b. Pre-flight Validation — KEEP IT

Mactias has a pre-flight validation that checks required fields before sending the API call. This is **excellent** for efficiency — it prevents a 422 AND saves an API call. However:
- Don't hard-block on validation. Return the error to Claude (in agentic loop) so it can fix and retry.
- The required fields dict will need updating after API discovery.

### 6c. Ramil's File Pre-extraction — SKIP IT

Ramil suggests a separate Claude call to extract data from files before planning. This wastes ~10-15 seconds and an extra LLM call. In the agentic loop, Claude sees the files as content blocks and plans accordingly. One less moving part.

### 6d. Logging — ESSENTIAL (Mactias has it, Ramil doesn't)

Mactias's plan includes proper logging. Ramil's code has zero logging. We need logs to debug failures after platform submissions. Non-negotiable.

### 6e. Streaming — IMPLEMENT IT

Mactias's plan includes streaming for the Claude API calls. This saves 1-3s per turn. Over 10 turns, that's 10-30s — meaningful when the ceiling is 300s. Ramil's plan doesn't mention it.

### 6f. Task Type Detection Gap

Neither plan addresses this: the competition spec says "Each submission receives one task, **weighted toward tasks you've attempted less.**" This means early submissions will cover more task types. We should submit frequently early on to discover all 30 task types and their scoring criteria, then optimize.

### 6g. The `tool_choice` Trick

Ramil's `tool_choice: {"type": "tool", "name": "..."}` forces Claude to use the tool (no "let me think about this" text responses). In an agentic loop, we should NOT use this — we want Claude to be able to signal completion with text or a `task_complete` tool. But we should use `tool_choice: {"type": "auto"}` and handle both text and tool_use responses.

---

## Summary: The Merged Strategy

| Decision Point | Winner | Key Reason |
|---------------|--------|------------|
| Model | **Opus** (Mactias) | Correctness dominates scoring; timeout math works |
| Architecture | **Agentic loop** (Mactias) | Error recovery + adaptability for Tier 3 = massive correctness gains |
| Error handling | **Claude sees errors** (Mactias) | Spec rewards correctness above all; blind execution is fatal |
| Tier priority | **Ramil's ordering** (Tier 2 first) | Higher ROI, but agentic loop matters more than ordering |
| System prompt | **Merge both** | Mactias's rules + Ramil's schemas, verified empirically |
| Pre-flight validation | **Keep** (Mactias) | Prevents 422s, saves API calls |
| Streaming | **Yes** (Mactias) | 10-30s saved over a task |
| File handling | **Inline** (Mactias) | Skip Ramil's separate extraction call |
| Logging | **Yes** (Mactias) | Essential for debugging platform submissions |
| Variable tracking | **Agentic loop makes this moot** | Claude tracks IDs naturally by seeing responses |
| Invoice flow | **VERIFY BOTH** then decide | This is the single biggest unknown |

### Bottom Line

**Use Mactias's architecture (agentic tool-use loop with Opus) as the foundation. Integrate Ramil's superior API schema knowledge into the system prompt. Verify all schemas empirically against the sandbox Friday evening. The agentic loop is non-negotiable — it's the difference between a fragile bot and an adaptive agent, and on Tier 3 tasks worth 120 of 150 possible points, adaptability is everything.**

The current `main.py` is inadequate (single-shot, one `{CREATED_ID}` substitution, no error recovery, no logging, no timeout management). It needs a full rewrite to Mactias's agentic architecture, enhanced with Ramil's schema knowledge.
