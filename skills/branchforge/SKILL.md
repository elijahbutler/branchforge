---
name: branchforge
description: Runs durable, agent-native branching deliberation for complex research, product ideation, architecture, debugging, and software implementation. Use when several materially different approaches deserve independent exploration, evidence must be preserved, or the user asks for deep branching, competing agents, hypothesis trees, or staged convergence. Requires the BranchForge MCP tools; do not substitute the headless CLI when invoked in an agent host.
---

# BranchForge

Act as the public entrypoint. Keep reasoning and subagent coordination in the host agent; use BranchForge tools for deterministic state, evidence, artifacts, and dossiers.

## Intake

Inspect local context before asking questions. Establish:

- goal and target project;
- stage sequence and mode for each stage: `research`, `ideation`, `software`, or `hybrid`;
- deliverables, hard invariants, and weighted rubric;
- branch, round, time, and tool budgets;
- permissions and human approval boundaries.

If a consequential choice is missing, ask one compact checkpoint. Otherwise proceed with conservative defaults.

## Start

1. Confirm the BranchForge MCP tools are available. If unavailable, stop and explain that the plugin/MCP installation is incomplete. Do not silently switch to model API calls or the CLI.
2. Call `run_create` with the goal and search budget.
3. Load `branchforge-orchestrator` and pass the run ID plus the intake contract. Loading means activating that installed skill by name; if the host has no skill dispatcher, read its `SKILL.md` from the installed skill suite. Do not recursively invoke `branchforge` again.

## Stage-loop fallback

If the host cannot activate a sibling phase skill, continue directly instead of stopping:

1. Call `stage_create`.
2. Form two to four materially distinct, falsifiable candidates and persist each with `branch_add`.
3. Explore admitted branches independently with native subagents when available.
4. Record results, claims, evidence, findings, and explicitly authorized artifacts. Call `branch_fail` for an explorer that cannot return a result.
5. Verify every viable result with `branch_verify`; prune rejected candidates with a reason.
6. Resolve every admitted branch, then call `stage_commit` for one verified winner.
7. Repeat for the next bounded stage. Call `run_finish` only after all stages commit.

## Native-agent rule

Use native subagents or agent teams for independent branches when the host provides them. The lead agent owns orchestration and user communication. Explorers never grant themselves more permissions or budget.

## Completion

Return the committed outcome, decisive evidence, rejected alternatives, unresolved uncertainty, and dossier path. Never present a run as complete until `run_finish` succeeds.
