#!/usr/bin/env python3
"""Autoresearch — Automated content optimization via iterative Claude scoring.

Usage:
    python -m autoresearch.run --config configs/landing_page.yaml
    python -m autoresearch.run --input content.txt --type landing_page
    python -m autoresearch.run --input content.txt --type landing_page --auto-checklist
"""

import logging
import sys
from pathlib import Path

import click
import yaml

from core.optimizer import run_optimization
from dashboard.server import start_dashboard, update_output_dir

logger = logging.getLogger("autoresearch")

# Default checklists per content type
DEFAULT_CHECKLISTS = {
    "landing_page": [
        "Does the headline clearly communicate the main value proposition in one sentence?",
        "Is there a clear, specific call-to-action (not generic like 'Learn More')?",
        "Does the copy mention a specific pain point the target audience faces?",
        "Is the language free of buzzwords and jargon?",
        "Does the page include social proof or credibility signals?",
        "Does the first paragraph hook the reader with a concrete benefit or result?",
    ],
    "ad_copy": [
        "Does the headline include a specific benefit or result?",
        "Is the copy under 90 words?",
        "Does it include a clear, action-oriented CTA?",
        "Does it address a specific pain point in the first sentence?",
        "Is it free of superlatives and unsubstantiated claims?",
    ],
    "newsletter": [
        "Does the opener create curiosity or urgency without clickbait?",
        "Does the first paragraph include a personal or relatable detail?",
        "Is the email under 200 words?",
        "Is there exactly one clear CTA?",
        "Is it free of cliche phrases?",
    ],
}


def generate_checklist(content: str, content_type: str, count: int = 5) -> list[str]:
    """Auto-generate a scoring checklist using Claude."""
    import anthropic
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")
    client = anthropic.Anthropic()

    tool = {
        "name": "checklist",
        "description": "Return a list of yes/no quality checklist questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of yes/no quality checklist questions",
                }
            },
            "required": ["questions"],
        },
    }

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=f"""You are a content quality expert. Generate exactly {count} yes/no checklist questions
for evaluating {content_type} content. Each question should:
- Be answerable with a clear yes or no
- Check one specific, measurable quality aspect
- Catch common weaknesses (vague language, missing CTAs, no social proof, etc.)
- Be strict enough that mediocre content fails at least half the items""",
        tools=[tool],
        tool_choice={"type": "tool", "name": "checklist"},
        messages=[
            {
                "role": "user",
                "content": f"Generate a scoring checklist for this {content_type}:\n\n{content[:2000]}",
            }
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "checklist":
            return block.input["questions"][:count]

    return DEFAULT_CHECKLISTS.get(content_type, DEFAULT_CHECKLISTS["landing_page"])


@click.command()
@click.option("--config", "config_path", type=click.Path(exists=True), help="Path to YAML config file")
@click.option("--input", "input_path", type=click.Path(exists=True), help="Path to content file")
@click.option("--type", "content_type", type=click.Choice(["landing_page", "ad_copy", "newsletter"]), help="Content type")
@click.option("--auto-checklist", is_flag=True, help="Auto-generate checklist using Claude")
@click.option("--checklist-count", default=5, help="Number of checklist items to generate (with --auto-checklist)")
@click.option("--no-dashboard", is_flag=True, help="Disable the web dashboard")
@click.option("--max-iterations", default=None, type=int, help="Override max iterations")
@click.option("--port", default=8501, type=int, help="Dashboard port")
def main(config_path, input_path, content_type, auto_checklist, checklist_count, no_dashboard, max_iterations, port):
    """Autoresearch — Automatically optimize content with iterative Claude scoring."""

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.StreamHandler()],
    )

    # Load config
    if config_path:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    elif input_path:
        config = {
            "project_name": Path(input_path).stem,
            "input_path": input_path,
            "content_type": content_type or "landing_page",
            "content_context": f"This is a {content_type or 'landing_page'} being optimized.",
            "scorer_model": "claude-sonnet-4-20250514",
            "mutator_model": "claude-sonnet-4-20250514",
            "max_iterations": 30,
            "target_score": 0.95,
            "consecutive_target": 3,
            "output_dir": str(Path(__file__).parent / "output"),
        }
    else:
        click.echo("Error: Provide either --config or --input")
        sys.exit(1)

    # Override max iterations if specified
    if max_iterations is not None:
        config["max_iterations"] = max_iterations

    # Resolve content path relative to autoresearch root (not config file location)
    autoresearch_root = Path(__file__).parent
    if "input_content" not in config or not config.get("input_content"):
        content_path = config.get("input_path")
        if content_path and not Path(content_path).is_absolute():
            content_path = str(autoresearch_root / content_path)
            config["input_path"] = content_path

    # Handle checklist
    if auto_checklist or (not config.get("checklist") and config.get("auto_checklist")):
        logger.info("Auto-generating checklist...")
        if "input_content" in config:
            content = config["input_content"]
        else:
            content = Path(config["input_path"]).read_text(encoding="utf-8")
        config["checklist"] = generate_checklist(
            content,
            config.get("content_type", "landing_page"),
            checklist_count,
        )
        logger.info(f"Generated {len(config['checklist'])} checklist items:")
        for q in config["checklist"]:
            logger.info(f"  - {q}")
    elif not config.get("checklist"):
        ct = config.get("content_type", "landing_page")
        config["checklist"] = DEFAULT_CHECKLISTS.get(ct, DEFAULT_CHECKLISTS["landing_page"])
        logger.info(f"Using default {ct} checklist ({len(config['checklist'])} items)")

    # Resolve output dir
    output_dir = config.get("output_dir", str(autoresearch_root / "output"))
    if not Path(output_dir).is_absolute():
        output_dir = str(autoresearch_root / output_dir)
    config["output_dir"] = output_dir

    # Start dashboard
    if not no_dashboard and config.get("dashboard", True):
        logger.info(f"Starting dashboard on http://localhost:{port}")
        start_dashboard(output_dir, port=port, open_browser=True)

    # Run optimization
    click.echo(f"\n{'='*60}")
    click.echo("  AUTORESEARCH — Automated Content Optimization")
    click.echo(f"{'='*60}")
    click.echo(f"  Project:    {config.get('project_name', 'autoresearch')}")
    click.echo(f"  Type:       {config.get('content_type', 'unknown')}")
    click.echo(f"  Checklist:  {len(config['checklist'])} items")
    click.echo(f"  Max rounds: {config.get('max_iterations', 30)}")
    click.echo(f"  Target:     {config.get('target_score', 0.95):.0%}")
    if not no_dashboard:
        click.echo(f"  Dashboard:  http://localhost:{port}")
    click.echo(f"{'='*60}\n")

    result_dir = run_optimization(config)

    # Update dashboard with final output dir
    if not no_dashboard:
        update_output_dir(str(result_dir))

    click.echo(f"\nDone! Results saved to: {result_dir}")
    click.echo(f"  Original:  {result_dir}/original.txt")
    click.echo(f"  Improved:  {result_dir}/final.txt")
    click.echo(f"  Changelog: {result_dir}/changelog.jsonl")


if __name__ == "__main__":
    main()
