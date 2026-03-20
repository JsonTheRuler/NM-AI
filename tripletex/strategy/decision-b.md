# Decision Maker B — Contrarian Critique of Decision A

**Team EasyEiendom · NM i AI 2026**  
**Date:** 2026-03-20  
**Role:** Devil's Advocate — challenging A's verdicts with scoring-grounded arguments

---

## Preamble: A's Blind Spot

Decision A is well-reasoned but suffers from a single dominant bias: **it optimizes for correctness on hard tasks while undervaluing throughput, efficiency bonuses, and coverage speed.** Nearly every verdict favors the slower, heavier approach. In a competition with 30 task types, 56 variants each, 10 submissions/task/day, and 300s timeouts, this bias has real scoring consequences that A never quantifies.

Let me go verdict by verdict.

---

## 1. Model Choice: Opus vs Sonnet

### A says: Opus — correctness dominates

### B says: **A is probably right, but the argument is weaker than presented**

A's case rests on: "Opus getting one more field right per task across 30 tasks could be 10-20 points." This is hand-waving. Where's the evidence that Opus gets fields right that Sonnet doesn't?

**What A ignores:**

1. **Sonnet 4 is not Sonnet 3.5.** Claude Sonnet 4 is extremely capable at structured extraction, multilingual parsing, and tool use. The gap with Opus on *accounting field extraction* (not creative writing, not PhD-level reasoning) is likely much smaller than A assumes. These are fundamentally extraction + API-calling tasks, not open-ended reasoning.

2. **Throughput = coverage = points.** The spec says "Each submission receives one task, weighted toward tasks you've attempted less." With Opus agentic at ~200s/task, we get ~18 submissions/hour. With Sonnet at ~50s/task (single-shot or lean agentic), we get ~60 submissions/hour. **3× more coverage per hour.** Early coverage of all 30 task types matters enormously because:
   - Best score per task is kept (bad runs don't hurt)
   - We discover all task types faster → can optimize system prompt faster
   - More attempts = more chances at perfect scores with good efficiency

3. **A's timeout math is optimistic.** "10 turns × 15-20s = 150-200s" — this assumes no retries, no complex Tier 3 reasoning, no extended thinking. Opus with a genuine Tier 3 task (bank reconciliation from CSV) could easily need 12-15 turns with heavier reasoning. At 20s/turn that's 240-300s — right at the wire. One slow API response and you timeout. Score: **0.0.**

**My actual position:** Use Opus, but **only because best-score-per-task means we can afford the occasional timeout.** A bad Opus run costs nothing (best score kept). A good Opus run on a tricky task could be +0.5 over Sonnet. But A should acknowledge this is a marginal call, not a slam dunk. And we should have Sonnet ready as a fallback — not as an afterthought, but as a configured alternative.

**Scoring impact of being wrong:** Low. Both models will handle Tier 1/2 well. The real gap, if any, is on Tier 3. But Tier 3 opens Saturday, so we'll have data.

---

## 2. Architecture: Agentic Loop vs Single-Shot

### A says: Agentic loop — "clearly superior," "non-negotiable"

### B says: **A is dangerously overconfident. The agentic loop introduces costs A refuses to count.**

This is where I disagree most strongly. A treats the agentic loop as a free upgrade. It's not. Let me count the costs:

**Cost 1: Latency (quantified)**

| Architecture | LLM calls | Time/task (Opus) | Time/task (Sonnet) | Submissions/hour |
|---|---|---|---|---|
| Single-shot | 1 | ~20s + execution | ~5s + execution | ~60-100 |
| Agentic (avg 5 turns) | 5 | ~100s + execution | ~25s + execution | ~25-30 |
| Agentic (10 turns) | 10 | ~200s + execution | ~50s + execution | ~15 |

With 10 submissions/task/day limit and 30 task types, we need ~300 submissions for full coverage. At 15/hour (Opus agentic worst case), that's **20 hours of continuous running.** At 60/hour (Sonnet single-shot), it's **5 hours.** Coverage speed is a strategic asset.

**Cost 2: The agentic loop has its OWN error modes**

A assumes the agentic loop only helps. But each round-trip is a chance for Claude to:
- **Change strategy mid-stream** ("Actually, let me try a different approach..." → wasted calls)
- **Over-explore** ("Let me GET /ledger/vatType to see what's available..." → unnecessary call)
- **Hallucinate based on partial context** (seeing one error and overcorrecting)
- **Lose track of what it already did** (in long conversations, Claude can forget earlier context)

Single-shot with a great system prompt avoids ALL of these. Claude plans once, carefully, with all the schemas right there.

**Cost 3: Efficiency bonus impact is MASSIVE — A downplays it**

A says "the efficiency bonus is a cherry on top." Let me do the actual math from the spec:

> "If your agent achieves a perfect correctness score (1.0), you receive an efficiency bonus that can **up to double** your tier score."

So for a perfect Tier 2 task:
- Best efficiency: **4.0** (2.0 × 2)
- Mediocre efficiency: **~2.6** (2.0 × 1.3)
- Poor efficiency: **~2.1** (2.0 × 1.05)

The difference between best and poor efficiency on a perfect task is **1.9 points.** Across 30 tasks, that's **up to 57 points** from efficiency alone. A dismisses this as "cherry on top" — it's potentially **40% of the total score.**

The agentic loop inherently makes MORE API calls (each turn adds potential calls) and errors in the loop (Claude trying something wrong, then fixing it) count as 4xx errors that tank the efficiency bonus.

**Cost 4: A's killer example (VAT type) is actually a planning problem, not an architecture problem**

A says: "vatType ID 3 doesn't exist. Ramil's system: 422, score 0.0. Mactias's system: sees error, does GET, finds correct ID."

But this is a false dichotomy. The correct solution is: **put "always GET /ledger/vatType first" in the system prompt plan.** Both architectures can handle this if the prompt is right. The single-shot plan would include a GET step before the POST. A is comparing good-agentic vs bad-single-shot, not good-agentic vs good-single-shot.

**Where A IS right:**

A is correct that for genuinely unpredictable Tier 3 tasks (bank reconciliation, error correction in ledger), the agentic loop is necessary. You can't plan a "find the error in the ledger" task without first seeing the ledger.

But Tier 3 is **10 of 30 tasks at most** (and opens Saturday). For the other 20 tasks (Tier 1 and 2), the operations are predictable: create employee, create invoice, register payment. These are TEMPLATE tasks. An agentic loop is overkill.

### B's Actual Position: **Hybrid is the only correct answer — but not A's hybrid**

A mentions a hybrid approach but dismisses it: "don't over-engineer this — default to agentic loop." I say the opposite: **default to single-shot, escalate to agentic on failure or for known-complex tasks.**

Here's the architecture:

```
POST /solve
  ├─ Classify task complexity from prompt (fast heuristic or first LLM call)
  ├─ IF simple (Tier 1, known patterns):
  │    └─ Single-shot plan + execute (Ramil's approach with good schemas)
  │       └─ IF any step fails: escalate to agentic recovery (1-2 more turns)
  ├─ IF complex (Tier 3, discovery-required):
  │    └─ Full agentic loop (Mactias's approach)
  └─ Return {"status": "completed"}
```

**Why this beats pure-agentic:**
- Tier 1 tasks complete in ~25s instead of ~120s → 5× faster
- Tier 1 tasks use 1 LLM call instead of 3-5 → lower cost, fewer error opportunities
- Tier 1 efficiency bonus is maximized (minimal calls, zero errors)
- Tier 3 still gets full agentic treatment
- Failed single-shot gets a SECOND CHANCE via agentic recovery (escalation)

**Scoring impact:** If single-shot handles 20/30 tasks well, and the efficiency bonus delta is ~1 point/task, that's **~20 points** we're leaving on the table with pure-agentic.

---

## 3. Error Handling: Replanning vs No Replanning

### A says: Claude sees errors — "non-negotiable"

### B says: **A is right on principle, wrong on implementation**

A correctly identifies that Ramil's "don't retry 4xx" is too aggressive. A 422 with a fixable error message should be retried.

But A's implementation (full agentic loop where Claude sees every error) has a hidden cost: **Claude often OVER-corrects.** Give Claude a 422 error and it might:
1. Change the entire approach instead of fixing one field
2. Add unnecessary GET calls to "be safe"
3. Retry with different data instead of fixing the specific field mentioned in the error

**Better approach: Targeted error recovery**

```python
# After a 4xx error on a POST/PUT:
if 400 <= status < 500 and error_message:
    # Give Claude ONLY the error message and ask for a fixed version
    # of the SAME call — not a whole new plan
    fix_response = claude.messages.create(
        messages=[{
            "role": "user", 
            "content": f"This API call failed:\n{method} {endpoint}\nBody: {json_body}\nError: {error_message}\n\nReturn ONLY the corrected json_body. Fix the specific issue mentioned in the error."
        }]
    )
    # Retry with fixed body — ONE retry, ONE LLM call
```

This is **cheaper than an agentic turn** (smaller prompt, faster response) and **more focused** (Claude fixes one thing instead of replanning everything).

**Scoring impact:** Small but positive. The difference between "Claude replans" and "Claude fixes one field" is maybe 1-2 unnecessary API calls per error recovery, which impacts efficiency bonus.

---

## 4. Tier Prioritization

### A says: Both wrong, correct order is Tier 2 > Tier 1 ≈ Tier 3 prep

### B says: **A misses the most important insight: you don't control task assignment**

A quotes the spec: "Each submission receives one task, weighted toward tasks you've attempted less." Then A says prioritization means "what do you optimize your system prompt for first?"

But A buries the real implication: **submission velocity IS the strategy.** The competition assigns tasks weighted toward your gaps. So:

1. **Submit as fast as possible** to discover all 30 task types
2. **Submit as often as possible** to get re-rolls on tasks you scored poorly
3. **Don't spend 2 hours perfecting one task type** when you could be discovering 10 others

This further supports SPEED over DEPTH, which means:
- Sonnet for early discovery phase (controversial, I know — but hear me out)
- Fast architecture (single-shot) for coverage
- Switch to Opus + agentic for optimization once we know all task types

**What neither plan addresses: the information game**

Every submission gives us back:
- Which task type we got
- Our field-by-field score
- How many API calls we made

This is **gold.** After 30 submissions, we know every task type and every field the scorer checks. We can then write EXACT templates for each task type. Neither plan builds this feedback loop.

**Proposed feedback loop:**
```python
# After each submission result comes back:
# 1. Log: task_type, score, checks_passed, checks_failed, api_call_count
# 2. If score < 1.0: analyze which fields failed → update system prompt
# 3. If score = 1.0 but low efficiency: count calls → optimize
# 4. Maintain a task_knowledge.json with learned patterns per task type
```

**Scoring impact:** This meta-optimization could be worth 20-30 points over the competition. Neither plan has it.

---

## 5. System Prompt

### A says: Merge both, Ramil's schemas matter more

### B says: **A is right here, but both prompts have a CRITICAL shared flaw**

Both plans write the system prompt BEFORE doing API discovery. Both acknowledge this is wrong ("test empirically," "discover first"). Yet Mactias's strategy already has a detailed prompt, and Ramil's has exact field schemas that are GUESSED.

**The specific dangers:**
- Ramil says `vatType: {id: 3}` for 25% VAT. What if it's `{id: 7}` on fresh accounts? Now the system prompt is actively teaching Claude WRONG information.
- Ramil says `PUT /order/{id}/:invoiceOrder` for invoice creation. What if fresh accounts need POST /invoice? Neither has verified this.
- Mactias says `POST /invoice` with orders array. What if this requires pre-existing orders with specific status?

**My demand:** The system prompt MUST be written AFTER 2 hours of API discovery Friday evening. Any prompt written before that is a draft, not a strategy.

**What I'd add that neither has:**

1. **Response format documentation.** Neither prompt shows Claude what a successful response looks like. Claude needs to know: `{"value": {"id": 123, "firstName": "Ola", ...}}` for POST, `{"fullResultSize": 5, "values": [...]}` for GET. This prevents Claude from misinterpreting responses.

2. **Explicit "don't translate" rules per language.** The prompt says "copy character-for-character" but doesn't address that a German prompt might say "Erstellen Sie einen Mitarbeiter" and the API field is still `firstName` not `vorname`. Claude needs to know: **field names are ALWAYS English, only VALUES come from the prompt.**

3. **Common Tripletex gotchas** (to be filled after discovery):
   - Does `isCustomer: true` need to be explicit or is it default?
   - Are there default employees/customers on fresh accounts?
   - What modules are pre-enabled?
   - What happens if you POST to an endpoint that requires module activation?

---

## 6. What A Misses Entirely

### 6a. Cost of Anthropic API calls

Nobody mentions this. Opus is ~15× more expensive than Sonnet per token. An agentic loop with 10 Opus calls per task × 30 tasks × 56 variants × multiple attempts = potentially thousands of dollars. Is there a budget? If so, Sonnet-default with Opus-fallback is the financially responsible choice.

**Scoring impact:** Zero directly, but if we run out of API budget Saturday afternoon, game over.

### 6b. Concurrent submissions = 3 for verified teams

The spec says verified teams can submit 3 concurrently. A says "submit sequentially." **Why?** A argues "Risk of hitting the same task type 3× wastes our 10/task/day limit."

But the spec says tasks are weighted toward LESS-ATTEMPTED tasks. So 3 concurrent submissions will likely get 3 DIFFERENT task types. Concurrent submission is a **3× throughput multiplier** at no scoring cost. We should absolutely use it.

**Scoring impact:** 3× throughput = 3× faster coverage of all 30 task types.

### 6c. The "best score per task" mechanic is underexploited

A mentions it once: "Bad runs never lower your score." But neither plan builds strategy around this. This means:

- **Aggressive experimentation is FREE.** Try risky things — if they work, great. If not, no harm.
- **Two-pass strategy:** First pass = coverage (get ANY score on all 30 tasks). Second pass = optimization (improve each score).
- **We should submit FAST with a "good enough" agent first,** then optimize. Spending Friday evening perfecting the agent before any submission is wrong. Submit the current main.py (even if bad) to start learning task types.

### 6d. The pre-flight validation is a double-edged sword

A loves Mactias's pre-flight validation. But consider: if the REQUIRED_FIELDS dict is WRONG (which it will be before API discovery), it will BLOCK correct calls. Claude might correctly know that `/project` needs `name` and `projectManager`, but if our hardcoded dict also requires `startDate` (and it's actually optional), we'll reject Claude's correct call.

**Better:** Let Claude's calls through. If they get 422'd, the Tripletex error message is more accurate than our hardcoded validation. Pre-flight validation should be ADVISORY (included in Claude's context) not BLOCKING (preventing the API call).

### 6e. The prompt is in 7 languages but examples are all Norwegian/English

Both system prompts have examples only in Norwegian and English. But the task could come in Spanish, Portuguese, German, French, or Nynorsk. We should have at least one example per language to prime Claude, especially for:
- European number format (`1.500,00` = 1500.00)
- Date formats (German: `15. März 2026`, French: `15 mars 2026`)
- Nynorsk vocabulary differences from Bokmål

### 6f. No graceful degradation

What happens when Claude returns garbage? Both plans assume Claude always returns valid tool_use or valid JSON. But:
- What if Claude refuses the task? ("I can't help with that")
- What if the tool_use response has empty steps?
- What if Claude hallucinates an endpoint?

The fallback should be: **log everything, return {"status": "completed"}, move on.** Never let a parsing error crash the server. Every crash = missed submission = missed points.

---

## 7. Is There a THIRD Architecture?

### Yes: **Template-First with Agentic Fallback**

Neither plan proposes this, but it's the optimal architecture:

```
Architecture: Template → Single-Shot → Agentic (escalation ladder)

Level 1: TEMPLATE (no LLM call)
  If we can classify the task AND have a proven template → execute template directly
  Example: "Opprett ansatt Ola Nordmann, ola@test.no" → POST /employee with extracted fields
  Time: <1s | API calls: 1 | Efficiency: MAXIMUM

Level 2: SINGLE-SHOT (1 LLM call)  
  If task is novel but predictable → Claude plans once, executor runs
  Example: "Create invoice for customer X with product Y" → Claude outputs 4-step plan
  Time: ~10s | API calls: 3-5 | Efficiency: High

Level 3: AGENTIC (multiple LLM calls)
  If single-shot fails OR task requires discovery → full agentic loop
  Example: "Find and correct the error in the ledger" → Claude explores
  Time: ~120s | API calls: 5-15 | Efficiency: Lower but correctness maximized
```

**Why this is superior:**

1. **Tier 1 at Level 1:** After API discovery, we KNOW the exact calls for "create employee." Why ask Claude at all? Parse the prompt (one fast Claude call or even regex), extract fields, fire the API call. Perfect efficiency, zero errors, ~1 second.

2. **Tier 2 at Level 2:** Invoice creation is a known flow. Claude plans it, executor runs it. If a step fails, escalate to Level 3 for recovery.

3. **Tier 3 at Level 3:** These genuinely need agentic reasoning.

4. **The escalation is AUTOMATIC:** Failed Level 1 → Level 2. Failed Level 2 → Level 3. No manual classification needed.

**Scoring math:**
- 10 Tier 1 tasks at Level 1: avg 1.8/2.0 (near-perfect efficiency) = 18 points
- 10 Tier 2 tasks at Level 2: avg 3.2/4.0 (good efficiency) = 32 points
- 10 Tier 3 tasks at Level 3: avg 3.5/6.0 (ok efficiency) = 35 points
- **Total: ~85 points**

vs. Pure agentic (A's approach):
- 10 Tier 1 tasks: avg 1.4/2.0 (wasted calls from loop overhead) = 14 points
- 10 Tier 2 tasks: avg 2.8/4.0 (good correctness, mediocre efficiency) = 28 points  
- 10 Tier 3 tasks: avg 3.5/6.0 (same — this is where agentic shines) = 35 points
- **Total: ~77 points**

The template-first approach wins by **~8 points** — entirely from efficiency bonuses on simple tasks.

**Caveat:** This requires more engineering effort (templates, classifier). If we can't build it Friday evening, default to A's pure agentic. But it's worth considering.

---

## 8. Summary: Where A Is Right, Wrong, and Incomplete

| Verdict | A's Position | B's Assessment | B's Alternative |
|---------|-------------|----------------|-----------------|
| Model | Opus | **Mostly right** — but overconfident; gap is smaller than claimed | Opus default, Sonnet ready, acknowledge marginal |
| Architecture | Pure agentic | **Overconfident, ignores costs** — efficiency loss is ~8+ points | Hybrid: single-shot default, agentic escalation |
| Error recovery | Claude sees errors | **Right on principle, wrong on implementation** | Targeted fix (small LLM call) not full replan |
| Tier priority | Tier 2 first | **Misses throughput** — coverage speed matters more than optimization order | Submit fast first, optimize second |
| System prompt | Merge both | **Right but premature** — must be post-discovery | Agree, but add response format docs + multi-language examples |
| Pre-flight validation | Hard block | **Risky if validation dict is wrong** | Advisory, not blocking |
| Concurrent submissions | Sequential | **Wrong** — 3× throughput is free | Use all 3 concurrent slots |
| Streaming | Yes | **Agree** | Agree |
| File handling | Inline | **Agree** | Agree |
| Template option | Not considered | **Significant missed optimization** | Template → Single-shot → Agentic ladder |
| Feedback loop | Not addressed | **Critical gap** | Log every result, update prompts dynamically |
| Graceful degradation | Not addressed | **Essential for robustness** | Never crash, always return completed |

### Bottom Line

A's instinct is right: correctness matters most, and the agentic loop helps with correctness. But A treats the agentic loop as zero-cost, dismisses efficiency bonuses as "cherry on top" (they're worth ~40% of total score on perfect tasks), ignores throughput implications, and doesn't consider that most tasks are PREDICTABLE.

**The optimal strategy is: be as simple as possible for simple tasks, as complex as necessary for complex tasks.** Pure agentic violates this by being complex for everything. The escalation ladder — template → single-shot → agentic — respects both correctness AND efficiency.

**If we only have time for one architecture Friday evening:** Build the agentic loop (A is right that it's the safest single choice). But build it in a way that we can ADD templates and single-shot paths later without rewriting everything. Keep the architecture modular.

---

*Decision Maker B — Team EasyEiendom*  
*Every point anchored to scoring impact. The Synthesizer decides.*
