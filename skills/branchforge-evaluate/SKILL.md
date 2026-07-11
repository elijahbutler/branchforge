---
name: branchforge-evaluate
description: Verifies and judges competing BranchForge branches using invariants, evidence hierarchy, divergence auditing, pairwise comparison, and calibrated confidence. Use after branch exploration and before pruning or committing a stage winner.
---

# BranchForge Evaluate

Judge evidence, not prose quality.

## Verification

1. Use `branch_list` to load the stage candidates.
2. Check hard invariants first. Failed invariants cannot be outweighed by preference scores.
3. Rank evidence: machine checks; reproducible tests; artifact inspection; primary sources; corroborated analysis; model opinion.
4. Identify the earliest consequential disagreement and the smallest experiment capable of resolving it.
5. Call `branch_verify` with weighted scores, notes, and `verified=true` only when the evidence supports it.

## Selection

Compare candidates pairwise, anonymizing order when practical. Permit:

- one winner;
- a diverse beam for another round;
- a new synthesis branch that must itself be verified;
- no decision pending another experiment.

Use `branch_prune` with a specific reason for dominated or falsified candidates. Never use majority agreement as proof. State what evidence would reverse the decision.
