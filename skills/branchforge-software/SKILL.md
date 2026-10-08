---
name: branchforge-software
description: Executes software-mode BranchForge branches through isolated implementations, tests, benchmarks, artifact capture, and rollback-aware evidence. Use when competing branches modify code, select architectures, debug software, optimize performance, or build product implementations.
---

# BranchForge Software

Implement only the assigned branch in an isolated workspace. Use the host's git worktree isolation for subagents when it has one, so competing branches never edit the same files.

1. Preserve the branch hypothesis and hard invariants.
2. Inspect relevant code and establish a baseline before editing.
3. Keep changes within the authorized project and branch workspace.
4. Run proportional tests, benchmarks, static checks, or visual verification.
5. Call `check_record` for every command result, failures included, with the command and exit code. Tie it to a stage invariant by exact text when it decides one. The stage cannot verify this branch without a passing check for each invariant.
6. Store important diffs, logs, reports, screenshots, or generated deliverables with `artifact_store`.
7. Return implementation summary, changed artifacts, commands, test results, risks, rollback notes, and confidence.

Do not merge, commit a stage winner, alter protected evaluation inputs, or mutate another branch's workspace. The orchestrator owns promotion.
