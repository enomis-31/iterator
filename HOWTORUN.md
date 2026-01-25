# How to Run: Ralph Loop Execution Guide

**Purpose**: This guide explains how to execute the Ralph-style autonomous loop for implementing features from Spec Kit PRD files.

**Prerequisites**: 
- Spec Kit feature directory with `spec.md`, `tasks.md`, and other spec files
- PRD generator has been run to create `prd.json`
- AI Refactor Tool configured (`.ai-refactor.yml`)

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Execution Modes](#execution-modes)
3. [Workflow Overview](#workflow-overview)
4. [Step-by-Step Workflow](#step-by-step-workflow)
5. [Testing Workflow](#testing-workflow)
6. [Common Scenarios](#common-scenarios)
7. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Minimal Workflow

```bash
# 1. Generate PRD from Spec Kit files
python -m ai_refactor.prd_generator --feature-id 001-event-notifications

# 2. Run single iteration (default mode)
python -m ai_refactor.ralph_adapter --feature-id 001-event-notifications --mode once

# 3. Run full loop
python -m ai_refactor.ralph_adapter --feature-id 001-event-notifications --mode loop
```

---

## Execution Modes

### Mode: `once` (Single Iteration)

**Purpose**: Execute one story implementation attempt, then exit.

**Use Cases**:
- Testing the loop with a single story
- Manual review after each iteration
- Debugging specific stories
- Incremental development workflow

**Behavior**:
1. Loads existing PRD (does NOT generate it)
2. Selects next eligible story (by priority, status, ID)
3. Executes implementation for that story
4. Updates PRD with result
5. Exits immediately

**Example**:
```bash
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once
```

**Output**: One story processed, PRD updated, summary printed.

---

### Mode: `loop` (Full Autonomous Loop)

**Purpose**: Continuously iterate through stories until completion or limits reached.

**Use Cases**:
- Autonomous implementation of entire feature
- Batch processing multiple stories
- Continuous integration scenarios

**Behavior**:
1. Loads existing PRD
2. Loops until:
   - All stories have `status == "pass"`, OR
   - `max_iterations` reached, OR
   - All remaining stories exhausted (max attempts reached)
3. Each iteration:
   - Selects next story
   - Executes implementation
   - Updates PRD state
   - Logs progress
4. Prints final summary

**Example**:
```bash
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode loop \
  --max-iterations 10
```

**Output**: Multiple iterations, PRD updated after each, final summary.

---

## Workflow Overview

### High-Level Flow

```
┌─────────────────┐
│ 1. Generate PRD │  (prd_generator.py)
│   from Spec Kit │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 2. Review PRD   │  (optional: check prd.json)
│   stories       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 3. Run Ralph    │  (ralph_adapter.py)
│   Loop          │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 4. Monitor      │  (check logs, PRD updates)
│   Progress      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 5. Review       │  (check git commits, test results)
│   Results       │
└─────────────────┘
```

### Story State Machine

```
todo ──────────► in_progress ──────────► pass
                      │
                      │ (failure)
                      ▼
                   in_progress (retry)
                      │
                      │ (max attempts)
                      ▼
                    fail
```

**State Transitions**:
- `todo` → `in_progress`: When story is selected for execution
- `in_progress` → `pass`: On successful implementation (SHIP + tests_ok)
- `in_progress` → `in_progress`: On failure, if attempts < max_attempts
- `in_progress` → `fail`: On failure, if attempts >= max_attempts

---

## Step-by-Step Workflow

### Phase 1: Prepare Spec Kit Files

Ensure your feature directory has the required Spec Kit files:

```bash
specs/001-event-notifications/
├── spec.md              # User stories (US1, US2, US3, ...)
├── tasks.md             # Implementation tasks (T001, T002, ...)
├── plan.md              # Technical plan
├── data-model.md        # Data model (optional)
├── research.md          # Research notes (optional)
├── quickstart.md        # Quick start guide (optional)
└── contracts/           # Service contracts (optional)
    └── *.md
```

### Phase 2: Generate PRD

**First Time Setup**:
```bash
# From repository root
python -m ai_refactor.prd_generator --feature-id 001-event-notifications
```

**What Happens**:
- Reads `spec.md` and extracts User Stories (US1, US2, US3, ...)
- Reads `tasks.md` and links tasks to stories via `[USx]` tags
- Stores each spec file's content in the `context.files` dictionary within `prd.json`.
- Creates/updates `specs/001-event-notifications/prd.json`
- *Note*: Redundant full concatenation is avoided to keep the PRD lean.

**Verify PRD**:
```bash
# Check that PRD was generated correctly
cat specs/001-event-notifications/prd.json | jq '.stories[] | {id, title, priority, status}'
```

**Expected Output**:
```json
{
  "id": "US1",
  "title": "Receive Notification When Event Time Arrives",
  "priority": "P1",
  "status": "todo"
}
```

### Phase 3: Run Ralph Loop

#### Option A: Single Iteration (Recommended for Testing)

```bash
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once \
  --verbose
```

**What Happens**:
1. Loads PRD from `specs/001-event-notifications/prd.json`
2. Selects highest priority story with `status="todo"` (e.g., US1 with P1)
3. Marks story as `in_progress`, increments `attempts`
4. Builds a **lean context** for planning (Story details + `tasks.md` + file manifest).
5. Calls `workflow.run_once()` which:
   - Uses a **Planner Agent** to create a strategy.
   - Executes **Aider** with the full specifications passed as **read-only context** (`--read`).
6. Updates story status based on result:
   - Success → `status="pass"`, `last_error=null`
   - Failure → `status="in_progress"` or `"fail"`, `last_error` set
7. Saves updated PRD
8. Prints summary and exits

**Output Example**:
```
Starting Ralph Loop for feature: 001-event-notifications (mode: once)
PRD loaded successfully from specs/001-event-notifications/prd.json
--- Iteration 1 ---
Selected story: US1 - Receive Notification When Event Time Arrives
Story US1 marked as in_progress (attempt 1)
...
Story US1 PASSED (attempt 1)

--- Ralph Loop Summary ---
Feature: 001-event-notifications
Iterations: 1
Stories total: 2
Stories pass: 1
Stories fail: 0
```

#### Option B: Full Loop

```bash
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode loop \
  --max-iterations 5 \
  --max-attempts-per-story 3 \
  --verbose
```

**What Happens**:
- Same as single iteration, but repeats until:
  - All stories pass, OR
  - 5 iterations completed, OR
  - All stories exhausted

#### Option C: Target Specific Story

```bash
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once \
  --story-id US2 \
  --verbose
```

**What Happens**:
- Loads PRD
- Finds story with `id="US2"`
- Executes only that story (if eligible)
- Exits

**Use Case**: Retry a specific story that failed, or test a lower-priority story.

### Phase 4: Monitor Progress

**Check PRD Status**:
```bash
# View all story statuses
cat specs/001-event-notifications/prd.json | jq '.stories[] | {id, status, attempts, last_error}'
```

**Check Git History**:
```bash
# View commits made by the loop
git log --oneline --grep="refactor:" --all

# View branches created
git branch -a | grep ai-refactor
```

**Check Logs**:
- Console output shows real-time progress
- With `--verbose`, see detailed debug information

### Phase 5: Review Results

**Success Indicators**:
- Story `status="pass"` in PRD
- Git commit created (if `--auto-commit`)
- Tests passing (if not `--no-tests`)

**Failure Indicators**:
- Story `status="fail"` in PRD
- `last_error` field contains error message
- `attempts` field shows number of retries

**Next Steps**:
- If story passed: Loop continues to next story (or exits if `mode=once`)
- If story failed: Review `last_error`, fix issues, regenerate PRD if needed, retry

---

## Testing Workflow

### Test Scenario 1: Single Story Execution

**Goal**: Verify single iteration mode works correctly.

**Steps**:
```bash
# 1. Generate PRD
python -m ai_refactor.prd_generator --feature-id 001-event-notifications

# 2. Verify PRD has stories
cat specs/001-event-notifications/prd.json | jq '.stories | length'

# 3. Run single iteration
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once \
  --verbose

# 4. Check PRD was updated
cat specs/001-event-notifications/prd.json | jq '.stories[0] | {id, status, attempts}'
```

**Expected**:
- One story processed
- Story status changed from `todo` to `in_progress` then `pass` or `fail`
- `attempts` incremented to 1
- PRD file updated

---

### Test Scenario 2: Priority Ordering

**Goal**: Verify stories are selected by priority (P1 before P2).

**Steps**:
```bash
# 1. Ensure PRD has stories with different priorities
# (e.g., US1 with P1, US2 with P2, both status="todo")

# 2. Run single iteration
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once

# 3. Verify US1 (P1) was selected, not US2 (P2)
cat specs/001-event-notifications/prd.json | jq '.stories[] | select(.status=="in_progress" or .status=="pass") | {id, priority}'
```

**Expected**:
- US1 (P1) selected first, even if US2 appears earlier in array
- US2 remains `status="todo"`

---

### Test Scenario 3: Story Retry After Failure

**Goal**: Verify failed stories can be retried.

**Steps**:
```bash
# 1. Run iteration that will fail (e.g., story with impossible requirements)
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once \
  --story-id US1

# 2. Verify story marked as in_progress (not fail) if attempts < max
cat specs/001-event-notifications/prd.json | jq '.stories[] | select(.id=="US1") | {status, attempts, last_error}'

# 3. Run again (should retry same story)
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once

# 4. Verify attempts incremented
cat specs/001-event-notifications/prd.json | jq '.stories[] | select(.id=="US1") | {attempts}'
```

**Expected**:
- Story status remains `in_progress` if attempts < max_attempts_per_story
- `attempts` increments on each retry
- `last_error` contains error message

---

### Test Scenario 4: Max Attempts Limit

**Goal**: Verify stories are marked as `fail` after max attempts.

**Steps**:
```bash
# 1. Run with low max attempts
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode loop \
  --max-attempts-per-story 2 \
  --story-id US1

# 2. Manually set story attempts to 1 (to simulate previous attempts)
# Edit prd.json: set story.attempts = 1, status = "in_progress"

# 3. Run iteration (will fail, attempts becomes 2)
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once \
  --story-id US1

# 4. Run again (attempts becomes 3, exceeds max_attempts_per_story=2)
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once \
  --story-id US1

# 5. Verify story marked as fail
cat specs/001-event-notifications/prd.json | jq '.stories[] | select(.id=="US1") | {status, attempts}'
```

**Expected**:
- After 2 failed attempts, story `status="fail"`
- Story no longer selected by `select_next_story()`

---

### Test Scenario 5: Full Loop Execution

**Goal**: Verify loop processes multiple stories in priority order.

**Steps**:
```bash
# 1. Ensure PRD has multiple stories (all status="todo")
python -m ai_refactor.prd_generator --feature-id 001-event-notifications

# 2. Run loop with iteration limit
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode loop \
  --max-iterations 3 \
  --verbose

# 3. Verify multiple stories processed
cat specs/001-event-notifications/prd.json | jq '.stories[] | {id, status, attempts}'
```

**Expected**:
- 3 iterations executed
- Stories processed in priority order (P1 → P2 → P3)
- PRD updated after each iteration

---

### Test Scenario 6: Context Injection

**Goal**: Verify story context is properly injected into agents.

**Steps**:
```bash
# 1. Run with verbose logging
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once \
  --verbose

# 2. Check logs for context information
# Look for: "Story context length: X characters"
# Look for: "Enhanced context with story context"
```

**Expected**:
- Logs show story context being built
- Logs show context enhancement in workflow
- Agents receive both story-specific and general spec context

---

## Common Scenarios

### Scenario: First Time Running on a Feature

```bash
# 1. Generate PRD (required first step)
python -m ai_refactor.prd_generator --feature-id 001-event-notifications

# 2. Review PRD to understand stories
cat specs/001-event-notifications/prd.json | jq '.stories[] | {id, title, priority}'

# 3. Run single iteration to test
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once \
  --verbose

# 4. Review results
cat specs/001-event-notifications/prd.json | jq '.stories[0] | {status, attempts, last_error}'

# 5. If successful, run full loop
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode loop \
  --max-iterations 10
```

---

### Scenario: Retrying a Failed Story

```bash
# 1. Check which story failed
cat specs/001-event-notifications/prd.json | jq '.stories[] | select(.status=="fail") | {id, last_error, attempts}'

# 2. Review error message
cat specs/001-event-notifications/prd.json | jq '.stories[] | select(.id=="US1") | .last_error'

# 3. Fix underlying issue (code, tests, etc.)

# 4. Manually reset story status (optional)
# Edit prd.json: set status="todo", attempts=0, last_error=null

# 5. Retry specific story
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once \
  --story-id US1
```

---

### Scenario: Testing Lower Priority Story First

```bash
# 1. Target specific story (e.g., US3 with P3)
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once \
  --story-id US3

# 2. Verify only US3 was processed
cat specs/001-event-notifications/prd.json | jq '.stories[] | select(.id=="US3") | {status, attempts}'
```

---

### Scenario: Autonomous Implementation (CI/CD)

```bash
# Run full loop with auto-commit
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode loop \
  --max-iterations 20 \
  --max-attempts-per-story 3 \
  --auto-commit \
  --verbose
```

**Note**: Use `--auto-commit` carefully. It automatically commits changes when stories pass.

---

## Troubleshooting

### Issue: "PRD file not found"

**Error**:
```
FileNotFoundError: PRD file not found: specs/001-event-notifications/prd.json
Please run the PRD generator first...
```

**Solution**:
```bash
# Generate PRD first
python -m ai_refactor.prd_generator --feature-id 001-event-notifications
```

---

### Issue: "No eligible stories found"

**Possible Causes**:
- All stories have `status="pass"`
- All stories exceeded `max_attempts_per_story`
- Stories have invalid status values

**Solution**:
```bash
# Check story statuses
cat specs/001-event-notifications/prd.json | jq '.stories[] | {id, status, attempts}'

# Reset stories if needed (edit prd.json manually)
# Or use --force to retry passed stories
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once \
  --force
```

---

### Issue: Story Stuck in "in_progress"

**Cause**: Loop was interrupted before story completed.

**Solution**:
```bash
# Option 1: Let loop retry (in_progress stories are retried)
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once

# Option 2: Manually reset (edit prd.json: status="todo")
```

---

### Issue: Wrong Story Selected

**Cause**: Story selection logic may not match expectations.

**Debug**:
```bash
# Run with verbose to see selection details
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once \
  --verbose

# Check story priorities and statuses
cat specs/001-event-notifications/prd.json | jq '.stories[] | {id, priority, status, attempts}'
```

**Solution**: Use `--story-id` to target specific story, or adjust priorities in `spec.md` and regenerate PRD.

---

### Issue: Context Not Being Used

**Symptoms**: Agents don't seem to have story context.

**Debug**:
```bash
# Run with verbose logging
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode once \
  --verbose

# Look for: "Story context length: X characters"
# The Planner should show "Using lean context" messages.
```

**Solution**: Ensure `spec_kit.enabled: true` in `.ai-refactor.yml`.

---

### Issue: PRD Gets Regenerated and Loses State

**Cause**: Accidentally running `prd_generator` after loop started.

**Solution**: 
- `generate_prd()` preserves loop-managed fields (`status`, `attempts`, `last_error`)
- But avoid regenerating PRD while loop is running
- If needed, regenerate PRD only when spec files change

---

## Advanced Usage

### Combining with Git Workflow

```bash
# 1. Create feature branch
git checkout -b feature/001-event-notifications

# 2. Generate PRD
python -m ai_refactor.prd_generator --feature-id 001-event-notifications

# 3. Run loop (with auto-commit)
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode loop \
  --auto-commit

# 4. Review commits
git log --oneline

# 5. Create PR when done
git push origin feature/001-event-notifications
```

---

### Monitoring Progress Over Time

```bash
# Watch PRD status changes
watch -n 5 'cat specs/001-event-notifications/prd.json | jq ".stories[] | {id, status, attempts}"'

# Check progress summary
cat specs/001-event-notifications/prd.json | jq '{
  total: (.stories | length),
  pass: ([.stories[] | select(.status=="pass")] | length),
  fail: ([.stories[] | select(.status=="fail")] | length),
  todo: ([.stories[] | select(.status=="todo")] | length),
  in_progress: ([.stories[] | select(.status=="in_progress")] | length)
}'
```

---

### Customizing Attempt Limits

```bash
# Per-story limit (set in PRD manually)
# Edit prd.json: story.max_attempts = 5

# Global limit (CLI flag)
python -m ai_refactor.ralph_adapter \
  --feature-id 001-event-notifications \
  --mode loop \
  --max-attempts-per-story 3
```

---

## Best Practices

1. **Always generate PRD first**: Run `prd_generator` before starting loop
2. **Start with single iteration**: Use `--mode once` to test before full loop
3. **Monitor first iteration**: Check logs and PRD updates to verify everything works
4. **Use verbose for debugging**: `--verbose` provides detailed information
5. **Review PRD regularly**: Check story statuses and error messages
6. **Don't regenerate PRD during loop**: Only regenerate when spec files change
7. **Use git branches**: Create feature branches before running loop
8. **Set reasonable limits**: Use `--max-iterations` and `--max-attempts-per-story` to prevent infinite loops

---

## Command Reference

### PRD Generator

```bash
python -m ai_refactor.prd_generator --feature-id <feature-id>
```

### Ralph Loop

```bash
# Basic usage
python -m ai_refactor.ralph_adapter --feature-id <feature-id> [OPTIONS]

# Options:
--mode {once,loop}              # Execution mode (default: once)
--max-iterations N               # Maximum loop iterations
--max-attempts-per-story N       # Max attempts per story before fail
--story-id USx                   # Target specific story
--force                          # Retry stories with status="pass"
--auto-commit                    # Auto-commit on success
--no-tests                       # Skip running tests
--no-agents                      # Disable CrewAI agents
--verbose, -v                    # Enable verbose logging
```

---

## Next Steps

After running the Ralph loop:

1. **Review Implementation**: Check git commits and code changes
2. **Run Tests**: Verify all tests pass
3. **Review PRD**: Check all stories have `status="pass"`
4. **Update Specs**: If needed, update spec files and regenerate PRD
5. **Continue Development**: Use loop for remaining stories or new features

---

## See Also

- [HOWTOSPECK.md](./HOWTOSPECK.md) - Spec Kit feature specification guide
- [SETUP.md](./SETUP.md) - Initial setup and configuration
- `ai_refactor/prd_generator.py` - PRD generator implementation
- `ai_refactor/ralph_adapter.py` - Ralph loop implementation
