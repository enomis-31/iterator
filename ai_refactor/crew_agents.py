from crewai import Agent, Task, Crew, LLM
from typing import Dict, Tuple, List
import json
import logging
import os

# Configure Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Defaults
DEFAULT_CODER_MODEL = "ollama/qwen2.5-coder:14b"
DEFAULT_PLANNER_MODEL = "ollama/llama3.1:8b"
# Read BASE_URL from environment variable or use default
BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

def get_llm(model_name: str, base_url: str = None) -> LLM:
    """Create an LLM instance with optional base_url override."""
    url = base_url or BASE_URL
    return LLM(model=model_name, base_url=url)

# Agents
def create_coder_agent(model_name: str, base_url: str = None) -> Agent:
    return Agent(
        role="Senior Developer",
        goal="Plan and implement code refactors with precision.",
        backstory=(
            "You are an expert software engineer specializing in refactoring. "
            "You analyze requests and repositories to produce clear, actionable plans for coding tools (like Aider)."
        ),
        llm=get_llm(model_name, base_url=base_url),
        verbose=True,
        allow_delegation=False
    )

def create_critic_agent(model_name: str, base_url: str = None) -> Agent:
    return Agent(
        role="Code Reviewer",
        goal="Verify code changes and test results to ensure quality and correctness.",
        backstory=(
            "You are a strict code reviewer. You look at git diffs and test logs. "
            "You rely on evidence, not intuition. You only approve changes that are correct and safe."
        ),
        llm=get_llm(model_name, base_url=base_url),
        verbose=True,
        allow_delegation=False
    )

# Service Functions

def coder_plan(task_name: str, task_context: str, repo_files: List[str], spec_context: str = "", model_name: str = DEFAULT_CODER_MODEL, base_url: str = None) -> Tuple[str, List[str]]:
    """
    Generates a prompt for Aider and a list of files to edit.
    """
    coder = create_coder_agent(model_name, base_url=base_url)
    
    files_list_str = "\n".join(repo_files[:200]) # Limit to avoid context overflow if huge
    if len(repo_files) > 200:
        files_list_str += "\n... (truncated)"

    description = (
        f"Objective: {task_name}\n"
        f"Context: {task_context}\n"
    )
    
    if spec_context:
        description += f"\n{spec_context}\n"
        
    description += (
        f"Available Files:\n{files_list_str}\n\n"
        "Produce a JSON object with two keys:\n"
        "1. 'aider_prompt': A detailed instruction for the coding tool to execute the refactor. "
        "Reference specific constraints from the Specifications if applicable.\n"
        "2. 'target_files': A list of file paths that likely need modification.\n"
        "Do NOT output markdown code blocks, just the raw JSON string."
    )

    planning_task = Task(
        description=description,
        expected_output="JSON string with 'aider_prompt' and 'target_files'.",
        agent=coder
    )
    
    crew = Crew(agents=[coder], tasks=[planning_task])
    result = crew.kickoff()
    
    try:
        # Clean up result if it has markdown formatting
        raw_output = str(result)
        if "```json" in raw_output:
            raw_output = raw_output.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_output:
            raw_output = raw_output.split("```")[1].split("```")[0].strip()
            
        data = json.loads(raw_output)
        return data.get("aider_prompt", task_name), data.get("target_files", [])
    except Exception as e:
        logger.error(f"Failed to parse coder plan: {e}")
        logger.error(f"Raw output: {result}")
        # Fallback
        return task_name, []

def critic_review(diff: str, test_log: str, task_name: str, model_name: str = DEFAULT_PLANNER_MODEL, base_url: str = None) -> str:
    """
    Reviews the changes and returns "SHIP" or "REVISE".
    """
    critic = create_critic_agent(model_name, base_url=base_url)
    
    review_task = Task(
        description=(
            f"Task: {task_name}\n\n"
            f"Test logs:\n{test_log[-2000:]}\n\n" # Truncate logs
            f"Git Diff:\n{diff[:5000]}\n\n" # Truncate diff
            "Analyze the above. If tests passed and the code changes look correct and safe, output 'SHIP'. "
            "If tests failed or there are logical errors, output 'REVISE'. "
            "Output ONLY the decision word."
        ),
        expected_output="'SHIP' or 'REVISE'",
        agent=critic
    )
    
    crew = Crew(agents=[critic], tasks=[review_task])
    result = crew.kickoff()
    
    decision = str(result).strip().upper()
    if "SHIP" in decision:
        return "SHIP"
    return "REVISE"
