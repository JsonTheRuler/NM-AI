"""Main autoresearch optimization loop: mutate → score → keep/revert → repeat."""

import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .scorer import score_content
from .mutator import mutate_content

logger = logging.getLogger("autoresearch")


def _save_results_json(output_dir: Path, data: dict):
    """Write results.json for dashboard consumption."""
    with open(output_dir / "results.json", "w") as f:
        json.dump(data, f, indent=2, default=str)


def _append_changelog(output_dir: Path, entry: dict):
    """Append one line to changelog.jsonl."""
    with open(output_dir / "changelog.jsonl", "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def run_optimization(config: dict):
    """Run the autoresearch optimization loop.

    Args:
        config: Parsed configuration dict with keys:
            - input_content or input_path: the content to optimize
            - checklist: list of yes/no quality questions
            - content_context: context about the content
            - scorer_model, mutator_model: Claude model IDs
            - max_iterations: max loop iterations (default 50)
            - target_score: score threshold (default 0.95)
            - consecutive_target: times target must be hit (default 3)
            - output_dir: path to output directory
    """
    load_dotenv(Path(__file__).parent.parent.parent / ".env")

    client = anthropic.Anthropic()

    # Load content
    if "input_content" in config and config["input_content"]:
        content = config["input_content"]
    else:
        content = Path(config["input_path"]).read_text(encoding="utf-8")

    checklist = config["checklist"]
    content_context = config.get("content_context", "")
    scorer_model = config.get("scorer_model", "claude-sonnet-4-20250514")
    mutator_model = config.get("mutator_model", "claude-sonnet-4-20250514")
    max_iterations = config.get("max_iterations", 50)
    target_score = config.get("target_score", 0.95)
    consecutive_target = config.get("consecutive_target", 3)

    # Setup output directory
    project_name = config.get("project_name", "autoresearch")
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_base = Path(config.get("output_dir", Path(__file__).parent.parent / "output"))
    output_dir = output_base / f"{project_name}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "history").mkdir(exist_ok=True)

    # Store output_dir in config so dashboard can find it
    config["_output_dir"] = str(output_dir)

    # Save original and config snapshot
    (output_dir / "original.txt").write_text(content, encoding="utf-8")
    with open(output_dir / "config_snapshot.yaml", "w") as f:
        import yaml
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Checklist ({len(checklist)} items): {checklist}")

    # Score baseline
    logger.info("Scoring baseline...")
    best_score, best_results = score_content(content, checklist, scorer_model, client)
    best_content = content
    logger.info(f"Baseline score: {best_score:.0%}")

    scores = [best_score]
    consecutive_at_target = 0
    started_at = datetime.now().isoformat()

    # Save initial state
    results_data = {
        "project_name": project_name,
        "status": "running",
        "started_at": started_at,
        "current_iteration": 0,
        "max_iterations": max_iterations,
        "current_score": best_score,
        "target_score": target_score,
        "scores": scores,
        "checklist": best_results,
        "latest_change": "Baseline — no changes yet",
        "content_preview": best_content[:1000],
        "full_content": best_content,
        "consecutive_at_target": 0,
        "changelog": [],
    }
    _save_results_json(output_dir, results_data)
    (output_dir / "current_best.txt").write_text(best_content, encoding="utf-8")

    changelog_entries = []

    for iteration in range(1, max_iterations + 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"Iteration {iteration}/{max_iterations} | Best score: {best_score:.0%}")

        # Identify failures
        failures = [r for r in best_results if not r["passed"]]
        all_passing = len(failures) == 0

        if all_passing:
            logger.info("All checklist items passing!")
            consecutive_at_target += 1
            no_early_stop = config.get("no_early_stop", False)
            if not no_early_stop and consecutive_at_target >= consecutive_target:
                logger.info(f"Target reached {consecutive_target} times in a row. Stopping.")
                break
            failures = [{"question": "General improvement", "reasoning": "All items passing — make the content even stronger while maintaining score"}]

        # Mutate
        logger.info(f"{'Polishing' if all_passing else 'Failing items: ' + str(len(failures))}")
        try:
            all_change_descs = [e["change"] for e in changelog_entries]
            candidate, change_desc = mutate_content(
                best_content, failures, content_context, mutator_model, client,
                previous_changes=all_change_descs,
                all_passing=all_passing,
            )
        except Exception as e:
            logger.error(f"Mutation failed: {e}")
            change_entry = {
                "iteration": iteration,
                "timestamp": datetime.now().isoformat(),
                "score_before": best_score,
                "score_after": best_score,
                "kept": False,
                "change": f"Mutation error: {e}",
                "failing_items": [f["question"] for f in failures],
            }
            _append_changelog(output_dir, change_entry)
            changelog_entries.append(change_entry)
            continue

        # Score candidate
        logger.info(f"Change: {change_desc}")
        try:
            candidate_score, candidate_results = score_content(
                candidate, checklist, scorer_model, client
            )
        except Exception as e:
            logger.error(f"Scoring failed: {e}")
            continue

        logger.info(f"Candidate score: {candidate_score:.0%} (was {best_score:.0%})")

        # Keep or revert
        kept = candidate_score >= best_score
        if kept:
            best_content = candidate
            best_score = candidate_score
            best_results = candidate_results
            logger.info("KEPT — score improved or maintained")
        else:
            logger.info("REVERTED — score decreased")

        scores.append(best_score)

        # Track consecutive target hits
        if best_score >= target_score:
            consecutive_at_target += 1
        else:
            consecutive_at_target = 0

        # Save artifacts
        change_entry = {
            "iteration": iteration,
            "timestamp": datetime.now().isoformat(),
            "score_before": scores[-2] if len(scores) > 1 else best_score,
            "score_after": best_score,
            "candidate_score": candidate_score,
            "kept": kept,
            "change": change_desc,
            "failing_items": [f["question"] for f in failures],
        }
        _append_changelog(output_dir, change_entry)
        changelog_entries.append(change_entry)

        # Save iteration snapshot
        (output_dir / "history" / f"iteration_{iteration:03d}.txt").write_text(
            best_content, encoding="utf-8"
        )
        (output_dir / "current_best.txt").write_text(best_content, encoding="utf-8")

        # Update dashboard data
        results_data = {
            "project_name": project_name,
            "status": "running",
            "started_at": started_at,
            "current_iteration": iteration,
            "max_iterations": max_iterations,
            "current_score": best_score,
            "target_score": target_score,
            "scores": scores,
            "checklist": best_results,
            "latest_change": change_desc,
            "kept": kept,
            "content_preview": best_content[:1000],
            "full_content": best_content,
            "consecutive_at_target": consecutive_at_target,
            "changelog": changelog_entries,
        }
        _save_results_json(output_dir, results_data)

        # Stop condition
        no_early_stop = config.get("no_early_stop", False)
        if not no_early_stop and consecutive_at_target >= consecutive_target:
            logger.info(f"Target {target_score:.0%} reached {consecutive_target} times in a row!")
            break

    # Final save
    (output_dir / "final.txt").write_text(best_content, encoding="utf-8")
    results_data["status"] = "completed"
    results_data["completed_at"] = datetime.now().isoformat()
    _save_results_json(output_dir, results_data)

    logger.info(f"\nOptimization complete!")
    logger.info(f"Final score: {best_score:.0%}")
    logger.info(f"Iterations: {len(scores) - 1}")
    logger.info(f"Output: {output_dir}")

    return output_dir
