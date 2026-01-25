import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, Any, Optional

from .config import load_config
from .workflow import run_once
from .git_utils import get_repo_root
from .prd_generator import generate_prd

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

logger = logging.getLogger(__name__)

def _save_prd(prd_path: Path, data: Dict[str, Any]) -> None:
    """Saves the PRD data to the JSON file with pretty printing."""
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_prd(repo_root: Path, feature_id: str, specs_dir: str = "specs") -> Dict[str, Any]:
    """
    Loads and validates PRD JSON from the feature directory.
    Does NOT generate PRD - user must run generator separately.
    
    Raises:
        FileNotFoundError: If prd.json doesn't exist
        json.JSONDecodeError: If PRD is invalid JSON
        ValueError: If PRD missing required fields
    """
    feature_dir = repo_root / specs_dir / feature_id
    prd_path = feature_dir / "prd.json"
    
    if not prd_path.exists():
        raise FileNotFoundError(
            f"PRD file not found: {prd_path}\n"
            f"Please run the PRD generator first:\n"
            f"  python -m ai_refactor.prd_generator --feature-id {feature_id}"
        )
    
    try:
        data = json.loads(prd_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(
            f"Invalid JSON in PRD file {prd_path}: {e.msg}",
            e.doc,
            e.pos
        )
    
    # Validate required fields
    if "stories" not in data:
        raise ValueError(f"PRD missing required field 'stories' in {prd_path}")
    if "context" not in data:
        raise ValueError(f"PRD missing required field 'context' in {prd_path}")
    
    logger.info(f"PRD loaded successfully from {prd_path}")
    return data

def select_next_story(
    prd: Dict[str, Any],
    max_attempts_per_story: Optional[int] = None,
    target_story_id: Optional[str] = None,
    force: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Priority-aware story selection.
    
    Selection priority (highest to lowest):
    1. Status: todo > in_progress > fail (skip pass unless force=True)
    2. Priority: P1 > P2 > P3 > P4 > P5
    3. ID: US1 > US2 > US3 (numeric part)
    4. Attempts: Lower attempts preferred (for same priority/status)
    
    Args:
        prd: PRD dictionary with stories array
        max_attempts_per_story: Maximum attempts before marking as exhausted
        target_story_id: If provided, return this story if eligible
        force: If True, include stories with status="pass"
    
    Returns:
        Selected story dict or None if no eligible story found
    """
    stories = prd.get("stories", [])
    if not stories:
        return None
    
    # If target_story_id specified, find and return it if eligible
    if target_story_id:
        for story in stories:
            if story.get("id") == target_story_id:
                # Check if eligible
                status = story.get("status", "todo")
                if status == "pass" and not force:
                    logger.warning(f"Story {target_story_id} has status 'pass'. Use --force to retry.")
                    return None
                
                attempts = story.get("attempts", 0)
                max_attempts = story.get("max_attempts") or max_attempts_per_story
                if max_attempts and attempts >= max_attempts:
                    logger.warning(f"Story {target_story_id} has reached max attempts ({max_attempts})")
                    return None
                
                return story
        logger.warning(f"Story {target_story_id} not found in PRD")
        return None
    
    # Filter eligible stories
    eligible = []
    for story in stories:
        status = story.get("status", "todo")
        
        # Skip pass unless force
        if status == "pass" and not force:
            continue
        
        # Check max attempts
        attempts = story.get("attempts", 0)
        max_attempts = story.get("max_attempts") or max_attempts_per_story
        if max_attempts and attempts >= max_attempts:
            continue
        
        eligible.append(story)
    
    if not eligible:
        return None
    
    # Sort by selection priority
    def sort_key(story):
        status = story.get("status", "todo")
        priority = story.get("priority", "P9")
        story_id = story.get("id", "")
        attempts = story.get("attempts", 0)
        
        # Status priority: todo=0, in_progress=1, fail=2, pass=3
        status_priority = {"todo": 0, "in_progress": 1, "fail": 2, "pass": 3}.get(status, 99)
        
        # Priority number: P1=1, P2=2, etc.
        priority_num = int(priority[1:]) if priority.startswith("P") and priority[1:].isdigit() else 99
        
        # Extract numeric part from ID (US1 -> 1, US2 -> 2)
        id_match = re.match(r"US(\d+)", story_id)
        id_num = int(id_match.group(1)) if id_match else 9999
        
        return (status_priority, priority_num, id_num, attempts)
    
    eligible.sort(key=sort_key)
    selected = eligible[0]
    
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            f"Selected story {selected['id']} (status={selected.get('status')}, "
            f"priority={selected.get('priority')}, attempts={selected.get('attempts', 0)})"
        )
    
    return selected

def build_story_context(story: Dict[str, Any], prd: Dict[str, Any], model_name: Optional[str] = None, verbose: bool = False) -> str:
    """
    Constructs rich context string from story + PRD context.
    Combines story description, acceptance_criteria, independent_test
    and prepends PRD context.full_concatenation for full spec context.
    
    Args:
        story: Story dictionary from PRD
        prd: Full PRD dictionary
        model_name: Model name for context limiting (optional)
        verbose: Whether to log context details
    
    Returns:
        Formatted context string for agents (limited to model's context length if model_name provided)
    """
    context_parts = []
    
    # Add story-specific context FIRST (most important)
    context_parts.append("=== CURRENT USER STORY ===\n")
    context_parts.append(f"Story ID: {story.get('id', 'N/A')}\n")
    context_parts.append(f"Title: {story.get('title', 'N/A')}\n")
    context_parts.append(f"Priority: {story.get('priority', 'N/A')}\n")
    context_parts.append(f"\nDescription:\n{story.get('description', 'N/A')}\n")
    
    # Add acceptance criteria
    acceptance_criteria = story.get("acceptance_criteria", [])
    if acceptance_criteria:
        context_parts.append("\nAcceptance Criteria:\n")
        for ac in acceptance_criteria:
            context_parts.append(f"- {ac}\n")
    
    # Add independent test
    independent_test = story.get("independent_test", "")
    if independent_test:
        context_parts.append(f"\nIndependent Test:\n{independent_test}\n")
    
    # Add linked tasks (for reference)
    tasks = story.get("tasks", [])
    if tasks:
        context_parts.append(f"\nLinked Implementation Tasks: {', '.join(tasks)}\n")
    else:
        context_parts.append("\n(No linked tasks - story context only)\n")
    
    # Add PRD full context AFTER story (less critical, can be truncated)
    prd_context = prd.get("context", {})
    full_concatenation = prd_context.get("full_concatenation", "")
    if full_concatenation:
        context_parts.append("\n=== FULL SPECIFICATION CONTEXT ===\n")
        context_parts.append(full_concatenation)
        context_parts.append("\n")
    
    full_context = "".join(context_parts)
    
    # Limit context if model_name provided
    if model_name:
        from .context_manager import limit_context_for_model
        full_context = limit_context_for_model(
            full_context,
            model_name,
            reserve_tokens=2000,  # Reserve for prompt + response
            verbose=verbose
        )
    
    return full_context

def update_story_after_attempt(
    story: Dict[str, Any],
    result: Dict[str, Any],
    max_attempts: Optional[int] = None
) -> None:
    """
    Updates story state based on implementation result.
    Sets status (pass/in_progress/fail), increments attempts,
    sets last_error (or clears it on success), sets last_updated_at timestamp.
    Marks as fail if max_attempts exceeded.
    """
    story["attempts"] = story.get("attempts", 0) + 1
    story["last_updated_at"] = datetime.now(UTC).isoformat() + "Z"
    
    # Check if successful
    if result.get("decision") == "SHIP" and result.get("tests_ok", False):
        story["status"] = "pass"
        story["last_error"] = None
        logger.info(f"Story {story.get('id')} PASSED (attempt {story['attempts']})")
    else:
        # Determine error message
        error_msg = result.get("error")
        if not error_msg:
            if result.get("decision") != "SHIP":
                decision = result.get("decision", "UNKNOWN")
                critic_reason = result.get("critic_reason")
                if critic_reason:
                    error_msg = f"Agent decision: {decision} - {critic_reason}"
                else:
                    error_msg = f"Agent decision: {decision}"
            elif not result.get("tests_ok", True):
                error_msg = "Tests failed"
            else:
                error_msg = "Unknown error"
        
        story["last_error"] = error_msg
        
        # Check if max attempts reached
        if max_attempts and story["attempts"] >= max_attempts:
            story["status"] = "fail"
            logger.warning(
                f"Story {story.get('id')} reached max attempts ({max_attempts}), "
                f"marking as fail. Last error: {error_msg}"
            )
        else:
            story["status"] = "in_progress"
            logger.info(
                f"Story {story.get('id')} needs revision (attempt {story['attempts']}). "
                f"Error: {error_msg}"
            )

def print_iteration_summary(iteration_result: Dict[str, Any], story: Dict[str, Any]) -> None:
    """
    Print clear summary of iteration result.
    Shows story status, attempts, decision, test results, and next steps.
    """
    print("\n" + "=" * 80)
    print("ITERATION SUMMARY")
    print("=" * 80)
    print(f"Story: {story.get('id')} - {story.get('title', 'N/A')}")
    print(f"Status: {story.get('status', 'unknown')}")
    print(f"Attempts: {story.get('attempts', 0)}")
    
    result = iteration_result.get('result', {})
    decision = result.get('decision', 'UNKNOWN')
    tests_ok = result.get('tests_ok', False)
    
    print(f"\nDecision: {decision}")
    print(f"Tests: {'PASSED' if tests_ok else 'FAILED'}")
    
    if story.get('last_error'):
        print(f"\nError: {story['last_error']}")
    
    status = story.get('status')
    if status == 'pass':
        print("\n✅ Story PASSED - Ready to proceed to next story")
    elif status == 'fail':
        print("\n❌ Story FAILED - Max attempts reached")
    elif status == 'in_progress':
        print("\n⚠️  Story needs revision - Will retry on next iteration")
    else:
        print(f"\n📝 Story status: {status}")
    print("=" * 80 + "\n")

def run_ralph_iteration(
    repo_root: Path,
    prd: Dict[str, Any],
    prd_path: Path,
    story: Dict[str, Any],
    use_agents: bool,
    auto_commit: bool,
    skip_tests: bool,
    verbose: bool,
    max_attempts_per_story: Optional[int] = None
) -> Dict[str, Any]:
    """
    Executes single iteration for one story.
    Updates story to in_progress, saves PRD, builds story context,
    calls run_once(), updates story state based on result, saves PRD.
    
    Returns iteration result dict.
    """
    feature_id = prd.get("feature_id", "unknown")
    story_id = story.get("id", "unknown")
    
    # Update story to in_progress and increment attempts
    story["status"] = "in_progress"
    story["attempts"] = story.get("attempts", 0) + 1
    story["last_updated_at"] = datetime.now(UTC).isoformat() + "Z"
    
    # Save PRD state before execution
    _save_prd(prd_path, prd)
    logger.info(f"Story {story_id} marked as in_progress (attempt {story['attempts']})")
    
    # Build story context (with model-aware limiting)
    # Get model name from config for context limiting
    try:
        from .config import load_config
        config = load_config(repo_root)
        coder_model = config.models.get("coder", "ollama/qwen2.5-coder:14b")
    except Exception:
        coder_model = None
    
    story_context = build_story_context(story, prd, model_name=coder_model, verbose=verbose)
    
    # Check if story has no linked tasks (informational)
    tasks = story.get("tasks", [])
    if not tasks:
        logger.info(f"Story {story_id} has no linked tasks, proceeding with story context only")
    
    # Construct task name
    task_name = f"{feature_id}-{story_id}-{story.get('title', 'story')}"
    # Sanitize task name for branch creation
    task_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_name)
    
    if verbose:
        logger.debug(f"Task name: {task_name}")
        logger.debug(f"Story context length: {len(story_context)} characters")
    
    # Execute run_once with story context
    try:
        result = run_once(
            task_name=task_name,
            repo_root=repo_root,
            use_agents=use_agents,
            auto_commit=auto_commit,
            prompt=None,  # Let agents generate prompt from context
            skip_tests=skip_tests,
            verbose=verbose,
            story_context=story_context,  # Pass story context
            feature_id=feature_id,  # Pass feature_id for filtering
        )
    except Exception as e:
        logger.error(f"Exception during run_once for story {story_id}: {e}", exc_info=verbose)
        result = {
            "decision": "ERROR",
            "tests_ok": False,
            "error": f"Exception: {str(e)}"
        }
    
    # Update story state based on result
    max_attempts = story.get("max_attempts") or max_attempts_per_story
    update_story_after_attempt(story, result, max_attempts)
    
    # Save PRD state after execution
    try:
        _save_prd(prd_path, prd)
    except Exception as e:
        logger.error(f"Failed to save PRD after iteration: {e}")
        # Continue anyway - state is in memory
    
    # Build iteration result
    iteration_result = {
        "story_id": story_id,
        "story_title": story.get("title"),
        "attempt": story["attempts"],
        "result": result,
        "status": story["status"]
    }
    
    # Print summary
    print_iteration_summary(iteration_result, story)
    
    return iteration_result

def run_ralph_loop(
    repo_root: Path,
    feature_id: str,
    mode: str = "loop",
    max_iterations: Optional[int] = None,
    max_attempts_per_story: Optional[int] = None,
    target_story_id: Optional[str] = None,
    auto_commit: bool = False,
    skip_tests: bool = False,
    use_agents: bool = True,
    verbose: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Executes the Ralph-style autonomous loop.
    
    Args:
        repo_root: Repository root path
        feature_id: Feature identifier (e.g., "001-event-notifications")
        mode: Execution mode - "once" for single iteration, "loop" for full loop
        max_iterations: Maximum loop iterations (None = no limit)
        max_attempts_per_story: Maximum attempts per story before marking as fail
        target_story_id: Target specific story (e.g., "US1")
        auto_commit: Automatically commit when SHIP + tests_ok
        skip_tests: Skip running tests
        use_agents: Use CrewAI agents for planning/review
        verbose: Enable verbose logging
        force: Retry stories with status="pass"
    
    Returns:
        Summary dict with feature_id, iterations, stories_total, stories_pass, stories_fail
    """
    # Load config and PRD (do NOT generate - user must run generator separately)
    try:
        config = load_config(repo_root)
        specs_dir = config.spec_kit.get("specs_dir", "specs") if config.spec_kit else "specs"
        
        logger.info(f"Loading PRD for feature '{feature_id}'...")
        prd = load_prd(repo_root, feature_id, specs_dir=specs_dir)
        
        feature_dir = repo_root / specs_dir / feature_id
        prd_path = feature_dir / "prd.json"
        
    except Exception as e:
        logger.error(f"Failed to initialize Ralph loop: {e}")
        return {
            "feature_id": feature_id,
            "error": str(e),
            "stories_total": 0,
            "stories_pass": 0,
            "stories_fail": 0,
            "iterations": 0
        }
    
    if "ralph_metadata" not in prd:
        prd["ralph_metadata"] = {}
    prd["ralph_metadata"]["last_run_at"] = datetime.now(UTC).isoformat() + "Z"
    prd["ralph_metadata"]["last_run_mode"] = mode
    prd["ralph_metadata"]["total_iterations"] = prd["ralph_metadata"].get("total_iterations", 0)
    
    iterations = 0
    
    while True:
        # Check iteration limit
        if max_iterations is not None and iterations >= max_iterations:
            logger.info(f"Reached maximum iterations ({max_iterations}). Stopping.")
            break
        
        # Select next story
        story = select_next_story(
            prd,
            max_attempts_per_story=max_attempts_per_story,
            target_story_id=target_story_id,
            force=force
        )
        
        if story is None:
            logger.info("No eligible stories found. Loop complete.")
            break
        
        logger.info(f"--- Iteration {iterations + 1} ---")
        logger.info(f"Selected story: {story['id']} - {story.get('title', 'N/A')}")
        
        # Execute iteration
        iteration_result = run_ralph_iteration(
            repo_root=repo_root,
            prd=prd,
            prd_path=prd_path,
            story=story,
            use_agents=use_agents,
            auto_commit=auto_commit,
            skip_tests=skip_tests,
            verbose=verbose,
            max_attempts_per_story=max_attempts_per_story
        )
        
        iterations += 1
        prd["ralph_metadata"]["total_iterations"] = iterations
        
        # If single iteration mode, exit after one iteration
        if mode == "once":
            logger.info("Single iteration mode - exiting after one iteration")
            break
        
        # Basic sleep to prevent tight loops
        time.sleep(1)
    
    # Calculate summary
    stories = prd.get("stories", [])
    summary = {
        "feature_id": feature_id,
        "iterations": iterations,
        "stories_total": len(stories),
        "stories_pass": sum(1 for s in stories if s.get("status") == "pass"),
        "stories_fail": sum(1 for s in stories if s.get("status") == "fail"),
        "stories_todo": sum(1 for s in stories if s.get("status") == "todo"),
        "stories_in_progress": sum(1 for s in stories if s.get("status") == "in_progress"),
    }
    
    # Final save of PRD with updated metadata
    try:
        _save_prd(prd_path, prd)
    except Exception as e:
        logger.error(f"Failed to save PRD at end of loop: {e}")
    
    return summary

def main():
    parser = argparse.ArgumentParser(description="AI Refactor - Ralph-style autonomous loop")
    parser.add_argument(
        "--feature-id",
        required=True,
        help="Spec Kit feature id (e.g. 001-ui-theme)",
    )
    parser.add_argument(
        "--mode",
        choices=["once", "loop"],
        default="once",
        help="Execution mode: 'once' for single iteration, 'loop' for full loop (default: once)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        help="Maximum number of loop iterations (optional)",
    )
    parser.add_argument(
        "--max-attempts-per-story",
        type=int,
        help="Maximum attempts per story before marking as fail (optional)",
    )
    parser.add_argument(
        "--story-id",
        help="Target specific story (e.g. US1) - only works in 'once' mode",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Retry stories with status='pass'",
    )
    parser.add_argument(
        "--auto-commit",
        action="store_true",
        help="Automatically commit when SHIP + tests_ok",
    )
    parser.add_argument(
        "--no-tests",
        action="store_true",
        help="Skip running tests in each iteration",
    )
    parser.add_argument(
        "--no-agents",
        action="store_true",
        help="Disable Coder/Critic agents and just run Aider",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.story_id and args.mode == "loop":
        print("Error: --story-id can only be used with --mode once")
        sys.exit(1)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    try:
        repo_root = get_repo_root()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    logger.info(f"Starting Ralph Loop for feature: {args.feature_id} (mode: {args.mode})")

    result = run_ralph_loop(
        repo_root=repo_root,
        feature_id=args.feature_id,
        mode=args.mode,
        max_iterations=args.max_iterations,
        max_attempts_per_story=args.max_attempts_per_story,
        target_story_id=args.story_id,
        auto_commit=args.auto_commit,
        skip_tests=args.no_tests,
        use_agents=not args.no_agents,
        verbose=args.verbose,
        force=args.force,
    )

    print("\n" + "=" * 80)
    print("RALPH LOOP SUMMARY")
    print("=" * 80)
    print(f"Feature: {result['feature_id']}")
    print(f"Mode: {args.mode}")
    print(f"Iterations executed: {result['iterations']}")
    print(f"\nStories Status:")
    print(f"  Total:    {result['stories_total']}")
    print(f"  ✅ Pass:  {result['stories_pass']}")
    print(f"  ❌ Fail:  {result['stories_fail']}")
    if 'stories_todo' in result:
        print(f"  📝 Todo:  {result['stories_todo']}")
    if 'stories_in_progress' in result:
        print(f"  🔄 In Progress: {result['stories_in_progress']}")
    
    if result.get("error"):
        print(f"\n⚠️  Error: {result['error']}")
    
    # Final status message
    if result["stories_fail"] > 0:
        print("\n❌ Some stories failed. Check PRD for details.")
    elif result["stories_pass"] == result["stories_total"] and result["stories_total"] > 0:
        print("\n✅ All stories passed! Feature complete.")
    elif result.get('stories_todo', 0) > 0 or result.get('stories_in_progress', 0) > 0:
        print("\n⚠️  Some stories still pending. Run again to continue.")
    print("=" * 80)

    if result["stories_fail"] > 0:
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
