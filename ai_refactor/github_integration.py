import subprocess
import shlex

def create_pr(title: str, body: str) -> None:
    """
    Creates a pull request using GitHub CLI (gh).
    """
    cmd = [
        "gh", "pr", "create",
        "--title", title,
        "--body", body
    ]
    
    print(f"Creating PR with command: {' '.join(shlex.quote(c) for c in cmd)}")
    
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"Failed to create PR: {e}")
    except FileNotFoundError:
        print("Error: 'gh' command not found. Please install GitHub CLI.")
