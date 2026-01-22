import subprocess
import shlex
from pathlib import Path
from typing import List, Optional

def run_aider(prompt: str, repo_root: Path, files: Optional[List[str]] = None, config_path: Optional[Path] = None) -> int:
    """
    Runs Aider in single-message mode.
    """
    cmd = ["aider", "--no-auto-commits", "--message", prompt]
    
    if config_path and config_path.exists():
        cmd.extend(["--config", str(config_path)])
        
    if files:
        # Resolve files relative to repo_root
        cmd.extend(files)
        
    print(f"Running Aider with command: {' '.join(shlex.quote(c) for c in cmd)}")
    
    try:
        # We allow Aider to take over stdin/stdout potentially, but usually in this automation 
        # it just runs the prompt and exits.
        return subprocess.call(cmd, cwd=str(repo_root))
    except FileNotFoundError:
        print("Error: 'aider' command not found. Please install it via 'pipx install aider-chat'.")
        return 127
