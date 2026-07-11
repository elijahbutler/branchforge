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
- Deterministic agent-native MCP server with lifecycle, evidence, artifact, and dossier tools
- Codex and Claude skill suites with phase-specific orchestration instructions
- Codex and Claude plugin manifests plus local installers

## Prioritized roadmap

The next work should make BranchForge operationally legible before making it broader.
The core branch graph is durable; the product now needs to help users and host agents
understand what is unfinished, what is safe to do next, and why a run can or cannot
finish.

### R1 — Guided run UX

- Add `branchforge status [run_id]` and MCP `run_status`.
- Report active run, stage state, branch counts, unresolved branch IDs, blockers, next actions, and finish readiness.
- Update skills with a continuation path for existing runs that inspects status before creating new stages or branches.
- Be explicit that this is guided continuation from durable state, not automatic worker/process resume.

### R2 — Lifecycle consistency

- Keep native tools, MCP exports, README, and tests in exact sync.
- Add an MCP tool-surface contract test that verifies every intended lifecycle/evidence/artifact/dossier tool is exposed.
- Require meaningful reasons for terminal prune/fail actions.
- Make negative verification produce clear resolution guidance so rejected candidates do not remain ambiguous.
- Ensure failed partial-run dossiers do not leave active-looking branch records without explanation.

### R3 — Install confidence

- Add `branchforge doctor --host codex|claude|claude-desktop`.
- Diagnose Python/runtime import, MCP stdio startup, skill installation, host CLI availability, configured command path, duplicate Claude scopes, Desktop config shape, and marketplace/PATH readiness.
- Back the doctor with fake-host and temporary-config tests.

### R4 — Objective evaluators and benchmarks

- Build 8-12 fixed benchmark tasks comparing BranchForge with a strong single-agent baseline.
- Score correctness, evidence quality, cost, latency, and calibrated uncertainty.
- Add one deterministic coding evaluator first, using tests/static checks/artifact inspection.
- Use evaluator results as structured evidence that cannot be overridden by a model judge when hard constraints fail.

## Deliberately out of scope for v0.1

- Arbitrary tool execution by the headless Python kernel
- Filesystem/container sandbox provisioning
- Human approval checkpoints
- Learned branch policy or Monte Carlo value estimates
- Distributed task queues
- Web dashboard
- Semantic similarity embeddings for branch deduplication
- Provider retry, rate-limit, and billing controls

In agent-native mode, Codex or Claude executes work through its own tools and approval boundary. BranchForge records that work but does not bypass or replace host safety controls.

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
