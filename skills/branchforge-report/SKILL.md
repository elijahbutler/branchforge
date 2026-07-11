---
name: branchforge-report
description: Finalizes and reports a BranchForge run by rendering the durable tree, every branch dossier, committed decisions, rejected alternatives, evidence, artifacts, findings, and reconsideration conditions. Use after stage commitment, on partial-run failure, or when the user asks to inspect an existing run.
---

# BranchForge Report

1. Call `tree_view` to inspect final lineage and terminal states.
2. Confirm each admitted branch has a result or explicit failure/pruning reason.
3. Call `dossier_render` to refresh `RUN.json`, `TREE.json`, `DECISION.md`, and every branch dossier.
4. Summarize:
   - committed result and rationale;
   - decisive evidence;
   - rejected branches and why they lost;
   - unresolved uncertainty;
   - reconsideration conditions;
   - artifact and dossier paths.
5. Let the orchestrator call `run_finish` after all stages are committed.

Do not expose private chain-of-thought. Report concise decision summaries and verifiable evidence.
