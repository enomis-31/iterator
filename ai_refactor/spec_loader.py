import os
from pathlib import Path
from typing import List, Optional

def load_specs(repo_root: Path, specs_dir: str = "specs") -> str:
    """
    Reads all markdown files from the specs directory and concatenates them.
    This serves as the 'Source of Truth' context for the agents.
    """
    specs_path = repo_root / specs_dir
    if not specs_path.exists() or not specs_path.is_dir():
        return ""

    combined_specs = []
    
    # Priority files if they exist (Spec Kit conventions)
    priority_files = ["constitution.md", "system-patterns.md", "tech-context.md"]
    
    # Read priority files first
    for fname in priority_files:
        fpath = specs_path / fname
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8")
                combined_specs.append(f"--- SPEC: {fname} ---\n{content}\n")
            except Exception as e:
                print(f"Warning: Failed to read spec file {fname}: {e}")

    # Read remaining markdown files
    for fpath in specs_path.glob("*.md"):
        if fpath.name not in priority_files:
            try:
                content = fpath.read_text(encoding="utf-8")
                combined_specs.append(f"--- SPEC: {fpath.name} ---\n{content}\n")
            except Exception as e:
                print(f"Warning: Failed to read spec file {fpath.name}: {e}")

    if not combined_specs:
        return ""

    return "# PROJECT SPECIFICATIONS (Source of Truth)\n\n" + "\n".join(combined_specs)
