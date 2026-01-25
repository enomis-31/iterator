import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from .config import load_config

logger = logging.getLogger(__name__)

class LiteLLMFilter(logging.Filter):
    """Filter to suppress non-critical LiteLLM errors (e.g., fastapi dependency)"""
    def filter(self, record):
        msg = record.getMessage().lower()
        # Filter non-critical errors about fastapi dependency
        if "fastapi" in msg or ("missing dependency" in msg and "fastapi" in msg):
            return False
        return True
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

def log_phase(phase_name: str, verbose: bool = False):
    """Print visual separator for workflow phase"""
    if verbose:
        logger.info("=" * 80)
        logger.info(f"PHASE: {phase_name}")
        logger.info("=" * 80)
    else:
        logger.debug(f"PHASE: {phase_name}")

def enhance_spec_context_with_story(spec_context: str, story_context: str) -> str:
    """
    Prepends story-specific context to existing spec context.
    Formats story context as a clear section.
    Returns combined context string.
    """
    if not story_context:
        return spec_context
    
    # Format story context as a clear section at the beginning
    enhanced = "=== STORY-SPECIFIC CONTEXT ===\n"
    enhanced += story_context
    enhanced += "\n\n=== GENERAL SPECIFICATION CONTEXT ===\n"
    enhanced += spec_context if spec_context else "(No general spec context available)"
    
    return enhanced

def run_once(
    task_name: str, 
    repo_root: Path,
    use_agents: bool = True, 
    auto_commit: bool = False,
    prompt: Optional[str] = None,
    skip_tests: bool = False,
    verbose: bool = False,
    story_context: Optional[str] = None,
    feature_id: Optional[str] = None
) -> Dict[str, Any]:
    
    # Filter non-critical LiteLLM errors (fastapi dependency warnings)
    litellm_logger = logging.getLogger("LiteLLM")
    litellm_filter = LiteLLMFilter()
    # Only add filter if not already added (avoid duplicates)
    if not any(isinstance(f, LiteLLMFilter) for f in litellm_logger.filters):
        litellm_logger.addFilter(litellm_filter)
    litellm_logger.setLevel(logging.WARNING)  # Only show warnings and errors, not info/debug
    
    try:
        config = load_config(repo_root)
    except Exception as e:
        return {
            "decision": "ERROR",
            "tests_ok": False,
            "error": f"Failed to load config: {e}"
        }
    
    # Load Spec Kit context
    # Se story_context è fornito, contiene già PRD context.full_concatenation (solo feature corrente)
    # Non serve chiamare load_specs() che carica TUTTE le feature
    spec_context = ""
    if story_context:
        # story_context già contiene PRD context.full_concatenation + story details
        # Usare direttamente senza aggiungere altro context per evitare confusione
        spec_context = story_context
        if verbose:
            logger.debug(f"Using PRD context from story_context (length: {len(spec_context)} characters)")
    elif config.spec_kit and config.spec_kit.get("enabled", False):
        # Fallback: se non c'è story_context, carica specs
        # Nota: questo carica TUTTE le feature, quindi preferire sempre story_context
        try:
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
            
            # Estrai feature_id se non fornito esplicitamente
            if not feature_id and story_context:
                # Cerca feature_id nel story_context (dalla PRD)
                import re
                match = re.search(r'feature_id["\']?\s*:\s*["\']?([^"\']+)', story_context)
                if match:
                    feature_id = match.group(1)
            
            # Se ancora non abbiamo feature_id, prova a estrarlo da task_name (formato: {feature_id}-{story_id}-{title})
            if not feature_id and task_name:
                import re
                match = re.match(r'^([0-9]{3}-[a-z0-9-]+)', task_name)
                if match:
                    feature_id = match.group(1)
            
            # Filtra all_files per feature corrente
            if feature_id:
                # Escludi altre feature directories da specs/, include solo feature corrente + file di codice
                filtered_files = []
                for f in all_files:
                    # Include file di codice (app/, lib/, src/, components/, etc.)
                    if any(f.startswith(prefix) for prefix in ["app/", "lib/", "src/", "components/", "pages/", "routes/"]):
                        filtered_files.append(f)
                    # Include file della feature corrente in specs/
                    elif f.startswith(f"specs/{feature_id}/"):
                        filtered_files.append(f)
                    # Escludi altre feature directories
                    elif f.startswith("specs/") and not f.startswith(f"specs/{feature_id}/"):
                        continue  # Escludi altre feature
                    # Include altri file non-spec (README, config, etc.)
                    elif not f.startswith("specs/"):
                        filtered_files.append(f)
                
                all_files = filtered_files
                if verbose:
                    logger.debug(f"Filtered files for feature {feature_id}: {len(all_files)} files (excluded other feature directories)")
            
            # Check presets
            if task_name in config.task_presets:
                preset = config.task_presets[task_name]
                aider_prompt = preset.get("prompt")
                # Might use files_hint logic here to filter files
            
            if not aider_prompt:
                # Generate plan
                log_phase("PLAN", verbose)
                logger.info("Planner Agent is thinking (this may take a minute)...")
                coder_model = config.models.get("coder", "ollama/qwen2.5-coder:14b")
                if verbose:
                    logger.debug(f"Using coder model: {coder_model}")
                aider_prompt, target_files = coder_plan(task_name, "User requested refactor.", all_files, spec_context, coder_model, base_url=config.ollama_base_url)
                logger.info(f"Plan generated: prompt length={len(aider_prompt)}, target files={len(target_files)}")
                if verbose:
                    logger.debug(f"Generated prompt: {aider_prompt[:200]}...")
                    logger.debug(f"Target files (before validation): {target_files}")
                
                # Validare target_files: escludi file di spec, include solo codice
                # IMPORTANTE: Accettiamo anche file che NON esistono ancora (per creazione iniziale)
                code_extensions = {'.ts', '.tsx', '.js', '.jsx', '.py', '.java', '.go', '.rs', '.cpp', '.c', '.h', '.hpp'}
                target_files_filtered = []
                spec_files_filtered = []
                
                for f in target_files:
                    # Escludi file di spec
                    if f.startswith('specs/'):
                        spec_files_filtered.append(f)
                        continue
                    
                    # Accetta solo file con estensioni di codice (anche se non esistono ancora)
                    if any(f.endswith(ext) for ext in code_extensions):
                        target_files_filtered.append(f)
                    else:
                        spec_files_filtered.append(f)
                
                if spec_files_filtered:
                    logger.warning(f"Filtered out {len(spec_files_filtered)} spec/non-code files: {spec_files_filtered[:3]}")
                
                # Verifica se i file suggeriti esistono o devono essere creati
                existing_files = []
                new_files = []
                for f in target_files_filtered:
                    file_path = repo_root / f
                    if file_path.exists():
                        existing_files.append(f)
                    else:
                        new_files.append(f)
                
                if new_files:
                    logger.info(f"Planner suggested {len(new_files)} new files to create: {', '.join(new_files[:3])}{'...' if len(new_files) > 3 else ''}")
                if existing_files:
                    logger.info(f"Planner suggested {len(existing_files)} existing files to modify: {', '.join(existing_files[:3])}{'...' if len(existing_files) > 3 else ''}")
                
                target_files = target_files_filtered
                if verbose:
                    logger.debug(f"Target files (after validation): {target_files}")
                
                # Se non ci sono file di codice suggeriti, avvisa ma non blocca (potrebbe essere creazione iniziale)
                if not target_files:
                    logger.warning("No code files suggested by Planner. This might be the first implementation.")
                    logger.warning("Planner should suggest creating new files in app/, lib/, src/, or components/ directories.")
                    # Non blocchiamo - lasciamo che Aider provi con il prompt generico
                    # Il Planner potrebbe aver suggerito di creare file nel prompt invece che in target_files
        except Exception as e:
            logger.warning(f"Failed to generate plan with agent: {e}")
            if verbose:
                logger.debug(f"Exception details: {e}", exc_info=True)
            logger.info("Falling back to task name as prompt.")
            aider_prompt = task_name
    
    if not aider_prompt:
        aider_prompt = task_name # Fallback if agent failed or no prompt provided
    
    # 2. Code (Aider)
    # IMPORTANTE: Aider può creare nuovi file automaticamente quando il prompt lo richiede.
    # Non blocchiamo se target_files è vuoto - Aider creerà i file necessari basandosi sul prompt.
    log_phase("CODE", verbose)
    logger.info(f"Starting Aider with prompt: {aider_prompt[:100]}..." if len(aider_prompt) > 100 else f"Starting Aider with prompt: {aider_prompt}")
    if target_files:
        # Verifica quali file esistono e quali devono essere creati
        existing = [f for f in target_files if (repo_root / f).exists()]
        new = [f for f in target_files if not (repo_root / f).exists()]
        if existing:
            logger.info(f"Target files to modify ({len(existing)}): {', '.join(existing[:3])}{'...' if len(existing) > 3 else ''}")
        if new:
            logger.info(f"Target files to create ({len(new)}): {', '.join(new[:3])}{'...' if len(new) > 3 else ''}")
    else:
        logger.info("No specific target files - Aider will create files based on prompt instructions")
    
    try:
        coder_model = config.models.get("coder", "ollama/qwen2.5-coder:14b")
        if verbose:
            logger.debug(f"Using coder model: {coder_model}")
        aider_exit_code = run_aider(aider_prompt, repo_root, target_files, 
                  model=coder_model, ollama_base_url=config.ollama_base_url)
        
        # Log Aider result (il summary è già loggato in run_aider)
        if aider_exit_code == 0:
            logger.info("Aider execution completed")
        elif aider_exit_code == 124:
            return {
                "decision": "ERROR",
                "tests_ok": False,
                "error": "Aider execution timed out after 5 minutes. Check model response time or context length."
            }
        else:
            logger.warning(f"Aider exited with code {aider_exit_code}")
        
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
        # Not showing full traceback in console unless verbose
        if verbose:
            logger.debug(f"Exception details: {e}", exc_info=True)
        return {
            "decision": "ERROR",
            "tests_ok": False,
            "error": f"Aider execution failed: {e}"
        }
    
    # 3. Test
    log_phase("TEST", verbose)
    if skip_tests:
        logger.info("Skipping tests (--no-tests flag set).")
        tests_ok, test_log = True, "Tests skipped via --no-tests flag"
    else:
        logger.info(f"Running tests: {config.tests}")
        try:
            tests_ok, test_log = run_tests(config.tests, repo_root)
            if tests_ok:
                logger.info("Tests PASSED")
            else:
                logger.warning("Tests FAILED")
                if verbose:
                    logger.debug(f"Test output: {test_log[:500]}")
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
    critic_reason = None
    if use_agents:
        log_phase("REVIEW", verbose)
        try:
            logger.info("Critic Agent is reviewing changes (this may take a minute)...")
            planner_model = config.models.get("planner", "ollama/llama3.1:8b")
            if verbose:
                logger.debug(f"Using planner model: {planner_model}")
            decision, critic_reason = critic_review(diff, test_log, task_name, planner_model, base_url=config.ollama_base_url)
            logger.info(f"Review decision: {decision}")
            if critic_reason:
                logger.info(f"Review reason: {critic_reason}")
            if verbose:
                logger.debug(f"Diff size: {len(diff)} characters")
        except Exception as e:
            logger.warning(f"Failed to review with agent: {e}")
            if verbose:
                logger.debug(f"Exception details: {e}", exc_info=True)
            logger.info("Defaulting to SHIP decision.")
            decision = "SHIP"
            critic_reason = None
    
    # Loggare perché non si fa commit
    if decision == "SHIP" and tests_ok:
        if auto_commit:
            logger.info("Auto-committing changes (SHIP + tests passed)...")
        else:
            logger.info("Changes ready to commit (SHIP + tests passed, but --auto-commit not set)")
    elif decision != "SHIP":
        logger.info(f"Not committing: Review decision is '{decision}'" + (f" ({critic_reason})" if critic_reason else ""))
    elif not tests_ok:
        logger.info("Not committing: Tests failed")
    
    # 5. Commit/Push
    if decision == "SHIP" and tests_ok:
        if auto_commit:
            try:
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
        "test_log_head": test_log[:500] if test_log else "",
        "critic_reason": critic_reason
    }
