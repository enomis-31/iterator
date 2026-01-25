import os
import warnings
import logging
import re
import json

# Disabilita logging avanzato LiteLLM che richiede fastapi
# Deve essere fatto PRIMA di importare crewai
os.environ.setdefault("LITELLM_LOG", "ERROR")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TELEMETRY_OPT_OUT", "true")

# Filtra warning fastapi
warnings.filterwarnings("ignore", message=".*fastapi.*")
warnings.filterwarnings("ignore", message=".*Missing dependency.*fastapi.*")
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Configura logging per sopprimere errori fastapi di LiteLLM e rumore HTTP
logging.getLogger("litellm").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

from crewai import Agent, Task, Crew, LLM
from typing import Dict, Tuple, List, Optional

# Configure Logger

# Defaults
DEFAULT_CODER_MODEL = "ollama/qwen2.5-coder:14b"
DEFAULT_PLANNER_MODEL = "ollama/llama3.1:8b"

def get_llm(model_name: str, base_url: str = None) -> LLM:
    """Create an LLM instance with optimized parameters."""
    # Context window optimization:
    # With lean context (~4k tokens), 16384 is safe for 16GB VRAM.
    ctx_limit = 16384 if "14b" in model_name.lower() else 8192
    
    return LLM(
        model=model_name, 
        base_url=base_url,
        config={
            "num_ctx": ctx_limit,
            "temperature": 0.0,
            "num_thread": 8
        }
    )

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
        verbose=False,
        allow_delegation=False
    )

def create_critic_agent(model_name: str, base_url: str = None) -> Agent:
    return Agent(
        role="Pragmatic Senior Reviewer",
        goal="Ensure code changes are logically sound and match requirements, even if the environment is missing tools.",
        backstory=(
            "You are a pragmatic senior developer. You understand that sometimes local environments lack testing tools. "
            "Your main focus is the CODE QUALITY and LOGIC in the git diff. If the code looks correct, you approve."
        ),
        llm=get_llm(model_name, base_url=base_url),
        verbose=False,
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

    # Limit spec_context to fit within model's context limit
    if spec_context:
        from .context_manager import limit_context_for_model
        spec_context = limit_context_for_model(
            spec_context,
            model_name,
            reserve_tokens=3000,  # Reserve for prompt, files list, and response
            verbose=False
        )

    description = (
        f"Objective: {task_name}\n"
        f"Context provided: {task_context}\n"
    )
    
    if spec_context:
        description += f"\n=== SPECIFICATION SUMMARY ===\n{spec_context}\n"
        
    description += (
        f"Available Files in Repository:\n{files_list_str}\n\n"
        "IMPORTANT: You are receiving a LEAN CONTEXT. You have the high-level specs and the current story details. "
        "The coding tool (Aider) will be provided with the FULL specification files as read-only context. "
        "Your job is to act as a STRATEGIC PLANNER: Identify WHICH files need modification or creation and WHAT specifically needs to be done in each.\n\n"
        "If code files don't exist yet (e.g. implementing the first user story), you MUST COMMAND Aider to CREATE them. "
        "Aider will automatically create files and directories when instructed.\n\n"
        "Produce a JSON object with two keys:\n"
        "1. 'aider_prompt': A single detailed STRING containing implementation instructions for Aider. "
        "Include technical details, required logic, and reference the specific requirements from the specs. "
        "Instruct Aider to read and follow the detailed requirements in the .md files in the feature directory.\n"
        "2. 'target_files': A list of file paths (full paths from repo root) that need to be CREATED or modified. "
        "Only include code files (not spec files).\n"
        "Use ONLY standard JSON format. Do NOT use markdown code blocks. Do NOT use backslashes at the end of lines."
    )

    planning_task = Task(
        description=description,
        expected_output="JSON string with 'aider_prompt' and 'target_files'.",
        agent=coder
    )
    
    # Filter non-critical LiteLLM errors (fastapi dependency warnings)
    litellm_logger = logging.getLogger("litellm")
    litellm_logger.setLevel(logging.ERROR)
    
    crew = Crew(agents=[coder], tasks=[planning_task], verbose=False)
    result = crew.kickoff()
    
    try:
        # Clean up result if it has markdown formatting
        raw_output = str(result).strip()
        
        # Robust markdown block extraction
        if "```json" in raw_output:
            raw_output = raw_output.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_output:
            raw_output = raw_output.split("```")[1].split("```")[0].strip()
            
        # Attempt to repair common LLM JSON errors
        # 1. Trailing backslashes before newlines in strings
        raw_output = re.sub(r'\\\s*\n', '\n', raw_output)
        
        # 2. Backticks for multiline strings
        if "`" in raw_output:
            # Replace ` at the start of a value (after :)
            raw_output = re.sub(r':\s*`', ': "', raw_output)
            # Replace ` at the end of a value (before , or })
            raw_output = re.sub(r'`\s*([,}])', r'"\1', raw_output)
            
        # 3. Unescaped newlines in strings (this is tricky, but common)
        # We try to find where a string starts with " and doesn't end before the newline
        # This is a very basic attempt at repair
        
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError as jde:
            # If standard parsing fails, try a more aggressive repair for unescaped newlines
            # or missing quotes at end of lines
            logger.debug(f"JSON standard parse failed, attempting aggressive repair: {jde}")
            
            # Remove any control characters that might break JSON parsing (except \n, \r, \t)
            cleaned_output = "".join(ch for ch in raw_output if ch == '\n' or ch == '\r' or ch == '\t' or (ord(ch) >= 32))
            
            # Repairing unescaped newlines inside "key": "value"
            fixed_output = ""
            lines = cleaned_output.splitlines()
            for i, line in enumerate(lines):
                if i > 0 and ":" not in line and not line.strip().startswith('}') and not line.strip().startswith(']'):
                    fixed_output += line.replace('"', '\\"') + "\\n"
                else:
                    fixed_output += line + "\n"
            
            try:
                if fixed_output.endswith("\\n\n"):
                    fixed_output = fixed_output[:-3] + "\n"
                data = json.loads(fixed_output)
                raw_output = fixed_output
            except:
                raise jde

        prompt_val = data.get("aider_prompt", task_name)
        target_files = data.get("target_files", [])
        
        # Ensure target_files are unique
        if isinstance(target_files, list):
            target_files = list(dict.fromkeys(target_files))
        
        # Handle if aider_prompt is a list (common model error)
        if isinstance(prompt_val, list):
            # Convert list of instructions/objects to a single string
            instruction_parts = []
            for item in prompt_val:
                if isinstance(item, dict):
                    # If it's a list of file actions, format them
                    action = item.get("type", "action")
                    path = item.get("path", "unknown")
                    content = item.get("content", "")
                    instruction_parts.append(f"Action: {action} on {path}\nContent:\n{content}\n")
                else:
                    instruction_parts.append(str(item))
            prompt_val = "\n".join(instruction_parts)

        return prompt_val, data.get("target_files", [])
    except Exception as e:
        logger.error(f"Failed to parse coder plan: {e}")
        logger.error(f"Raw output was: {result}")
        # Final fallback: use task_name and try to extract any paths manually
        paths = re.findall(r'["\']?([a-zA-Z0-9_\-/]+\.[a-zA-Z0-9]+)["\']?', str(result))
        # Filter out common false positives
        paths = [p for p in paths if any(p.startswith(d) for d in ['app/', 'lib/', 'src/', 'components/'])]
        return task_name, paths

def critic_review(diff: str, test_log: str, task_name: str, model_name: str = DEFAULT_PLANNER_MODEL, base_url: str = None) -> tuple[str, Optional[str]]:
    """
    Reviews the changes and returns ("SHIP", None) or ("REVISE", reason).
    
    Returns:
        Tuple of (decision, reason) where decision is "SHIP" or "REVISE",
        and reason is None for SHIP or a string explaining why REVISE.
    """
    critic = create_critic_agent(model_name, base_url=base_url)
    
    review_task = Task(
        description=(
            f"Review this task: {task_name}\n\n"
            f"TEST LOG (Might indicate missing tools): \n{test_log[-1000:]}\n\n"
            f"GIT DIFF (Actual code changes): \n{diff[:5000]}\n\n"
            "DIRECTIONS:\n"
            "1. Focus on the GIT DIFF. Is the logic correct? Does it implement the task?\n"
            "2. Ignore 'pytest: command not found' or 'skipped' errors in the test log if the code itself is good.\n"
            "3. If the code is correct, output exactly: SHIP\n"
            "4. If the code has real bugs or missing logic, output: REVISE: <one sentence explanation>\n"
            "Decision:"
        ),
        expected_output="'SHIP' or 'REVISE: <reason>'",
        agent=critic
    )
    
    crew = Crew(agents=[critic], tasks=[review_task], verbose=False)
    result = crew.kickoff()
    
    # Parsare risultato
    result_str = str(result).strip()
    
    # Cerca formato "REVISE: <reason>"
    if result_str.upper().startswith("REVISE:"):
        decision = "REVISE"
        reason = result_str.split(":", 1)[1].strip() if ":" in result_str else None
        return decision, reason
    elif "SHIP" in result_str.upper():
        return "SHIP", None
    else:
        # Fallback: se non riconosciuto, assume REVISE
        return "REVISE", f"Unrecognized response: {result_str}"
