import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from .config import load_config
from .git_utils import (
    get_repo_root, 
    ensure_clean_worktree, 
    create_task_branch, 
    get_diff, 
    commit_changes, 
    push_branch
)
from .aider_bridge import run_aider
from .crew_agents import coder_plan, critic_review
from .spec_loader import load_specs

def run_tests(test_command: str, cwd: Path) -> tuple[bool, str]:
    if not test_command:
        return True, "No tests configured."
    
    print(f"Running tests: {test_command}")
    try:
        # Using shell=True for complex commands like "python -m unittest ..."
        result = subprocess.run(
            test_command, 
            shell=True,
            cwd=cwd, 
            capture_output=True, 
            text=True
        )
        return result.returncode == 0, result.stdout + "\n" + result.stderr
    except Exception as e:
        return False, str(e)

def run_once(
    task_name: str, 
    repo_root: Path,
    use_agents: bool = True, 
    auto_commit: bool = False,
    prompt: Optional[str] = None
) -> Dict[str, Any]:
    
    config = load_config(repo_root)
    
    # Load Spec Kit context if enabled
    spec_context = ""
    if config.spec_kit and config.spec_kit.get("enabled", False):
        specs_dir = config.spec_kit.get("specs_dir", "specs")
        print(f"Loading Spec Kit data from {specs_dir}...")
        spec_context = load_specs(repo_root, specs_dir)
        if spec_context:
            print("Spec Kit context loaded.")
    
    # 1. Plan (CrewAI) -> Prompt & Files
    aider_prompt = prompt
    target_files = []
    
    if use_agents and not prompt:
        # Gather context
        # In a real scenario, we might read some file structure or use 'ls' but for now we pass a list of files
        # A simple recursive glob for context
        all_files = [str(f.relative_to(repo_root)) for f in repo_root.rglob("*") if f.is_file() and not any(part.startswith('.') for part in f.parts)]
        
        # Check presets
        if task_name in config.task_presets:
            preset = config.task_presets[task_name]
            aider_prompt = preset.get("prompt")
            # Might use files_hint logic here to filter files
        
        if not aider_prompt:
            # Generate plan
            print("Generating plan with Coder Agent...")
            coder_model = config.models.get("coder", "ollama/qwen2.5-coder:14b")
            aider_prompt, target_files = coder_plan(task_name, "User requested refactor.", all_files, spec_context, coder_model)
    
    if not aider_prompt:
        aider_prompt = task_name # Fallback if agent failed or no prompt provided
        
    # 2. Code (Aider)
    print(f"Starting Aider with prompt: {aider_prompt}")
    run_aider(aider_prompt, repo_root, target_files)
    
    # 3. Test
    print("Running tests...")
    tests_ok, test_log = run_tests(config.tests, repo_root)
    
    # 4. Review (CrewAI)
    diff = get_diff(repo_root)
    if not diff:
        print("No changes detected.")
        return {"decision": "NO_CHANGES", "tests_ok": tests_ok}
    
    decision = "SHIP"
    if use_agents:
        print("Reviewing changes with Critic Agent...")
        planner_model = config.models.get("planner", "ollama/llama3.1:8b")
        decision = critic_review(diff, test_log, task_name, planner_model)
    
    # 5. Commit/Push
    if decision == "SHIP" and tests_ok:
        if auto_commit:
            print("Auto-committing changes...")
            commit_changes(repo_root, f"refactor: {task_name}")
            # push_branch(repo_root) # Make push optional/manual usually safer
    
    return {
        "tests_ok": tests_ok,
        "decision": decision,
        "diff_size": len(diff),
        "test_log_head": test_log[:500] if test_log else ""
    }
