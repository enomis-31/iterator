import argparse
import sys
import logging
from pathlib import Path
from .workflow import run_once
from .git_utils import get_repo_root, create_task_branch, ensure_clean_worktree
from .config import load_config

def main():
    parser = argparse.ArgumentParser(description="AI Refactor CLI")
    parser.add_argument("task_name", help="Name of the refactoring task")
    parser.add_argument("--prompt", help="Specific prompt to use (overrides presets)")
    parser.add_argument("--no-branch", action="store_true", help="Do not create a new branch")
    parser.add_argument("--no-agents", action="store_true", help="Skip CrewAI planning/review, just run Aider")
    parser.add_argument("--no-tests", action="store_true", help="Skip running tests")
    parser.add_argument("--auto-commit", action="store_true", help="Automatically commit if successful")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging (DEBUG level)")
    
    args = parser.parse_args()
    
    # Configure logging based on verbosity
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='%(message)s')
        # Suppress verbose logs from third-party libraries
        logging.getLogger("crewai").setLevel(logging.WARNING)
        logging.getLogger("litellm").setLevel(logging.ERROR)
    
    try:
        repo_root = get_repo_root()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
        
    config = load_config(repo_root)
    print(f"Detected language: {config.language}, Tests: {config.tests}")
    
    # Branching
    if not args.no_branch:
        try:
            ensure_clean_worktree(repo_root)
            create_task_branch(args.task_name, config.branch_prefix, repo_root)
        except RuntimeError as e:
            print(f"Error: {e}")
            sys.exit(1)
            
    # Run Workflow
    result = run_once(
        task_name=args.task_name,
        repo_root=repo_root,
        use_agents=not args.no_agents,
        auto_commit=args.auto_commit,
        prompt=args.prompt,
        skip_tests=args.no_tests,
        verbose=args.verbose
    )
    
    print("\n--- Summary ---")
    print(f"Decision: {result['decision']}")
    print(f"Tests Passed: {result['tests_ok']}")
    
    # Check for errors
    if result.get('error'):
        print(f"Error: {result['error']}")
        sys.exit(1)
    
    if result['decision'] == "SHIP" and result['tests_ok']:
        print("Ready to merge! You can create a PR now.")
    elif result['decision'] == "ERROR":
        print("Workflow failed. Check errors above.")
        sys.exit(1)
    else:
        print("Needs revision. Check log and diff.")

if __name__ == "__main__":
    main()
