import subprocess
import shlex
import os
from pathlib import Path
from typing import List, Optional

def run_aider(prompt: str, repo_root: Path, files: Optional[List[str]] = None, config_path: Optional[Path] = None, 
              model: Optional[str] = None, ollama_base_url: Optional[str] = None) -> int:
    """
    Runs Aider in single-message mode.
    
    Args:
        prompt: The prompt to send to Aider
        repo_root: Root directory of the repository
        files: Optional list of files to include
        config_path: Optional path to Aider config file
        model: Optional model name (e.g., "ollama/qwen2.5-coder:14b")
        ollama_base_url: Optional Ollama base URL (e.g., "http://192.168.1.4:11434")
    """
    cmd = ["aider", "--no-auto-commits", "--message", prompt]
    
    if config_path and config_path.exists():
        cmd.extend(["--config", str(config_path)])
    
    # Configure Aider to use Ollama if model and base_url are provided
    env = os.environ.copy()
    if model:
        if ollama_base_url:
            # Aider needs OLLAMA_API_BASE for Ollama models
            env["OLLAMA_API_BASE"] = ollama_base_url
            # Also set OpenAI-compatible endpoint (some Aider versions use this)
            api_base = f"{ollama_base_url}/v1"
            env["OPENAI_API_BASE"] = api_base
            env["OPENAI_API_KEY"] = "ollama"  # Ollama doesn't require a real key
        # Set model via command line (Aider supports --model flag)
        if model.startswith("ollama/"):
            # Remove "ollama/" prefix for --model flag
            model_name = model.replace("ollama/", "")
            cmd.extend(["--model", model_name])
        else:
            cmd.extend(["--model", model])
    
    if files:
        # Resolve files relative to repo_root
        cmd.extend(files)
        
    print(f"Running Aider with command: {' '.join(shlex.quote(c) for c in cmd)}")
    if model:
        print(f"Using model: {model}")
    if ollama_base_url:
        print(f"Using Ollama endpoint: {ollama_base_url}")
    
    try:
        # We allow Aider to take over stdin/stdout potentially, but usually in this automation 
        # it just runs the prompt and exits.
        return subprocess.call(cmd, cwd=str(repo_root), env=env)
    except FileNotFoundError:
        print("Error: 'aider' command not found. Please install it via 'pipx install aider-chat'.")
        return 127
