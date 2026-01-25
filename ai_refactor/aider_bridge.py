import subprocess
import shlex
import os
import re
import logging
import time
import signal
import fcntl
from pathlib import Path
from typing import List, Optional, Tuple
from datetime import datetime
import urllib.request
import json

logger = logging.getLogger(__name__)

def extract_aider_summary(output: str) -> str:
    """
    Extract concise summary from Aider output.
    Looks for file modifications and errors.
    """
    # Pattern 1: Look for "Applied edit to X" (Common in 'whole' or 'architect' format)
    applied_edits = re.findall(r'Applied edit to (.*)', output)
    if applied_edits:
        unique_files = list(dict.fromkeys(applied_edits))
        return f"Modified {len(unique_files)} files: {', '.join(unique_files[:3])}{'...' if len(unique_files) > 3 else ''}"

    # Pattern 2: Look for "Modified X files" or similar
    modified_match = re.search(r'Modified\s+(\d+)\s+files?', output, re.IGNORECASE)
    if modified_match:
        count = modified_match.group(1)
        # Try to find specific modified files in the output
        file_paths = re.findall(r'(?:^|\s)((?:app|lib|src|components|pages|routes|tests)/[^\s\n]+\.(?:ts|tsx|js|jsx|py))', output, re.MULTILINE)
        unique_files = list(dict.fromkeys(file_paths))[:5]
        if unique_files:
            return f"Modified {count} files: {', '.join(unique_files[:3])}{'...' if len(unique_files) > 3 else ''}"
        return f"Modified {count} files"
    
    # Pattern 2: Look for diff lines
    diff_files = set()
    for line in output.split('\n'):
        if line.startswith('diff --git') or line.startswith('+++') or line.startswith('---'):
            match = re.search(r'[ab]/((?:app|lib|src|components|pages|routes|tests)/[^\s]+)', line)
            if match:
                diff_files.add(match.group(1))
    
    if diff_files:
        file_list = list(diff_files)[:5]
        return f"Modified {len(diff_files)} files: {', '.join(file_list[:3])}{'...' if len(file_list) > 3 else ''}"
    
    return "No code files modified (check if prompt was clear or model responded)"

def check_ollama_connection(base_url: str, model: str) -> bool:
    """
    Verifies that Ollama is reachable and the model exists.
    Returns True if OK, False otherwise.
    """
    try:
        url = f"{base_url}/api/tags"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status != 200:
                logger.error(f"Ollama returned status {response.status}")
                return False
            
            data = json.loads(response.read().decode())
            models = [m['name'] for m in data.get('models', [])]
            clean_model = model.split('/')[-1] if '/' in model else model
            if not any(m.startswith(clean_model) for m in models):
                logger.warning(f"Model '{model}' not found in Ollama. Available: {', '.join(models[:5])}...")
        return True
    except Exception as e:
        logger.error(f"Ollama connection check failed: {e}")
        return False

def make_async(fd):
    """Make a file descriptor non-blocking."""
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

def run_aider(prompt: str, repo_root: Path, files: Optional[List[str]] = None, 
              read_only_files: Optional[List[str]] = None, config_path: Optional[Path] = None, 
              model: Optional[str] = None, ollama_base_url: Optional[str] = None) -> int:
    """
    Runs Aider with reactive status updates and full logging.
    """
    if model and ollama_base_url:
        if not check_ollama_connection(ollama_base_url, model):
            logger.error("Ollama connection check failed. Aborting Aider run.")
            return 1
            
    # Force absolute paths for repo_root to ensure git discovery
    repo_root = repo_root.resolve()
            
    cmd = ["aider", "--no-auto-commits", "--no-show-model-warnings", "--message", prompt]
    cmd.extend([
        "--no-suggest-shell-commands", 
        "--no-analytics",
        "--yes-always",
        "--no-pretty",     
        "--map-tokens", "0",
        "--git" # Force git detection
    ])
    
    if config_path and config_path.exists():
        cmd.extend(["--config", str(config_path)])
    if model:
        cmd.extend(["--model", model])
    
    # Add files to edit
    if files:
        cmd.extend(files)
        
    # Add read-only files for context
    if read_only_files:
        for ro_file in read_only_files:
            cmd.extend(["--read", ro_file])
        
    env = os.environ.copy()
    if ollama_base_url:
        env["OLLAMA_API_BASE"] = ollama_base_url
        env["OPENAI_API_BASE"] = f"{ollama_base_url}/v1"
        env["OPENAI_API_KEY"] = "ollama"

    debug_dir = repo_root / "specs"
    debug_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = debug_dir / "aider.log"
    
    # Save prompt
    (debug_dir / "last_aider_prompt.md").write_text(prompt, encoding="utf-8")

    logger.debug(f"Starting coding task...")
    logger.debug(f"Log file: {log_file_path}")
    
    full_output = []
    process = None
    try:
        with open(log_file_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"\n--- Run Start: {datetime.now().isoformat()} ---\n")
            
            process = subprocess.Popen(
                cmd,
                cwd=str(repo_root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True 
            )
            
            make_async(process.stdout.fileno())
            
            start_time = time.time()
            last_output_time = start_time
            last_heartbeat_time = start_time
            timeout = 300
            
            while True:
                current_time = time.time()
                elapsed = current_time - start_time
                
                if process.poll() is not None:
                    break
                    
                if elapsed > timeout:
                    logger.error(f"Aider timed out after {timeout}s.")
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    return 124
                
                try:
                    line = process.stdout.readline()
                    if line:
                        log_file.write(line)
                        log_file.flush()
                        full_output.append(line)
                        last_output_time = current_time
                        
                        # Show some specific progress in console if we see it
                        if "Applied edit to" in line or "Creating" in line or "Updating" in line:
                            logger.info(f"[AIDER] {line.strip()}")
                        
                        # Monitor model responses (often start with 'I will...' or 'To implement...')
                        if "I will" in line or "To implement" in line:
                            logger.info("[AIDER] Model is starting to apply changes...")
                    else:
                        # No output right now, check if we've been waiting long
                        time_since_output = current_time - last_output_time
                        if time_since_output > 15:
                            if int(current_time) % 30 == 0: # Log every 30s of silence
                                logger.info(f"Still waiting for model response... ({int(elapsed)}s elapsed)")
                                last_output_time = current_time # Reset to avoid spamming every second
                        
                        time.sleep(0.5)
                except IOError:
                    # No data available on non-blocking pipe
                    time.sleep(0.5)

                # Explicit heartbeat every 60s
                if current_time - last_heartbeat_time > 60:
                    logger.info(f"Aider is active. Total time: {int(elapsed // 60)}m {int(elapsed % 60)}s")
                    last_heartbeat_time = current_time

            # Final capture
            try:
                final_out = process.stdout.read()
                if final_out:
                    log_file.write(final_out)
                    full_output.append(final_out)
            except:
                pass

        exit_code = process.returncode
        complete_output = "".join(full_output)
        summary = extract_aider_summary(complete_output)
        logger.info(f"Aider task finished. {summary}")
        
        return exit_code
        
    except Exception as e:
        logger.error(f"Bridge failure: {e}")
        if process and process.poll() is None:
            try: os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except: pass
        return 1
