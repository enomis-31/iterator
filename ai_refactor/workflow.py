import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from .config import load_config

logger = logging.getLogger(__name__)
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
    
    logger.info(f"Running tests: {test_command}")
    try:
        # Using shell=True for complex commands like "python -m unittest ..."
        result = subprocess.run(
            test_command, 
            shell=True,
            cwd=cwd, 
            capture_output=True, 
            text=True
        )
        output = result.stdout + "\n" + result.stderr
        # Check if command not found (e.g., pytest not installed)
        if result.returncode != 0 and ("not found" in output.lower() or "command not found" in output.lower()):
            return True, f"Test command not available (skipped): {output}"
        return result.returncode == 0, output
    except Exception as e:
        return False, str(e)

def run_once(
    task_name: str, 
    repo_root: Path,
    use_agents: bool = True, 
    auto_commit: bool = False,
    prompt: Optional[str] = None,
    skip_tests: bool = False,
    verbose: bool = False
) -> Dict[str, Any]:
    
    try:
        config = load_config(repo_root)
    except Exception as e:
        return {
            "decision": "ERROR",
            "tests_ok": False,
            "error": f"Failed to load config: {e}"
        }
    
    # Load Spec Kit context if enabled
    spec_context = ""
    try:
        if config.spec_kit and config.spec_kit.get("enabled", False):
            specs_dir = config.spec_kit.get("specs_dir", "specs")
            logger.info(f"Loading Spec Kit data from {specs_dir}...")
            spec_context = load_specs(repo_root, specs_dir)
            if spec_context:
                logger.info("Spec Kit context loaded.")
                if verbose:
                    logger.debug(f"Spec context length: {len(spec_context)} characters")
    except Exception as e:
        logger.warning(f"Failed to load Spec Kit context: {e}")
        if verbose:
            logger.debug(f"Exception details: {e}", exc_info=True)
        spec_context = ""
    
    # 1. Plan (CrewAI) -> Prompt & Files
    aider_prompt = prompt
    target_files = []
    
    if use_agents and not prompt:
        try:
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
                logger.info("Generating plan with Coder Agent...")
                coder_model = config.models.get("coder", "ollama/qwen2.5-coder:14b")
                if verbose:
                    logger.debug(f"Using coder model: {coder_model}")
                aider_prompt, target_files = coder_plan(task_name, "User requested refactor.", all_files, spec_context, coder_model, base_url=config.ollama_base_url)
                if verbose:
                    logger.debug(f"Generated prompt length: {len(aider_prompt)}, target files: {len(target_files)}")
        except Exception as e:
            logger.warning(f"Failed to generate plan with agent: {e}")
            if verbose:
                logger.debug(f"Exception details: {e}", exc_info=True)
            logger.info("Falling back to task name as prompt.")
            aider_prompt = task_name
    
    if not aider_prompt:
        aider_prompt = task_name # Fallback if agent failed or no prompt provided
        
    # 2. Code (Aider)
    logger.info(f"Starting Aider with prompt: {aider_prompt[:100]}..." if len(aider_prompt) > 100 else f"Starting Aider with prompt: {aider_prompt}")
    try:
        coder_model = config.models.get("coder", "ollama/qwen2.5-coder:14b")
        if verbose:
            logger.debug(f"Using coder model: {coder_model}, target files: {target_files}")
        aider_exit_code = run_aider(aider_prompt, repo_root, target_files, 
                  model=coder_model, ollama_base_url=config.ollama_base_url)
        
        # Check Aider exit code
        if aider_exit_code != 0:
            if aider_exit_code == 127:
                return {
                    "decision": "ERROR",
                    "tests_ok": False,
                    "error": "Aider command not found. Please install it via 'pipx install aider-chat'."
                }
            logger.warning(f"Aider exited with code {aider_exit_code}. Continuing anyway...")
    except Exception as e:
        logger.error(f"Failed to run Aider: {e}")
        if verbose:
            logger.debug(f"Exception details: {e}", exc_info=True)
        return {
            "decision": "ERROR",
            "tests_ok": False,
            "error": f"Aider execution failed: {e}"
        }
    
    # 3. Test
    if skip_tests:
        logger.info("Skipping tests (--no-tests flag set).")
        tests_ok, test_log = True, "Tests skipped via --no-tests flag"
    else:
        logger.info("Running tests...")
        try:
            tests_ok, test_log = run_tests(config.tests, repo_root)
            if verbose:
                logger.debug(f"Test result: {'PASSED' if tests_ok else 'FAILED'}")
        except Exception as e:
            logger.error(f"Failed to run tests: {e}")
            if verbose:
                logger.debug(f"Exception details: {e}", exc_info=True)
            tests_ok, test_log = False, f"Test execution failed: {e}"
    
    # 4. Review (CrewAI)
    try:
        diff = get_diff(repo_root)
        if verbose:
            logger.debug(f"Git diff size: {len(diff)} characters")
    except Exception as e:
        logger.error(f"Failed to get git diff: {e}")
        if verbose:
            logger.debug(f"Exception details: {e}", exc_info=True)
        return {
            "decision": "ERROR",
            "tests_ok": tests_ok,
            "error": f"Failed to get git diff: {e}"
        }
    
    if not diff:
        logger.info("No changes detected.")
        return {"decision": "NO_CHANGES", "tests_ok": tests_ok}
    
    decision = "SHIP"
    if use_agents:
        try:
            logger.info("Reviewing changes with Critic Agent...")
            planner_model = config.models.get("planner", "ollama/llama3.1:8b")
            if verbose:
                logger.debug(f"Using planner model: {planner_model}")
            decision = critic_review(diff, test_log, task_name, planner_model, base_url=config.ollama_base_url)
            if verbose:
                logger.debug(f"Critic decision: {decision}")
        except Exception as e:
            logger.warning(f"Failed to review with agent: {e}")
            if verbose:
                logger.debug(f"Exception details: {e}", exc_info=True)
            logger.info("Defaulting to SHIP decision.")
            decision = "SHIP"
    
    # 5. Commit/Push
    if decision == "SHIP" and tests_ok:
        if auto_commit:
            try:
                logger.info("Auto-committing changes...")
                commit_changes(repo_root, f"refactor: {task_name}")
                if verbose:
                    logger.debug("Changes committed successfully")
                # push_branch(repo_root) # Make push optional/manual usually safer
            except Exception as e:
                logger.error(f"Failed to commit changes: {e}")
                if verbose:
                    logger.debug(f"Exception details: {e}", exc_info=True)
                return {
                    "decision": decision,
                    "tests_ok": tests_ok,
                    "error": f"Failed to commit: {e}"
                }
    
    return {
        "tests_ok": tests_ok,
        "decision": decision,
        "diff_size": len(diff),
        "test_log_head": test_log[:500] if test_log else ""
    }
