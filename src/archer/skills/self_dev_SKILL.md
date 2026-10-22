---
name: self_dev
description: ARCHER self-development, automated R&D, and coding via Antigravity in isolated worktrees
category: rnd
---

# ARCHER Self-Development & R&D Tools (Spec Section 11b)

Enables ARCHER to research, write, test, and apply improvements to its own codebase.

### propose_improvement

Record a new plain-language improvement or skill proposal.

**Parameters:**
- `title` (string, required): Short summary of the improvement.
- `description` (string, optional): Detailed explanation of requirements.
- `source` (string, optional): Origin ('user', 'self_observation', 'research', 'tool_failure').

### run_rnd_job

Execute an R&D coding and testing job in an isolated git worktree.

**Parameters:**
- `job_id` (string, required): The ID of the proposal to execute.
- `writer_model` (string, optional): Writer AI model (defaults to gemini-4-argon-medium).
- `checker_model` (string, optional): Reviewer AI model from a different family (defaults to claude-sonnet-5-5-medium).

### apply_rnd_update

Apply a tested and reviewed R&D patch to the live repository. Creates a pre-apply backup and passes through Phase 3 approval gate.

**Parameters:**
- `job_id` (string, required): The ID of the proposal to apply.

### undo_last_update

Restore previous repository state from the latest pre-apply backup.

**Parameters:**
- `job_id` (string, optional): Specific job ID to rollback, or None for the latest.

### list_rnd_proposals

List all R&D proposals.

**Parameters:**
- `status` (string, optional): Filter by status ('proposed', 'running', 'ready_for_review', 'applied', 'rejected', 'undone').
- `limit` (integer, optional): Maximum number of proposals to return.

### get_rnd_status

Get detailed status, checker verdict, test results, and artifact paths for a proposal.

**Parameters:**
- `job_id` (string, required): The ID of the proposal.
