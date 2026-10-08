---
name: branchforge-evaluate
description: Verifies and judges competing BranchForge branches using invariants, evidence hierarchy, divergence auditing, pairwise comparison, and calibrated confidence. Use after branch exploration and before pruning or committing a stage winner.
---

# BranchForge Evaluate

Judge evidence, not prose quality.

## Verification

1. Use `branch_list` to load the stage candidates.
2. Check hard invariants first. For each invariant, run the test, benchmark, or inspection that decides it and call `check_record` with the result, pass or fail. Name the invariant by its exact text.
3. Rank evidence: machine checks; reproducible tests; artifact inspection; primary sources; corroborated analysis; model opinion.
4. Identify the earliest consequential disagreement and the smallest experiment capable of resolving it.
5. Call `branch_verify` with a 0 to 1 score per rubric criterion, notes, and `verified=true` only when the evidence supports it. The stage rubric applies the weights.

`branch_verify` refuses `verified=true` while an invariant's latest check failed. In a stage with `evidence_policy` `observed`, which is the default for software stages, it also refuses until every invariant has a passing check. Do not work around a refusal. Fix the branch and rerun the check, or prune the branch.

Verify a branch from a context that did not explore it. An explorer grading its own work tends to pass it.

## Selection

Compare candidates pairwise, anonymizing order when practical. Permit:

- one winner;
- a diverse beam for another round;
- a new synthesis branch that must itself be verified;
- no decision pending another experiment.

Use `branch_prune` with a specific reason for dominated or falsified candidates. Never use majority agreement as proof. State what evidence would reverse the decision.
