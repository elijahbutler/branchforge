---
name: branching-deliberation
description: Explores consequential decisions through bounded, competing agent branches, independent verification, divergence auditing, pairwise judgment, and staged convergence. Use for complex architecture, implementation, research, debugging, planning, or optimization tasks where several materially different approaches are plausible and choosing incorrectly would be costly. Do not use for routine, low-impact, easily reversible work with an obvious solution.
---

# Branching Deliberation

Run an adaptive branch–compete–collapse search. Spend parallel work only where uncertainty and consequence justify it.

## Operating rules

- Preserve the user's goal, authority, constraints, and required deliverables across every branch.
- Use native subagents or agent teams when available. Give each explorer an isolated, bounded contract.
- Keep orchestration, budgets, permissions, commits, and stopping decisions under the lead agent's control.
- Create one branch per materially different hypothesis, not per minor variation.
- Prefer objective tests, measurements, primary sources, and artifact inspection over model opinion.
- Never treat majority agreement as proof. Locate and test the decisive disagreement.
- Preserve rejected branches and their falsifying evidence so later stages do not repeat them.
- Persist a dossier for every admitted branch when durable storage is available. Treat chat history as transport, not the branch record.
- Follow the host's normal permission and safety rules. Branching never broadens authorization.

## Workflow

Track this state while working:

```text
Goal → Stage → Decision → Branches → Evidence → Judgment → Commit
```

### 1. Frame the stage

Define:

- one bounded stage objective;
- an execution mode: research, ideation, software, or hybrid;
- the deliverable;
- hard invariants;
- a weighted evaluation rubric;
- branch, time, token, and tool budgets;
- an observable completion condition.

If the task is simple, solve it directly and do not create branches.

### 2. Select a decision worth branching

Branch only when the decision has high impact, meaningful uncertainty, at least two plausible alternatives, and a feasible way to discriminate between them. Use the policy in [references/search-policy.md](references/search-policy.md).

### 3. Generate competing hypotheses

Create two to four hypotheses. Require every branch to state:

- its claim and strategy;
- how it differs materially from the others;
- predicted observable outcomes;
- falsifying evidence;
- estimated cost and risk.

Reject duplicates, cosmetic variants, and branches below the novelty threshold. Use the contracts in [references/branch-contracts.md](references/branch-contracts.md).

### 4. Explore independently

Run admitted branches concurrently when they do not depend on one another. Do not show explorers competing branch proposals before their independent work is complete.

Give each explorer only the relevant stage state, its hypothesis, allowed tools, budget, success conditions, and required return schema. Ask it to produce evidence and artifacts, not merely advocacy.

Create or update the branch dossier at admission, after evidence collection, and at final disposition. When the BranchForge runtime is available, use its repository rather than inventing a parallel storage layout.

### 5. Verify before judging

Check hard invariants first. Run available tests, benchmarks, linters, simulations, source checks, or artifact inspection. Clearly label unverified claims.

Use critics from a different branch or model family when available. A critic attempts to falsify; it does not choose the winner.

### 6. Audit divergence

Identify the earliest consequential point where surviving branches disagree. State the competing claims and the smallest experiment or evidence capable of resolving them.

If decisive evidence is missing and obtainable within budget, run that experiment before judging.

### 7. Run pairwise judgment

Compare candidates pairwise using anonymized order when practical. Score evidence against the predeclared rubric. Permit four outcomes:

- commit one winner;
- retain a diverse beam of two;
- synthesize compatible components after checking their interfaces;
- declare insufficient evidence and request a discriminating experiment.

Follow [references/evaluation.md](references/evaluation.md) for scoring and anti-bias rules.

### 8. Collapse and preserve memory

Commit the result only when it passes invariants and the evidence clears the confidence threshold. Record:

- the winner and rationale;
- supporting evidence and artifacts;
- rejected alternatives and why they lost;
- unresolved uncertainty;
- conditions that should trigger reconsideration.

Store this collapse record alongside the branch hypothesis, evidence ledger, artifact references, findings, and parent-child lineage. Preserve losing branches with explicit dispositions.

Treat the commit as immutable input to the next stage unless a recorded rollback condition occurs.

### 9. Repeat or stop

Start the next stage from committed state with a fresh branch budget. Stop when the requested deliverable is complete, the confidence threshold is met, marginal information gain is below cost, or the user must make a consequential choice.

## Communication

Keep the user informed during long searches. Report the current stage, active competing hypotheses, decisive evidence, pruned branches, and committed outcome. Do not expose private chain-of-thought; provide concise decision summaries and verifiable evidence.

## Fallback without subagents

If native subagents are unavailable, preserve the same contracts using independent model calls, isolated contexts, or the BranchForge CLI. If none are available, explore branches sequentially while preventing later branches from copying earlier conclusions until independent analysis is complete.
