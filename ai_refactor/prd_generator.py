import json
import logging
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

@dataclass
class UserStorySpec:
    """Represents a User Story extracted from spec.md"""
    id: str  # "US1", "US2", "US3"
    title: str
    description: str
    priority: str  # "P1", "P2", "P3"
    acceptance_scenarios: List[str]
    independent_test: str

    def __post_init__(self):
        if self.acceptance_scenarios is None:
            self.acceptance_scenarios = []

@dataclass
class TaskSpec:
    """Represents a Task extracted from tasks.md"""
    id: str  # "T001", "T002", etc.
    title: str
    description: str
    user_story_tags: List[str]  # ["US1"], ["US2"], etc.
    is_parallel: bool  # from [P] tag

    def __post_init__(self):
        if self.user_story_tags is None:
            self.user_story_tags = []

# Legacy class for backward compatibility (deprecated)
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

def parse_user_stories_from_spec(spec_content: str) -> List[UserStorySpec]:
    """
    Parses spec.md content to extract User Stories (US1, US2, US3, etc.).
    
    Pattern: ### User Story N - [Title] (Priority: PX)
    
    Extracts:
    - Story ID (US1, US2, US3)
    - Title (from header)
    - Description (the "As a user..." paragraph)
    - Priority (P1, P2, P3)
    - Acceptance Scenarios (from "**Acceptance Scenarios**:" section)
    - Independent Test description
    """
    stories = []
    
    # Pattern to match User Story headers: "### User Story 1 - Title (Priority: P1)"
    us_header_pattern = re.compile(
        r"^###\s+User\s+Story\s+(\d+)\s*-\s*(.+?)\s*\(Priority:\s*(P\d+)\)",
        re.IGNORECASE
    )
    
    lines = spec_content.splitlines()
    i = 0
    
    while i < len(lines):
        line = lines[i]
        header_match = us_header_pattern.match(line)
        
        if header_match:
            story_num = header_match.group(1)
            story_id = f"US{story_num}"
            title = header_match.group(2).strip()
            priority = header_match.group(3).strip()
            
            # Initialize story data
            description = ""
            independent_test = ""
            acceptance_scenarios = []
            
            # Move to next line and start parsing content
            i += 1
            
            # Parse description (usually the "As a user..." paragraph)
            while i < len(lines):
                line = lines[i].strip()
                
                # Stop at next section markers
                if line.startswith("**Why this priority") or line.startswith("**Independent Test"):
                    break
                if line.startswith("###") or line.startswith("##"):
                    break
                if not line:
                    i += 1
                    continue
                
                # Collect description lines
                if description:
                    description += " " + line
                else:
                    description = line
                i += 1
            
            # Parse "Why this priority" section (skip it)
            if i < len(lines) and "**Why this priority" in lines[i]:
                while i < len(lines) and "**Independent Test" not in lines[i]:
                    i += 1
            
            # Parse "Independent Test" section
            if i < len(lines) and "**Independent Test" in lines[i]:
                i += 1
                test_lines = []
                while i < len(lines):
                    line = lines[i].strip()
                    if line.startswith("**Acceptance Scenarios") or line.startswith("###") or line.startswith("##"):
                        break
                    if line:
                        test_lines.append(line)
                    i += 1
                independent_test = " ".join(test_lines)
            
            # Parse "Acceptance Scenarios" section
            if i < len(lines) and "**Acceptance Scenarios**" in lines[i]:
                i += 1
                scenario_lines = []
                current_scenario = ""
                
                while i < len(lines):
                    line = lines[i].strip()
                    
                    # Stop at next major section
                    if line.startswith("###") or line.startswith("##"):
                        if current_scenario:
                            acceptance_scenarios.append(current_scenario.strip())
                        break
                    
                    # Check for numbered scenarios (1. **Given** ...)
                    if re.match(r"^\d+\.\s*\*\*", line):
                        # Save previous scenario if exists
                        if current_scenario:
                            acceptance_scenarios.append(current_scenario.strip())
                        current_scenario = line
                    elif current_scenario and line:
                        # Continue current scenario
                        current_scenario += " " + line
                    elif not current_scenario and line and not line.startswith("---"):
                        # Might be a scenario without number
                        current_scenario = line
                    
                    i += 1
                
                # Add last scenario
                if current_scenario:
                    acceptance_scenarios.append(current_scenario.strip())
            
            # Create UserStorySpec
            story = UserStorySpec(
                id=story_id,
                title=title,
                description=description,
                priority=priority,
                acceptance_scenarios=acceptance_scenarios,
                independent_test=independent_test
            )
            stories.append(story)
        
        i += 1
    
    return stories

def parse_tasks_md(tasks_path: Path) -> List[TaskSpec]:
    """
    Parses a tasks.md file and returns a list of TaskSpec objects.
    Captures [USx] tags to link tasks to specific user stories.
    """
    if not tasks_path.exists():
        logger.warning(f"Tasks file not found: {tasks_path}")
        return []

    tasks = []
    current_task = None
    
    # Regex to match task lines like "- [ ] T1: Title" or "- [x] T1 [P] [US1] Title"
    # Captures: 1=id, 2=title_with_tags
    task_pattern = re.compile(r"^\s*-\s*\[[ xX]\]\s*(T\d+)\s*(?:\[P\]\s*)?(?:\[(US\d+)\]\s*)?(?:\[P\]\s*)?(.*)$")
    
    # Regex to find [USx] tags (for cases where tag appears anywhere in title)
    us_tag_pattern = re.compile(r"\[(US\d+)\]")
    
    # Regex to find [P] tag (parallel marker)
    parallel_pattern = re.compile(r"\[P\]")

    # Regex to match description lines like "  - Description: ..."
    desc_pattern = re.compile(r"^\s*-\s*Description:\s*(.+)$", re.IGNORECASE)

    with open(tasks_path, "r", encoding="utf-8") as f:
        for line in f:
            line_stripped = line.rstrip()
            
            # Check for new task
            task_match = task_pattern.match(line_stripped)
            if task_match:
                # Save previous task if exists
                if current_task:
                    tasks.append(current_task)
                
                task_id = task_match.group(1)
                raw_title = task_match.group(3) if task_match.group(3) else ""
                
                # Extract US tags from title (check both group 2 and full title)
                us_tags = []
                if task_match.group(2):  # US tag in group 2
                    us_tags.append(task_match.group(2))
                # Also search entire title for US tags
                us_tags.extend(us_tag_pattern.findall(raw_title))
                us_tags = list(set(us_tags))  # Remove duplicates
                
                # Check for [P] tag (parallel marker)
                is_parallel = bool(parallel_pattern.search(line_stripped))
                
                # Clean title - remove [P] and [USx] tags for cleaner display
                title = raw_title.strip()
                title = parallel_pattern.sub("", title).strip()
                title = us_tag_pattern.sub("", title).strip()
                title = re.sub(r"\s+", " ", title)  # Normalize whitespace
                
                current_task = TaskSpec(
                    id=task_id,
                    title=title,
                    description="",
                    user_story_tags=us_tags,
                    is_parallel=is_parallel
                )
                continue
            
            # Check for description if inside a task
            if current_task:
                desc_match = desc_pattern.match(line_stripped)
                if desc_match:
                    current_task.description = desc_match.group(1).strip()

    # Append the last task
    if current_task:
        tasks.append(current_task)

    return tasks

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
            
    # Sort files in logical order: spec.md → plan.md → data-model.md → research.md → quickstart.md → contracts/*
    def sort_key(item):
        path_str = item[0].lower()
        # Define priority order
        priority_map = {
            "spec.md": "0",
            "plan.md": "1",
            "data-model.md": "2",
            "research.md": "3",
            "quickstart.md": "4"
        }
        
        # Check if it's a contracts file
        if path_str.startswith("contracts/"):
            # Sort contracts alphabetically after other files
            return "5_" + path_str
        elif path_str in priority_map:
            return priority_map[path_str] + "_" + path_str
        else:
            # Other files go after priority files but before contracts
            return "4.5_" + path_str

    found_files.sort(key=sort_key)

    # File type descriptions for better context
    file_descriptions = {
        "spec.md": "Feature specification with user stories, requirements, and acceptance criteria",
        "plan.md": "Implementation plan with technical architecture and design decisions",
        "data-model.md": "Data model definitions and entity relationships",
        "research.md": "Research findings and technical decision rationale",
        "quickstart.md": "Quick start guide for implementation and testing"
    }

    for rel_path, full_path in found_files:
        try:
            content = full_path.read_text(encoding="utf-8")
            # Store in map using relative path as key
            context_data["files"][rel_path] = content
            
            # Get file description if available
            file_desc = file_descriptions.get(rel_path.lower(), "Specification document")
            
            # Count lines for metadata
            line_count = len(content.splitlines())
            
            # Append to full text with improved formatting
            header = f"\n\n{'='*40}\nFILE: {rel_path}\nTYPE: {file_desc}\nLINES: {line_count}\n{'='*40}\n\n"
            full_text_parts.append(header + content)
            
        except Exception as e:
            logger.warning(f"Failed to read spec file {rel_path}: {e}")

    # Join with proper spacing (ensure no double newlines at start)
    concatenated = "".join(full_text_parts)
    # Clean up any excessive newlines at the beginning
    concatenated = concatenated.lstrip()
    
    context_data["full_concatenation"] = concatenated
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

    # 1. Extract global info (Title, Description) & Context
    # We use the intelligent aggregator now
    spec_context = load_spec_documents(feature_dir)
    
    # 2. Parse User Stories from spec.md
    user_stories = []
    if "spec.md" in spec_context["files"]:
        spec_content = spec_context["files"]["spec.md"]
        user_stories = parse_user_stories_from_spec(spec_content)
        if not user_stories:
            logger.warning(f"No user stories found in spec.md for feature {feature_id}")
    else:
        logger.warning(f"spec.md not found in {feature_dir}")
    
    # 3. Parse Tasks from tasks.md (for linking to user stories)
    tasks = parse_tasks_md(tasks_path)
    
    # 4. Extract title and description from spec.md
    feature_title = f"Feature {feature_id}"
    feature_description = "See full context."
    
    if "spec.md" in spec_context["files"]:
        spec_content = spec_context["files"]["spec.md"]
        lines = spec_content.splitlines()
        
        # Extract title from "# Feature Specification: [Title]" pattern
        for line in lines:
            if line.startswith("# "):
                # Try to extract from "Feature Specification: [Title]" pattern
                title_match = re.search(r"Feature\s+Specification:\s*(.+)$", line, re.IGNORECASE)
                if title_match:
                    feature_title = title_match.group(1).strip()
                else:
                    # Fallback to everything after "# "
                    feature_title = line[2:].strip()
                break
        
        # Extract description from "**Input**: User description: ..." field
        desc_pattern = re.compile(r"\*\*Input\*\*:\s*User\s+description:\s*[\"'](.+?)[\"']", re.IGNORECASE | re.DOTALL)
        desc_match = desc_pattern.search(spec_content)
        
        if desc_match:
            feature_description = desc_match.group(1).strip()
            # Limit description length to 500 chars, but preserve important context
            if len(feature_description) > 500:
                feature_description = feature_description[:497] + "..."
        else:
            # Fallback: extract first meaningful paragraph after title
            desc_lines = []
            in_description = False
            for line in lines:
                if line.startswith("#"):
                    in_description = True
                    continue
                if in_description and line.strip() and not line.strip().startswith("**"):
                    desc_lines.append(line.strip())
                    if len(desc_lines) >= 3:  # Get first 3 lines
                        break
            if desc_lines:
                feature_description = " ".join(desc_lines)
                if len(feature_description) > 500:
                    feature_description = feature_description[:497] + "..."

    # 5. Load or Create PRD data
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
    
    # Preserve ralph_metadata if it exists (loop-managed)
    if "ralph_metadata" not in prd_data:
        prd_data["ralph_metadata"] = {}
    
    # SAVE THE RICH CONTEXT
    prd_data["context"] = spec_context

    if "stories" not in prd_data:
        prd_data["stories"] = []

    # 6. Build task index by user story for linking
    tasks_by_story: Dict[str, List[str]] = {}
    for task in tasks:
        for us_tag in task.user_story_tags:
            if us_tag not in tasks_by_story:
                tasks_by_story[us_tag] = []
            tasks_by_story[us_tag].append(task.id)

    # 7. Merge User Stories into PRD
    existing_stories_map = {s["id"]: s for s in prd_data["stories"]}
    merged_stories = []

    for user_story in user_stories:
        existing = existing_stories_map.get(user_story.id)
        
        # Get linked tasks for this user story
        linked_task_ids = tasks_by_story.get(user_story.id, [])
        
        # Prepare acceptance criteria from acceptance scenarios
        ac = user_story.acceptance_scenarios.copy()
        if not ac:
            # Fallback if no scenarios found
            ac = [f"Verify {user_story.title}"]

        if existing:
            # Update fields from spec.md but preserve loop-managed fields
            existing["title"] = user_story.title
            existing["description"] = user_story.description
            existing["priority"] = user_story.priority
            existing["acceptance_criteria"] = ac
            existing["independent_test"] = user_story.independent_test
            if linked_task_ids:
                existing["tasks"] = linked_task_ids
            
            # Preserve loop-managed fields: status, attempts, last_error, last_updated_at, max_attempts
            # These are only set/updated by the Ralph loop, not by the PRD generator
            # (status, attempts, last_error are already preserved by not overwriting)
            # last_updated_at and max_attempts are also preserved if they exist
            
            merged_stories.append(existing)
            del existing_stories_map[user_story.id]
        else:
            # Create new story from User Story
            new_story = {
                "id": user_story.id,
                "title": user_story.title,
                "description": user_story.description,
                "priority": user_story.priority,
                "acceptance_criteria": ac,
                "independent_test": user_story.independent_test,
                "tasks": linked_task_ids if linked_task_ids else [],
                "status": "todo",
                "attempts": 0,
                "last_error": None
            }
            merged_stories.append(new_story)
    
    # Append remaining stories from existing PRD (for backward compatibility with old task-based stories)
    for remaining_id, remaining_story in existing_stories_map.items():
        # Only keep if it's not a User Story ID (to avoid duplicates)
        if not re.match(r"^US\d+$", remaining_id):
            merged_stories.append(remaining_story)

    # Sort stories by priority (P1, P2, P3) then by ID
    def sort_key(s):
        priority_order = {"P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5}
        priority = s.get("priority", "P9")
        priority_num = priority_order.get(priority, 99)
        
        # Extract number from ID (US1 -> 1, US2 -> 2, etc.)
        id_match = re.match(r"US(\d+)", s.get("id", ""))
        id_num = int(id_match.group(1)) if id_match else 9999
        
        return (priority_num, id_num)

    merged_stories.sort(key=sort_key)
    prd_data["stories"] = merged_stories

    # 8. Save PRD
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(prd_data, f, indent=2)
    
    logger.info(f"Generated PRD with {len(merged_stories)} user stories for feature {feature_id}")
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
