---
name: branchforge-software
description: Executes software-mode BranchForge branches through isolated implementations, tests, benchmarks, artifact capture, and rollback-aware evidence. Use when competing branches modify code, select architectures, debug software, optimize performance, or build product implementations.
---

# BranchForge Software

Implement only the assigned branch in an isolated host-provided workspace or worktree when available.

1. Preserve the branch hypothesis and hard invariants.
2. Inspect relevant code and establish a baseline before editing.
3. Keep changes within the authorized project and branch workspace.
4. Run proportional tests, benchmarks, static checks, or visual verification.
5. Distinguish observed command results from interpretation.
6. Store important diffs, logs, reports, screenshots, or generated deliverables with `artifact_store`.
7. Return implementation summary, changed artifacts, commands, test results, risks, rollback notes, and confidence.

Do not merge, commit a stage winner, alter protected evaluation inputs, or mutate another branch's workspace. The orchestrator owns promotion.
