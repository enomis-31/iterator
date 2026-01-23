import os
from pathlib import Path
from typing import List, Optional

def load_specs(repo_root: Path, specs_dir: str = "specs") -> str:
    """
    Reads all markdown files from the specs directory and subdirectories, concatenates them.
    This serves as the 'Source of Truth' context for the agents.
    
    Supports Spec Kit structure:
    - Priority files at root: constitution.md, system-patterns.md, tech-context.md
    - Feature directories: specs/001-feature-name/spec.md, plan.md, tasks.md, etc.
    """
    specs_path = repo_root / specs_dir
    if not specs_path.exists() or not specs_path.is_dir():
        return ""

    combined_specs = []
    
    # Priority files if they exist (Spec Kit conventions) - at root level
    priority_files = ["constitution.md", "system-patterns.md", "tech-context.md"]
    
    # Read priority files first (at root level)
    for fname in priority_files:
        fpath = specs_path / fname
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8")
                combined_specs.append(f"--- SPEC: {fname} ---\n{content}\n")
            except Exception as e:
                print(f"Warning: Failed to read spec file {fname}: {e}")

    # Read remaining markdown files at root level
    for fpath in specs_path.glob("*.md"):
        if fpath.name not in priority_files:
            try:
                content = fpath.read_text(encoding="utf-8")
                combined_specs.append(f"--- SPEC: {fpath.name} ---\n{content}\n")
            except Exception as e:
                print(f"Warning: Failed to read spec file {fpath.name}: {e}")

    # Read markdown files from feature subdirectories (Spec Kit structure)
    # e.g., specs/001-ui-theme/spec.md, specs/002-calendar-appointments/plan.md
    for feature_dir in specs_path.iterdir():
        if feature_dir.is_dir() and not feature_dir.name.startswith('.'):
            # Priority order for feature files
            feature_priority = ["spec.md", "plan.md", "tasks.md", "research.md", "data-model.md"]
            
            # Read priority feature files first
            for fname in feature_priority:
                fpath = feature_dir / fname
                if fpath.exists():
                    try:
                        content = fpath.read_text(encoding="utf-8")
                        rel_path = fpath.relative_to(specs_path)
                        combined_specs.append(f"--- SPEC: {rel_path} ---\n{content}\n")
                    except Exception as e:
                        print(f"Warning: Failed to read spec file {rel_path}: {e}")
            
            # Read remaining markdown files in feature directory
            for fpath in feature_dir.glob("*.md"):
                if fpath.name not in feature_priority:
                    try:
                        content = fpath.read_text(encoding="utf-8")
                        rel_path = fpath.relative_to(specs_path)
                        combined_specs.append(f"--- SPEC: {rel_path} ---\n{content}\n")
                    except Exception as e:
                        print(f"Warning: Failed to read spec file {rel_path}: {e}")

    if not combined_specs:
        return ""

    return "# PROJECT SPECIFICATIONS (Source of Truth)\n\n" + "\n".join(combined_specs)
