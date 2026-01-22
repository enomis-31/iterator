# AI Refactor Ecosystem Setup Guide

This document provides a comprehensive step-by-step guide to setting up the **AI Refactor** environment, including all external dependencies (Ollama, Aider, Ralph, Spec Kit) and the `ai-refactor` CLI tool itself.

## 1. Prerequisites Installation

### 1.1. System Requirements
- **OS**: Linux / macOS
- **Python**: 3.11 or higher
- **Node.js**: 18 or higher (for Ralph)
- **Git**: Installed and configured
- **Hardware**: Sufficient RAM/VRAM to run your chosen LLMs (models run sequentially, not in parallel).

### 1.2. Install Ollama (Local LLM Runtime)
1. **Install**: Follow instructions at [ollama.com](https://ollama.com/).
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```
2. **Pull Models**:
   You can choose any models available on Ollama. We recommend:
   ```bash
   # Coder Model (Good at Python/JS)
   ollama pull qwen2.5-coder:14b
   
   # Planner/Critic Model (Good at logic/reasoning)
   ollama pull llama3.1:8b
   # OR for better reasoning (requires more RAM):
   ollama pull llama3.3:70b
   ```
3. **Verify**: Ensure Ollama is running (`systemctl status ollama` or just run `ollama serve`).

### 1.3. Install Aider (AI Coding Assistant)
We recommend `pipx` for isolating CLI tools.
```bash
pipx install aider-chat
```

**Configure Aider** (`~/.aider.conf.yml`):
Create or edit this file to point Aider to your local Ollama instance by default.
```yaml
model: ollama/qwen2.5-coder:14b
openai-api-base: http://localhost:11434/v1
openai-api-key: "ollama"
no-auto-commits: true  # ai-refactor handles commits
```

### 1.4. Install Ralph (Agent Loop CLI)
Ralph comes from `@iannuttall/ralph`.
```bash
npm install -g @iannuttall/ralph
```

### 1.5. Install Spec Kit (Specification Generator)
Used to generate structured tasks and specs.
```bash
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
# OR if uv is not available:
pipx install git+https://github.com/github/spec-kit.git
```

## 2. Installation of `ai-refactor`

1. **Navigate to the project source**:
   ```bash
   cd /path/to/multi-repo-ai-refactor
   ```

2. **Install globally via pipx**:
   ```bash
   pipx install .
   ```
   *Alternatively, for development/editing:*
   ```bash
   pip install -e .
   ```

3. **Verify installation**:
   ```bash
   ai-refactor --help
   ai-refactor-agent --help
   ```

## 3. Configuration & Usage (Per-Repository)

To use this tool on a target repository (e.g., `my-legacy-app`), follow these steps inside that repo.

### 3.1. Basic `ai-refactor` Setup
Create a `.ai-refactor.yml` in the root of `my-legacy-app`.

#### Model Configuration
You can specify exactly which Ollama models to use. This allows you to use a lightweight model for coding and a heavy, "smart" model for planning/critique.

**Note**: The tool runs models **sequentially**. First the Planner runs, then it unloads. Then the Coder runs. This means you do NOT need hardware capable of running both simultaneously.

```yaml
language: python
tests: "pytest tests/"
branch_prefix: "ai-refactor"

# Configure your specific models here
models:
  coder: "ollama/qwen2.5-coder:14b"
  planner: "ollama/llama3.1:8b" 
  # planner: "ollama/wangshenzhi/os-copilot-20b" # Example of using a larger model for planning

spec_kit:
  enabled: true
  specs_dir: "specs"

task_presets:
  modernize:
    prompt: "Update code to use Python 3.11 features, specifically type hinting."
```

### 3.2. Spec Kit Setup (Optional but Recommended)
Initialize Spec Kit to generate your "Source of Truth".
```bash
# In target repo
mkdir specs
# Add your specs manually or use specify-cli to generate them
# echo "My Project Constitution..." > specs/constitution.md
```

### 3.3. Ralph Integration Setup
Initialize Ralph in the target repository to run iterative loops.

1. **Install Ralph locally**:
   ```bash
   ralph install
   ralph install --skills # Optional standard skills
   ```
2. **Configure Ralph to use `ai-refactor`**:
   Edit `.agents/ralph/config.sh`:
   ```bash
   # Use our adapter as the agent command
   AGENT_CMD="ai-refactor-agent --from-prompt {prompt}"
   ```

## 4. Testing the Workflow

### Scenario A: Single Shot Refactor
Run a specific task immediately without the full Ralph loop.
```bash
cd /path/to/my-legacy-app
ai-refactor "Refactor the authentication module to use verify_token function"
```
**What happens:**
1. **Plan**: Planner Agent (e.g., Llama 3.1) analyzes files and creates a plan.
2. **Code**: Coder Agent (e.g., Qwen 2.5 Coder) executes changes via Aider.
3. **Test**: Runs your configured test command.
4. **Review**: Planner/Critic Agent (e.g., Llama 3.1) reviews the diff and test logs.
5. **Ship**: If approved, commits changes.

### Scenario B: Ralph Loop (Autonomous)
1. **Define a Task/Story** in Ralph's format (e.g., in `.agents/tasks/prd-001.json` or just use `ralph build`).
2. **Run the Loop**:
   ```bash
   ralph build 1
   ```

### Scenario C: Spec Kit Driven
1. Create a spec file `specs/feature-x.md`.
2. Run `ai-refactor` (it will auto-load `specs/*.md` as context for the Coder/Planner).
   ```bash
   ai-refactor "Implement Feature X according to specs"
   ```

## 5. Troubleshooting
- **Ollama Connection Refused**: Check if `ollama serve` is running.
- **Aider Error**: Ensure `aider` is in your PATH (`pipx ensurepath`).
- **Tests Failing**: Check `tests` command in `.ai-refactor.yml`.
- **Model not found**: Run `ollama list` to see installed models and update `.ai-refactor.yml` to match.
