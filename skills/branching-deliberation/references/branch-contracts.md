# Branch contracts

Use these schemas as compact contracts. Adapt fields to the task without weakening invariants or evidence requirements.

## Stage contract

```yaml
stage:
  name: architecture-selection
  mode: software
  objective: Choose the processing architecture
  deliverable: Decision record and validated prototype
  invariants:
    - At-least-once delivery
    - Tenant isolation
  rubric:
    correctness: 0.35
    operability: 0.25
    maintainability: 0.20
    performance: 0.10
    implementation_cost: 0.10
  budget:
    active_branches: 3
    survivor_width: 2
    rounds: 2
  completion:
    - All invariants verified
    - Winner clears the evidence threshold
```

## Explorer contract

```yaml
branch:
  id: branch-a
  hypothesis: Event sourcing improves auditability without unacceptable complexity
  mode: software
  material_difference: Append-only state and deterministic replay
  predictions:
    - Recovery can be demonstrated from the event log
  falsifiers:
    - Replay violates the recovery-time objective
  allowed_actions:
    - Inspect relevant repository files
    - Build an isolated prototype
    - Run declared tests
  prohibited_actions:
    - Mutate another branch workspace
    - Expand permissions or scope
  budget:
    time_minutes: 20
    child_agents: 1
  return:
    proposal: string
    evidence: list
    artifacts: list
    risks: list
    unresolved: list
    confidence: number
```

## Critic contract

```yaml
critic:
  candidate_id: branch-a
  task: Find the earliest unsupported or falsifiable claim
  checks:
    - hard invariants
    - evidence provenance
    - hidden assumptions
    - failure and rollback behavior
    - integration compatibility
  return:
    passed_invariants: list
    failed_invariants: list
    unsupported_claims: list
    discriminating_experiments: list
```

## Collapse record

```yaml
collapse:
  stage: architecture-selection
  winner: branch-a
  confidence: 0.82
  evidence:
    - Recovery benchmark passed
  rejected:
    branch-b: Failed recovery invariant
    branch-c: Equivalent performance at substantially higher operational cost
  unresolved:
    - Cross-region latency has not been measured
  revisit_if:
    - Active-active operation becomes required
```
