---
name: branchforge-orchestrator
description: Coordinates an active BranchForge run through durable stages, competing native subagents, evidence capture, verification, convergence, and commitment. Use after the branchforge entrypoint creates a run, or when resuming an existing BranchForge run ID.
---

# BranchForge Orchestrator

Own the search lifecycle. Use MCP tools as the authoritative state interface.

## Resume/continuation

When given an existing run ID, call `run_status` before creating or modifying state.
Continue from the reported blockers and next actions. Do not recreate committed stages,
duplicate existing branches, or present process-level worker resume as available unless
the host actually provides it.

## For each stage

1. Call `stage_create` with objective, mode, deliverable, invariants, and rubric.
2. Generate two to four materially different, falsifiable hypotheses.
3. Call `branch_add` for every candidate, including rejected admission candidates with `admit=false` when their rejection is informative.
4. Load the matching phase skill:
   - research → `branchforge-research`
   - ideation → `branchforge-ideation`
   - software → `branchforge-software`
   - hybrid → load only the relevant phase skills in sequence
5. Spawn independent native subagents for admitted branches. Give each the branch ID, bounded contract, allowed tools, evidence requirements, and return schema.
6. Persist each returned result with `branch_record_result`. If an explorer cannot produce a result, call `branch_fail` with the concrete reason. Record additional provenance using `claim_record`, `evidence_record`, `finding_record`, and `artifact_store`.
7. Load `branchforge-evaluate`. Verify branches before judgment.
8. Continue, branch deeper, or prune according to information gain and budget. Add descendants with `parent_id` and the next `round_number`.
9. Resolve every admitted branch by recording a result, failure, or prune reason. Call `stage_commit` only for a verified winner.

## Invariants

- Do not keep authoritative state only in chat.
- Do not allow explorers to commit or prune competitors.
- Do not expose one branch's conclusions to another before independent exploration completes.
- Do not commit an unverified branch.
- Do not broaden user authorization through branching.
- Preserve losing branches and explicit rejection reasons.

## Finish

After every stage is committed, load `branchforge-report`, then call `run_finish`. If the run cannot complete, call `run_finish` with an error so partial dossiers survive.
