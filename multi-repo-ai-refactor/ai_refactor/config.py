import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional

@dataclass
class Config:
    repo_root: Path
    language: str
    tests: str
    include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    branch_prefix: str = "ai"
    task_presets: Dict[str, Dict[str, str]] = field(default_factory=dict)
    spec_kit: Dict[str, any] = field(default_factory=lambda: {"enabled": False})
    models: Dict[str, str] = field(default_factory=lambda: {"coder": "ollama/qwen2.5-coder:14b", "planner": "ollama/llama3.1:8b"})

def detect_language(repo_root: Path) -> str:
    # Simple heuristic
    if list(repo_root.glob("*.py")) or (repo_root / "pyproject.toml").exists() or (repo_root / "setup.py").exists():
        return "python"
    if (repo_root / "package.json").exists():
        return "typescript" # Broadly JS/TS
    if (repo_root / "pom.xml").exists() or (repo_root / "build.gradle").exists():
        return "java"
    return "unknown"

def detect_test_command(repo_root: Path, language: str) -> str:
    if language == "python":
        if (repo_root / "pytest.ini").exists() or (repo_root / "pyproject.toml").exists():
             # Check if pyproject.toml actually has pytest config or is just project config? 
             # For now, default to pytest if it looks like python
             return "pytest"
        return "python -m unittest"
    if language == "typescript":
        if (repo_root / "package.json").exists():
            return "npm test"
    return ""

def load_config(repo_root: Path) -> Config:
    config_path = repo_root / ".ai-refactor.yml"
    
    defaults = {
        "language": detect_language(repo_root),
        "branch_prefix": "ai",
        "include": ["src", "app", "lib"],
        "exclude": ["node_modules", "dist", ".ralph", ".agents", "__pycache__", ".git", ".venv", "venv"],
        "task_presets": {},
        "spec_kit": {"enabled": False},
        "models": {
            "coder": "ollama/qwen2.5-coder:14b",
            "planner": "ollama/llama3.1:8b"
        }
    }
    defaults["tests"] = detect_test_command(repo_root, defaults["language"])

    if config_path.exists():
        with open(config_path, "r") as f:
            user_config = yaml.safe_load(f) or {}
            
            language = user_config.get("language", defaults["language"])
            tests = user_config.get("tests", defaults["tests"])
            include = user_config.get("include", defaults["include"])
            exclude = user_config.get("exclude", defaults["exclude"])
            branch_prefix = user_config.get("branch_prefix", defaults["branch_prefix"])
            task_presets = user_config.get("task_presets", defaults["task_presets"])
            spec_kit = user_config.get("spec_kit", defaults["spec_kit"])
            
            # Merge models dict carefully so user can override just one
            user_models = user_config.get("models", {})
            models = defaults["models"].copy()
            models.update(user_models)
            
            return Config(
                repo_root=repo_root,
                language=language,
                tests=tests,
                include=include,
                exclude=exclude,
                branch_prefix=branch_prefix,
                task_presets=task_presets,
                spec_kit=spec_kit,
                models=models
            )
            
    return Config(
        repo_root=repo_root,
        language=defaults["language"],
        tests=defaults["tests"],
        include=defaults["include"],
        exclude=defaults["exclude"],
        branch_prefix=defaults["branch_prefix"],
        task_presets=defaults["task_presets"],
        spec_kit=defaults["spec_kit"],
        models=defaults["models"]
    )
