import subprocess
import time
import re
from pathlib import Path

def run_git(cmd: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git"] + cmd, 
        cwd=cwd, 
        capture_output=True, 
        text=True, 
        check=True
    )
    return result.stdout.strip()

def get_repo_root(cwd: Path = None) -> Path:
    if cwd is None:
        cwd = Path.cwd()
    try:
        root = run_git(["rev-parse", "--show-toplevel"], cwd=cwd)
        return Path(root)
    except subprocess.CalledProcessError:
        raise ValueError("Not inside a git repository")

def ensure_clean_worktree(repo_root: Path):
    status = run_git(["status", "--porcelain"], cwd=repo_root)
    if status:
        raise RuntimeError("Working directory is not clean. Please commit or stash changes.")

def create_task_branch(task_name: str, prefix: str, repo_root: Path) -> str:
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', task_name.lower()).strip('-')
    timestamp = int(time.time())
    branch_name = f"{prefix}/{slug}-{timestamp}"
    run_git(["checkout", "-b", branch_name], cwd=repo_root)
    print(f"Created branch: {branch_name}")
    return branch_name

def get_diff(repo_root: Path, base_ref: str = "HEAD~1") -> str:
    return run_git(["diff", base_ref], cwd=repo_root)

def commit_changes(repo_root: Path, message: str):
    # -a stages modified existing files. New files need add potentially.
    # To be safe for new files, we might want 'git add .'
    run_git(["add", "."], cwd=repo_root)
    run_git(["commit", "-m", message], cwd=repo_root)

def push_branch(repo_root: Path, remote: str = "origin"):
    # Current branch
    current = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
    run_git(["push", "-u", remote, current], cwd=repo_root)
