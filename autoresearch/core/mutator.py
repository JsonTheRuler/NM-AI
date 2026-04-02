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

POLISH_SYSTEM_PROMPT = """You are an expert copywriter and content optimizer.

All quality checks are currently passing. Your job is to make the content EVEN BETTER while keeping all checks passing.

Focus on ONE of these improvement areas (pick a DIFFERENT one each time):
- Sharper, more vivid language that creates mental images
- Stronger emotional hooks that make the reader feel something
- Tighter phrasing — cut unnecessary words without losing meaning
- More specific numbers, examples, or scenarios
- Better rhythm and flow between sentences
- Stronger transitions between sections
- More compelling opening or closing lines
- Replace any remaining generic language with concrete details
- Improve scannability (clearer section headers, punchier bullet points)
- Add urgency or stakes without being manipulative

Rules:
- Make only ONE change. Do not rewrite the entire content.
- Return the COMPLETE updated content (not just the changed part).
- If the content is in Norwegian, keep it in Norwegian.
- Do not add filler, buzzwords, or generic marketing language.
- IMPORTANT: Do NOT repeat a change that was already tried (see previous changes list)."""


def mutate_content(
    content: str,
    failures: list[dict],
    content_context: str,
    model: str,
    client,
    previous_changes: list[str] | None = None,
    all_passing: bool = False,
) -> tuple[str, str]:
    """Make one small targeted change to the content.

    Args:
        content: Current content to improve
        failures: List of failing checklist items [{question, reasoning}]
        content_context: Context about the content type and audience
        model: Claude model to use
        client: Anthropic client
        previous_changes: List of previously tried change descriptions (to avoid repeats)
        all_passing: If True, use polish mode instead of fix mode

    Returns:
        (updated_content, change_description)
    """
    if all_passing:
        system = POLISH_SYSTEM_PROMPT
        failures_text = "All quality checks are PASSING. Make the content even stronger."
    else:
        system = SYSTEM_PROMPT
        failures_text = "\n".join(
            f"- FAILING: {f['question']}\n  Reason: {f['reasoning']}" for f in failures
        )

    prev_changes_text = ""
    if previous_changes:
        recent = previous_changes[-20:]  # Last 20 changes to avoid huge prompts
        prev_changes_text = f"\n\n## Previously Tried Changes (DO NOT REPEAT THESE)\n" + "\n".join(
            f"- {c}" for c in recent
        )

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        tools=[MUTATION_TOOL],
        tool_choice={"type": "tool", "name": "content_update"},
        messages=[
            {
                "role": "user",
                "content": f"""## Context
{content_context}

## Current Content
{content}

## Quality Checks
{failures_text}{prev_changes_text}

Make ONE small, targeted change. Return the complete updated content using the content_update tool.""",
            }
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "content_update":
            return block.input["updated_content"], block.input["change_description"]

    # Fallback — return unchanged
    return content, "No change made (mutation failed)"
