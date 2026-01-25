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
    user_story_tags: List[str] = None  # e.g., ["US1"]

    def __post_init__(self):
        if self.acceptance_criteria is None:
            self.acceptance_criteria = []
        if self.user_story_tags is None:
            self.user_story_tags = []

def parse_tasks_md(tasks_path: Path) -> List[StorySpec]:
    """
    Parses a tasks.md file and returns a list of StorySpec objects.
    Captures [USx] tags to link tasks to specific user stories.
    """
    if not tasks_path.exists():
        logger.warning(f"Tasks file not found: {tasks_path}")
        return []

    stories = []
    current_story = None
    
    # Regex to match task lines like "- [ ] T1: Title" or "- [x] T1 [US1] Title"
    # Captures: 1=id, 2=title_with_tags
    task_pattern = re.compile(r"^\s*-\s*\[[ xX]\]\s*(T\d+):\s*(.+)$")
    
    # Regex to find [USx] tags
    us_tag_pattern = re.compile(r"\[(US\d+)\]")

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
                raw_title = task_match.group(2).strip()
                
                # Extract US tags
                us_tags = us_tag_pattern.findall(raw_title)
                # Clean title (optional, might want to keep tags visible)
                # title = us_tag_pattern.sub("", raw_title).strip()
                title = raw_title # Keep tags in title for context
                
                current_story = StorySpec(id=story_id, title=title, user_story_tags=us_tags)
                continue
            
            # Check for description if inside a story
            if current_story:
                desc_match = desc_pattern.match(line_stripped)
                if desc_match:
                    current_story.description = desc_match.group(1).strip()

    # Append the last story
    if current_story:
        stories.append(current_story)

    return stories

def load_spec_documents(feature_dir: Path) -> Dict[str, Any]:
    """
    Recursively scans the feature directory for relevant spec documents.
    Returns a structured dictionary of content and a concatenated string.
    """
    
    # Files/patterns to include
    keep_patterns = [
        "spec\\.md$",
        "plan\\.md$",
        "data-model\\.md$", 
        "research\\.md$",
        "quickstart\\.md$",
        "contracts/.*\\.md$"
    ]
    
    context_data = {
        "files": {},
        "full_concatenation": ""
    }
    
    full_text_parts = []

    # Sort files to have deterministic order (spec.md first usually good)
    # But walk yields arbitrary order. We'll collect then sort.
    found_files = []
    
    for path in feature_dir.rglob("*.md"):
        rel_path = path.relative_to(feature_dir).as_posix()
        
        # Check against patterns
        is_relevant = False
        for pat in keep_patterns:
            if re.search(pat, rel_path, re.IGNORECASE):
                is_relevant = True
                break
        
        if is_relevant:
            found_files.append((rel_path, path))
            
    # Sort: spec.md first, then others alphabetically
    def sort_key(item):
        path_str = item[0].lower()
        if path_str == "spec.md": return "0_spec.md"
        if path_str == "plan.md": return "1_plan.md"
        return "2_" + path_str

    found_files.sort(key=sort_key)

    for rel_path, full_path in found_files:
        try:
            content = full_path.read_text(encoding="utf-8")
            # Store in map using relative path as key
            context_data["files"][rel_path] = content
            
            # Append to full text
            header = f"\n\n{'='*40}\nFILE: {rel_path}\n{'='*40}\n\n"
            full_text_parts.append(header + content)
            
        except Exception as e:
            logger.warning(f"Failed to read spec file {rel_path}: {e}")

    context_data["full_concatenation"] = "".join(full_text_parts)
    return context_data

def generate_prd(
    repo_root: Path,
    feature_id: str,
    specs_dir: str = "specs",
) -> Path:
    """
    Generates or updates the PRD for a specific feature based on Spec Kit files.
    Aggregates ALL spec files into the PRD context.
    """
    feature_dir = repo_root / specs_dir / feature_id
    tasks_path = feature_dir / "tasks.md"
    prd_path = feature_dir / "prd.json"

    if not feature_dir.exists():
        raise FileNotFoundError(f"Feature directory not found: {feature_dir}")

    # 1. Parse tasks/stories
    new_stories_specs = parse_tasks_md(tasks_path)
    if not new_stories_specs:
        logger.warning(f"No stories found in {tasks_path}. PRD might be empty of stories.")

    # 2. Extract global info (Title, Description) & Context
    # We use the intelligent aggregator now
    spec_context = load_spec_documents(feature_dir)
    
    # Try to derive title/desc from spec.md if available, else generic
    feature_title = f"Feature {feature_id}"
    feature_description = "See full context."
    
    if "spec.md" in spec_context["files"]:
        spec_content = spec_context["files"]["spec.md"]
        lines = spec_content.splitlines()
        for line in lines:
            if line.startswith("# "):
                feature_title = line[2:].strip()
                break
        # Simple description extraction
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
            # Proceed with empty dict
    
    # Initialize/Update basic fields
    prd_data["feature_id"] = feature_id
    prd_data["title"] = feature_title
    prd_data["description"] = feature_description
    
    # SAVE THE RICH CONTEXT
    prd_data["context"] = spec_context

    if "stories" not in prd_data:
        prd_data["stories"] = []

    # 4. Merge stories
    existing_stories_map = {s["id"]: s for s in prd_data["stories"]}
    merged_stories = []

    for spec in new_stories_specs:
        existing = existing_stories_map.get(spec.id)
        
        # Prepare acceptance criteria (simple default for now, 
        # ideally we could even extract AC from spec.md if we wanted to get fancy with [US] tags,
        # but the full context is now available to the agent via 'context', so we can keep AC simple here)
        ac = spec.acceptance_criteria
        if not ac:
            ac = [f"Verify {spec.title}"] 
            if spec.description:
                ac.append(f"Verify: {spec.description}")
            if spec.user_story_tags:
                 ac.append(f"Related User Stories: {', '.join(spec.user_story_tags)}")

        if existing:
            # Update define fields
            existing["title"] = spec.title
            existing["description"] = spec.description
            existing["acceptance_criteria"] = ac
            # Preserve status, attempts, last_error
            merged_stories.append(existing)
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
    
    # Append the remaining ones from existing_stories_map
    for remaining_id, remaining_story in existing_stories_map.items():
        merged_stories.append(remaining_story)

    # Sort stories by ID
    def sort_key(s):
        m = re.match(r"T(\d+)", s["id"])
        return int(m.group(1)) if m else 9999

    merged_stories.sort(key=sort_key)
    prd_data["stories"] = merged_stories

    # 5. Save PRD
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(prd_data, f, indent=2)
    
    return prd_path

if __name__ == "__main__":
    import argparse
    import sys
    from .git_utils import get_repo_root

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--feature-id", required=True)
    args = parser.parse_args()
    
    try:
        repo_root = get_repo_root()
    except:
        repo_root = Path.cwd()

    print(f"Generating PRD for {args.feature_id} in {repo_root}")
    generate_prd(repo_root, args.feature_id)
