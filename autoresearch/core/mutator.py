"""Content mutation via Claude API — makes one small targeted change per iteration."""

MUTATION_TOOL = {
    "name": "content_update",
    "description": "Return the updated content with exactly one small targeted change.",
    "input_schema": {
        "type": "object",
        "properties": {
            "updated_content": {
                "type": "string",
                "description": "The complete updated content with the change applied",
            },
            "change_description": {
                "type": "string",
                "description": "A brief description of what was changed and why",
            },
        },
        "required": ["updated_content", "change_description"],
    },
}

SYSTEM_PROMPT = """You are an expert copywriter and content optimizer.

You will receive content that is being iteratively improved, along with a list of specific quality issues (failing checklist items).

Your job: Make exactly ONE small, targeted change to address the most impactful failing item.

Rules:
- Make only ONE change. Do not rewrite the entire content.
- Focus on the failing item that would have the biggest positive impact.
- Preserve the overall tone, structure, and length of the content.
- Return the COMPLETE updated content (not just the changed part).
- Your change should be specific and measurable — not vague improvements.
- If the content is in Norwegian, keep it in Norwegian. Match the original language.
- Do not add filler, buzzwords, or generic marketing language."""


def mutate_content(
    content: str,
    failures: list[dict],
    content_context: str,
    model: str,
    client,
) -> tuple[str, str]:
    """Make one small targeted change to the content.

    Args:
        content: Current content to improve
        failures: List of failing checklist items [{question, reasoning}]
        content_context: Context about the content type and audience
        model: Claude model to use
        client: Anthropic client

    Returns:
        (updated_content, change_description)
    """
    failures_text = "\n".join(
        f"- FAILING: {f['question']}\n  Reason: {f['reasoning']}" for f in failures
    )

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[MUTATION_TOOL],
        tool_choice={"type": "tool", "name": "content_update"},
        messages=[
            {
                "role": "user",
                "content": f"""## Context
{content_context}

## Current Content
{content}

## Failing Quality Checks
{failures_text}

Make ONE small, targeted change to fix the most impactful failing item. Return the complete updated content using the content_update tool.""",
            }
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "content_update":
            return block.input["updated_content"], block.input["change_description"]

    # Fallback — return unchanged
    return content, "No change made (mutation failed)"
