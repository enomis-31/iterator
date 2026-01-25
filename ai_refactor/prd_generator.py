import json
import logging
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

@dataclass
class StorySpec:
    id: str
    title: str
    description: str = ""
    acceptance_criteria: List[str] = None

    def __post_init__(self):
        if self.acceptance_criteria is None:
            self.acceptance_criteria = []

def parse_tasks_md(tasks_path: Path) -> List[StorySpec]:
    """
    Parses a tasks.md file and returns a list of StorySpec objects.
    
    Expected format:
    - [ ] T1: Title
      - Description: ...
    """
    if not tasks_path.exists():
        logger.warning(f"Tasks file not found: {tasks_path}")
        return []

    stories = []
    current_story = None
    
    # Regex to match task lines like "- [ ] T1: Title" or "- [x] T1: Title"
    # Captures: 1=id, 2=title
    task_pattern = re.compile(r"^\s*-\s*\[[ xX]\]\s*(T\d+):\s*(.+)$")
    
    # Regex to match description lines like "  - Description: ..."
    desc_pattern = re.compile(r"^\s*-\s*Description:\s*(.+)$", re.IGNORECASE)

    with open(tasks_path, "r", encoding="utf-8") as f:
        for line in f:
            line_stripped = line.rstrip()
            
            # Check for new task
            task_match = task_pattern.match(line_stripped)
            if task_match:
                # Save previous story if exists
                if current_story:
                    stories.append(current_story)
                
                story_id = task_match.group(1)
                title = task_match.group(2).strip()
                current_story = StorySpec(id=story_id, title=title)
                continue
            
            # Check for description if inside a story
            if current_story:
                desc_match = desc_pattern.match(line_stripped)
                if desc_match:
                    current_story.description = desc_match.group(1).strip()
                # You could add more logic here to capture multi-line descriptions if needed
                # by checking indentation, but keeping it simple for now as requested.

    # Append the last story
    if current_story:
        stories.append(current_story)

    return stories

def generate_prd(
    repo_root: Path,
    feature_id: str,
    specs_dir: str = "specs",
) -> Path:
    """
    Generates or updates the PRD for a specific feature based on Spec Kit files.
    """
    feature_dir = repo_root / specs_dir / feature_id
    tasks_path = feature_dir / "tasks.md"
    spec_path = feature_dir / "spec.md"
    plan_path = feature_dir / "plan.md"
    prd_path = feature_dir / "prd.json"

    if not feature_dir.exists():
        raise FileNotFoundError(f"Feature directory not found: {feature_dir}")

    # 1. Parse tasks/stories
    new_stories_specs = parse_tasks_md(tasks_path)
    if not new_stories_specs:
        logger.warning(f"No stories found in {tasks_path}. PRD might be empty of stories.")

    # 2. Extract global info (Title, Description)
    feature_title = f"Feature {feature_id}"
    feature_description = ""

    # Try to get title/desc from spec.md
    if spec_path.exists():
        content = spec_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        # Simple heuristic: first H1 is title
        for line in lines:
            if line.startswith("# "):
                feature_title = line[2:].strip()
                break
        # Take first few paragraphs as description (simplified)
        # Just taking the first 500 chars for now or until first header
        desc_lines = []
        for line in lines:
            if line.startswith("#"): continue
            if not line.strip(): continue
            desc_lines.append(line.strip())
            if len(desc_lines) > 5: break
        if desc_lines:
            feature_description = " ".join(desc_lines)

    # 3. Load or Create PRD data
    prd_data = {}
    if prd_path.exists():
        try:
            prd_data = json.loads(prd_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse existing PRD {prd_path}: {e}")
            # Proceed with empty dict, or maybe backup? For now, we'll try to merge into empty.
    
    # Initialize basic fields if new
    if "feature_id" not in prd_data:
        prd_data["feature_id"] = feature_id
    
    # Always update title/desc from specs (source of truth)
    prd_data["title"] = feature_title
    if feature_description:
        prd_data["description"] = feature_description
    
    if "stories" not in prd_data:
        prd_data["stories"] = []

    # 4. Merge stories
    # Convert existing stories to dict by ID for easy lookup
    existing_stories_map = {s["id"]: s for s in prd_data["stories"]}
    merged_stories = []

    for spec in new_stories_specs:
        existing = existing_stories_map.get(spec.id)
        
        # Prepare acceptance criteria (simple default if empty)
        ac = spec.acceptance_criteria
        if not ac:
            # Fallback: create one AC from description/title
            ac = [f"Verify {spec.title}"] 
            if spec.description:
                ac.append(f"Verify details: {spec.description}")

        if existing:
            # Update define fields
            existing["title"] = spec.title
            existing["description"] = spec.description
            existing["acceptance_criteria"] = ac
            # Preserve status, attempts, last_error
            merged_stories.append(existing)
            # Remove from map so we know what's left (if we wanted to handle deletions)
            del existing_stories_map[spec.id]
        else:
            # Create new story
            new_story = {
                "id": spec.id,
                "title": spec.title,
                "description": spec.description,
                "acceptance_criteria": ac,
                "status": "todo",
                "attempts": 0,
                "last_error": None
            }
            merged_stories.append(new_story)
    
    # Optional: Keep stories that are in PRD but not in tasks?
    # The prompt says: "stories eventualmente non più presenti in tasks.md possono... essere mantenute"
    # So we append the remaining ones from existing_stories_map
    for remaining_id, remaining_story in existing_stories_map.items():
        merged_stories.append(remaining_story)

    # Sort stories by ID (T1, T2...)
    def sort_key(s):
        # Extract number from T<n>
        m = re.match(r"T(\d+)", s["id"])
        return int(m.group(1)) if m else 9999

    merged_stories.sort(key=sort_key)
    prd_data["stories"] = merged_stories

    # 5. Save PRD
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(prd_data, f, indent=2)
    
    return prd_path
