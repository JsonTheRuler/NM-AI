"""Checklist scoring via Claude API with structured tool_use output."""

import json

SCORING_TOOL = {
    "name": "checklist_score",
    "description": "Score the content against each checklist question with yes/no answers.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "passed": {"type": "boolean"},
                        "reasoning": {
                            "type": "string",
                            "description": "Brief explanation for why this passed or failed",
                        },
                    },
                    "required": ["question", "passed", "reasoning"],
                },
            }
        },
        "required": ["answers"],
    },
}

SYSTEM_PROMPT = """You are a strict, impartial content quality evaluator.

You will receive a piece of content and a checklist of yes/no quality questions.
For each question, evaluate the content honestly and answer with passed=true (meets the criterion) or passed=false (does not meet the criterion).

Rules:
- Be strict. If in doubt, fail the item.
- Evaluate each question independently.
- Your reasoning should be specific and cite evidence from the content.
- Do not be generous — the goal is to identify weaknesses accurately."""


def score_content(content: str, checklist: list[str], model: str, client) -> tuple[float, list[dict]]:
    """Score content against a checklist using Claude API.

    Returns:
        (score, results) where score is 0.0-1.0 and results is a list of
        {question, passed, reasoning} dicts.
    """
    checklist_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(checklist))

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[SCORING_TOOL],
        tool_choice={"type": "tool", "name": "checklist_score"},
        messages=[
            {
                "role": "user",
                "content": f"""Evaluate the following content against the checklist.

## Content to Evaluate
{content}

## Checklist Questions
{checklist_text}

Score each question as passed (true) or failed (false). Use the checklist_score tool.""",
            }
        ],
    )

    # Extract tool use result
    for block in response.content:
        if block.type == "tool_use" and block.name == "checklist_score":
            results = block.input["answers"]
            passed_count = sum(1 for r in results if r["passed"])
            score = passed_count / len(results) if results else 0.0
            return score, results

    # Fallback if no tool use found
    return 0.0, [{"question": q, "passed": False, "reasoning": "Scoring failed"} for q in checklist]
