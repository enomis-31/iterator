import subprocess
import shlex
import os
import re
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

def extract_aider_summary(output: str) -> str:
    """Extract concise summary from Aider output"""
    # Pattern 1: Cerca "Modified X files" o simili
    modified_match = re.search(r'Modified\s+(\d+)\s+files?', output, re.IGNORECASE)
    if modified_match:
        count = modified_match.group(1)
        # Cerca nomi file modificati
        file_paths = re.findall(r'(app|lib|src|components|pages|routes)/[^\s\n]+\.(?:ts|tsx|js|jsx|py)', output)
        unique_files = list(set(file_paths))[:5]
        if unique_files:
            return f"Modified {count} files: {', '.join(unique_files[:3])}{'...' if len(unique_files) > 3 else ''}"
        return f"Modified {count} files"
    
    # Pattern 2: Cerca file menzionati nel diff
    diff_files = set()
    for line in output.split('\n'):
        # Cerca linee diff che indicano file modificati
        if line.startswith('diff --git') or line.startswith('+++') or line.startswith('---'):
            match = re.search(r'[ab]/(app|lib|src|components|pages|routes)/([^\s]+)', line)
            if match:
                diff_files.add(f"{match.group(1)}/{match.group(2)}")
    
    if diff_files:
        file_list = list(diff_files)[:5]
        return f"Modified {len(diff_files)} files: {', '.join(file_list[:3])}{'...' if len(file_list) > 3 else ''}"
    
    # Pattern 3: Cerca file menzionati nel contesto
    code_files = set()
    for line in output.split('\n'):
        match = re.search(r'(app|lib|src|components|pages|routes)/[^\s\n]+\.(?:ts|tsx|js|jsx|py)', line)
        if match and not any(line.strip().startswith(p) for p in ['+', '-', '@@', 'diff']):
            code_files.add(match.group(0))
    
    if code_files:
        file_list = list(code_files)[:5]
        return f"Processed {len(code_files)} files: {', '.join(file_list[:3])}{'...' if len(file_list) > 3 else ''}"
    
    return "No code files modified (check if target_files were correct)"

def filter_aider_stderr(stderr: str) -> str:
    """Filter non-critical stderr messages"""
    lines = stderr.split('\n')
    filtered = []
    for line in lines:
        # Filtra warning non critici
        if any(skip in line.lower() for skip in ['warning:', 'deprecated', 'suggestion']):
            continue
        filtered.append(line)
    return '\n'.join(filtered)

def run_aider(prompt: str, repo_root: Path, files: Optional[List[str]] = None, config_path: Optional[Path] = None, 
              model: Optional[str] = None, ollama_base_url: Optional[str] = None) -> int:
    """
    Runs Aider in single-message mode.
    
    Args:
        prompt: The prompt to send to Aider
        repo_root: Root directory of the repository
        files: Optional list of files to include
        config_path: Optional path to Aider config file (if not provided, looks for ~/.aider.conf.yml)
        model: Optional model name (e.g., "ollama/qwen2.5-coder:14b")
        ollama_base_url: Optional Ollama base URL (e.g., "http://192.168.1.4:11434")
    
    Note:
        Aider configuration priority:
        1. config_path parameter (if provided)
        2. ~/.aider.conf.yml (user config, if exists)
        3. Environment variables (OLLAMA_API_BASE, OPENAI_API_BASE, etc.)
        4. Command-line flags (--model, etc.)
    """
    # Build command with non-interactive flags
    # Note: We DO NOT use --no-git because Aider uses git to understand code context, see diffs, and track changes. Git is essential!
    # --no-auto-commits: Don't auto-commit (we handle commits in workflow.py) (we handle commits in workflow.py)
    # --no-show-model-warnings: Suppress model warnings
    cmd = ["aider", "--no-auto-commits", "--no-show-model-warnings", "--message", prompt]
    
    # Look for Aider config file if not explicitly provided
    if not config_path:
        # Check for user config file
        user_config = Path.home() / ".aider.conf.yml"
        if user_config.exists():
            config_path = user_config
    
    if config_path and config_path.exists():
        cmd.extend(["--config", str(config_path)])
        logger.info(f"Using Aider config: {config_path}")
    
    # Configure Aider to use Ollama if model and base_url are provided
    env = os.environ.copy()
    
    # Disable interactive prompts
    env["AIDER_NO_ANALYTICS"] = "1"
    env["AIDER_SKIP_GITIGNORE"] = "1"
    
    if model:
        if ollama_base_url:
            # Aider needs OLLAMA_API_BASE for Ollama models
            env["OLLAMA_API_BASE"] = ollama_base_url
            # Also set OpenAI-compatible endpoint (some Aider versions use this)
            api_base = f"{ollama_base_url}/v1"
            env["OPENAI_API_BASE"] = api_base
            env["OPENAI_API_KEY"] = "ollama"  # Ollama doesn't require a real key
            logger.info(f"Configured Ollama endpoint: {ollama_base_url}")
        # Set model via command line (Aider supports --model flag)
        # Keep full format "ollama/model" for LiteLLM to recognize provider
        cmd.extend(["--model", model])
        logger.info(f"Using model: {model}")
    
    if files:
        # Resolve files relative to repo_root
        cmd.extend(files)
        
    logger.debug(f"Running Aider with command: {' '.join(shlex.quote(c) for c in cmd)}")
    
    try:
        # Run Aider non-interactively with automatic responses to prompts
        # Responses: n (no analytics), n (no gitignore), d (don't ask again for warnings)
        # timeout: 5 minutes max per execution
        result = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=env,
            input="n\nn\nd\n",  # Automatic responses: no analytics, no gitignore, don't ask warnings
            text=True,
            capture_output=True,  # ✅ CATTURA OUTPUT per estrarre summary
            timeout=300,  # 5 minutes timeout
            stdout=subprocess.PIPE,  # Explicitly redirect stdout
            stderr=subprocess.PIPE   # Explicitly redirect stderr
        )
        
        # Parse output per summary
        if result.stdout:
            summary = extract_aider_summary(result.stdout)
            logger.info(f"Aider completed: {summary}")
            # Log output completo solo in verbose mode
            verbose_mode = logger.isEnabledFor(logging.DEBUG)
            if verbose_mode:
                logger.debug(f"Full Aider output:\n{result.stdout}")
        
        if result.stderr:
            # Filtra stderr per errori rilevanti (escludi warning non critici)
            stderr_filtered = filter_aider_stderr(result.stderr)
            if stderr_filtered:
                logger.warning(f"Aider stderr: {stderr_filtered[:500]}")
        
        return result.returncode
    except subprocess.TimeoutExpired:
        logger.error("Aider execution timed out after 5 minutes. This may indicate:")
        logger.error("  - Model is taking too long to respond")
        logger.error("  - Context is too large (check context length limits)")
        logger.error("  - Network issues with Ollama")
        return 124  # Standard timeout exit code
    except FileNotFoundError:
        logger.error("Error: 'aider' command not found. Please install it via 'pipx install aider-chat'.")
        return 127
    except Exception as e:
        logger.error(f"Unexpected error running Aider: {e}")
        verbose_mode = logger.isEnabledFor(logging.DEBUG)
        if verbose_mode:
            logger.debug(f"Exception details: {e}", exc_info=True)
        return 1