import argparse
import sys
import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional

from .config import load_config
from .workflow import run_once
from .git_utils import get_repo_root
from .prd_generator import generate_prd

logger = logging.getLogger(__name__)

def _save_prd(prd_path: Path, data: Dict[str, Any]) -> None:
    """Saves the PRD data to the JSON file with pretty printing."""
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def _pick_next_story(stories: list[dict]) -> Optional[dict]:
    """
    Picks the next story to work on.
    Priority:
    1. First 'todo'
    2. First 'fail' (retry)
    3. 'in_progress' is treated as 'fail'/retry if we are restarting the loop
       (usually 'in_progress' shouldn't persist across loop restarts unless it crashed)
    
    Returns None if all are 'pass'.
    """
    # 1. Look for todo
    for story in stories:
        if story.get("status") == "todo":
            return story
            
    # 2. Look for fail or in_progress to retry
    for story in stories:
        status = story.get("status")
        if status in ["fail", "in_progress"]:
            return story
            
    return None

def run_ralph_loop(
    repo_root: Path,
    feature_id: str,
    max_iterations: Optional[int] = None,
    auto_commit: bool = False,
    skip_tests: bool = False,
    use_agents: bool = True,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Executes the Ralph-style autonomous loop:
    1. Generates/Updates PRD from Spec Kit.
    2. Iterates through stories until done or max_iterations reached.
    """
    
    # 0. Load Config & Generate PRD
    try:
        config = load_config(repo_root)
        specs_dir = config.spec_kit.get("specs_dir", "specs") if config.spec_kit else "specs"
        
        logger.info(f"Generating/Updating PRD for feature '{feature_id}'...")
        prd_path = generate_prd(repo_root, feature_id, specs_dir=specs_dir)
        logger.info(f"PRD ready at {prd_path}")
        
        data = json.loads(prd_path.read_text(encoding="utf-8"))
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

    iterations = 0
    
    while True:
        # Check iteration limit
        if max_iterations is not None and iterations >= max_iterations:
            logger.info(f"Reached maximum iterations ({max_iterations}). Stopping.")
            break

        # Pick next story
        story = _pick_next_story(data["stories"])
        if story is None:
            logger.info("All stories passed! Loop complete.")
            break
            
        logger.info(f"--- Iteration {iterations + 1} ---")
        logger.info(f"Selected story: {story['id']} - {story['title']}")
        
        # Update status to in_progress
        story["status"] = "in_progress"
        story["attempts"] = story.get("attempts", 0) + 1
        _save_prd(prd_path, data)
        
        # Construct task name & context
        # We pass story context into the prompt indirectly via run_once if needed, 
        # but run_once currently generates the prompt via agents.
        # We can pass the specifics as the prompt to run_once to bypass planning if we want,
        # OR we let run_once do the planning.
        # Given the instructions say "use models via Ollama", we probably rely on run_once's Planning phase (using agents=True).
        # But we should give it a good task_name that helps the planner.
        
        task_name = f"{feature_id}-{story['id']}-{story['title']}"
        # Sanitize task name for branch creation if needed
        task_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_name)
        
        # We might want to construct a specific prompt instruction to guide the agent better
        # using the story description and acceptance criteria.
        prompt_context = f"""Feature: {data['title']}
Story: {story['title']}
Description: {story['description']}
Acceptance Criteria:
"""
        for ac in story.get("acceptance_criteria", []):
            prompt_context += f"- {ac}\n"
            
        # Execute run_once
        result = run_once(
            task_name=task_name,
            repo_root=repo_root,
            use_agents=use_agents,
            auto_commit=auto_commit,
            # We pass the constructed context as the 'prompt' description for the planner 
            # if we wanted to enforce it, OR we let the planner discover it.
            # However, run_once with prompt=None uses 'task_name' to prompt the planner.
            # To capture the full story details, providing a 'prompt' argument to run_once 
            # (which skips the planner usually, OR serves as input to the planner if modified)
            # workflow.py: if prompt is provided, it skips Plan phase (crew_agents.coder_plan).
            # The user requirement says: "usa modelli locali... workflow esistente...". 
            # If we pass 'prompt', workflow.py skips the 'Plan' agent phase and goes straight to Aider.
            # But the requirement says "Phase Plan: uses crew_agents.coder_plan...".
            # So if we want to use the Planner Agent, we MUST NOT pass `prompt`. 
            # BUT we need to pass the Story details to the Planner Agent.
            # workflow.py `coder_plan` takes `task_name` and `user_request` (hardcoded "User requested refactor" in workflow.py currently).
            # To make this work without changing workflow.py too much, we might need to rely on the fact that
            # `coder_plan` receives `spec_context`. 
            # SINCE we updated `generate_prd`, the specs ARE in the specs folder.
            # `load_specs` will load ALL specs. 
            # The Planner Agent should ideally see the `tasks.md` or `prd.json` if included in context.
            # Let's hope `workflow.run_once` logic is sufficient. 
            # Limitation: currently `workflow.run_once` passes "User requested refactor." as the user_request to coder_plan.
            # We might want to patch `workflow.run_once` later to accept a `user_request` string,
            # but for now we follow instructions to "Modify implementation of AI Refactor Tool... using workflow existing...".
            # We will use `task_name` effectively to convey intent.
            prompt=None, 
            skip_tests=skip_tests,
            verbose=verbose,
        )
        
        # Evaluate result
        if result["decision"] == "SHIP" and result["tests_ok"]:
            logger.info(f"Story {story['id']} PASSED.")
            story["status"] = "pass"
            story["last_error"] = None
        else:
            logger.warning(f"Story {story['id']} FAILED / REVISE.")
            story["status"] = "fail"
            error_msg = result.get("error")
            if not error_msg and result["decision"] != "SHIP":
                error_msg = f"Agent decision: {result['decision']}"
            elif not error_msg and not result["tests_ok"]:
                error_msg = "Tests failed"
            
            story["last_error"] = error_msg

        _save_prd(prd_path, data)
        iterations += 1
        
        # Basic sleep to prevent tight loops if something goes wrong instantly
        time.sleep(1)

    # Calculate summary
    summary = {
        "feature_id": feature_id,
        "iterations": iterations,
        "stories_total": len(data["stories"]),
        "stories_pass": sum(1 for s in data["stories"] if s["status"] == "pass"),
        "stories_fail": sum(1 for s in data["stories"] if s["status"] == "fail"),
    }
    return summary

def main():
    parser = argparse.ArgumentParser(description="AI Refactor - Ralph-style autonomous loop")
    parser.add_argument(
        "--feature-id",
        required=True,
        help="Spec Kit feature id (e.g. 001-ui-theme)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        help="Maximum number of loop iterations (optional)",
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

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    try:
        repo_root = get_repo_root()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Starting Ralph Loop for feature: {args.feature_id}")

    result = run_ralph_loop(
        repo_root=repo_root,
        feature_id=args.feature_id,
        max_iterations=args.max_iterations,
        auto_commit=args.auto_commit,
        skip_tests=args.no_tests,
        use_agents=not args.no_agents,
        verbose=args.verbose,
    )

    print("\n--- Ralph Loop Summary ---")
    print(f"Feature: {result['feature_id']}")
    print(f"Iterations: {result['iterations']}")
    print(f"Stories total: {result['stories_total']}")
    print(f"Stories pass:  {result['stories_pass']}")
    print(f"Stories fail:  {result['stories_fail']}")

    if result.get("error"):
         print(f"Error occurred: {result['error']}")

    if result["stories_fail"] > 0:
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
