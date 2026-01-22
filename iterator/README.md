# AI Refactor CLI

A global, repo-agnostic CLI tool that runs inside any Git repository to perform AI-driven refactoring.
It uses Ollama (local models) + Aider (coding engine) + CrewAI (orchestration) and integrates with @iannuttall/ralph.

## Prerequisites

- Python 3.11+
- Node.js >= 18 (for Ralph)
- Ollama (running locally)
- Aider (`pipx install aider-chat`)

## Installation

```bash
pipx install .
```

## Usage

```bash
cd /path/to/any/repo
ai-refactor "Refactor error handling"
```

## Configuration

Create a `.ai-refactor.yml` in your repository root:

```yaml
language: python
tests: pytest
branch_prefix: ai
```
