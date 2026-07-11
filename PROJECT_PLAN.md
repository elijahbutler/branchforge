# BranchForge project plan

## Product thesis

BranchForge spends parallel model inference only at consequential, uncertain decisions. It represents alternative hypotheses explicitly, explores them in isolation, verifies them, compares the decisive differences, and commits a replayable stage outcome.

## MVP scope — implemented

- Code-controlled orchestration and resource limits
- Model-generated, novelty-scored competing hypotheses
- Concurrent branch exploration with timeouts
- Rubric and invariant verification
- Survivor beam and pairwise tournament
- Conditional provider separation between explorers and judges
- Multi-round refinement inside each stage
- SQLite append-only event history
- Queryable branch graph with enforced lifecycle transitions
- Research, ideation, software, and hybrid execution modes
- Structured claims, evidence, findings, and artifact provenance
- Content-addressed immutable artifact storage
- Portable branch dossiers and reconstructed tree exports
- OpenAI, Anthropic, and deterministic mock providers
- CLI event, tree, dossier, and run inspection plus Python API

## Deliberately out of scope for v0.1

- Arbitrary tool execution by branches
- Filesystem/container sandbox provisioning
- Human approval checkpoints
- Learned branch policy or Monte Carlo value estimates
- Distributed task queues
- Web dashboard
- Semantic similarity embeddings for branch deduplication
- Provider retry, rate-limit, and billing controls

These are excluded because safe execution boundaries and reliable evaluation should precede autonomous tool use.

## Milestones

### M1 — Search kernel (complete)

Build the event model, deterministic branch policy, concurrent execution, verification, tournament, and stage commits.

### M1.5 — Durable branch repository (complete)

- Persist parent-child branch lineage and lifecycle state
- Separate events from queryable current projections
- Store structured claims, evidence, findings, and dispositions
- Deduplicate artifacts through SHA-256 content addressing
- Render human-readable dossiers and decision records
- Apply mode-specific evidence policies

### M2 — Safe tool runtime

- Per-branch ephemeral workspaces
- Capability manifests and allowlisted tools
- Artifact hashing and dossier capture (complete)
- Network policy and secret isolation
- Human approval gates for consequential actions

### M3 — Better selection

- Divergence extraction before judgment
- Three-way cross-model judge panels
- Confidence calibration against held-out evals
- Experiment requests when the win margin is insufficient
- Semantic diversity and Pareto-front preservation

### M4 — Production operations

- Postgres event store and resumable workers
- OpenTelemetry traces and cost accounting
- Cancellation, backpressure, retries, and provider failover
- Search-tree UI with replay and intervention

### M5 — Learning

- Learn branch/continue/backtrack/stop from historical outcomes
- Difficulty-aware compute allocation
- Domain-specific evaluators
- Offline policy evaluation before deployment

## Acceptance criteria for v0.2

1. A killed process can resume a run without repeating committed work.
2. Every external action is attributable to one branch and capability grant.
3. No branch can mutate another branch's workspace.
4. Objective evaluator evidence is distinguishable from model opinion.
5. Token, time, and dollar budgets are enforced externally.
6. Search quality and cost are benchmarked against a strong single-agent baseline.
