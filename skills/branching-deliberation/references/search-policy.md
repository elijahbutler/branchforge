# Adaptive search policy

## Contents

- Branch decision
- Admission and diversity
- Resource allocation
- Pruning
- Stopping

## Branch decision

Estimate:

```text
branch_priority =
    impact
  × uncertainty
  × cost_of_error
  × expected_information_gain
  × novelty
  ÷ exploration_cost
```

Use relative estimates rather than pretending these terms are precisely measurable. Branch when the decision is consequential, alternatives are plausible, and evidence can change the choice. Continue locally when a choice is low impact, reversible, or already dominated by evidence.

## Admission and diversity

Default to three active branches, a survivor beam of two, and two exploration rounds. Adjust only when task risk or budget justifies it.

Admit a branch only if:

1. It preserves all hard constraints.
2. It tests a distinct hypothesis or failure mode.
3. Its expected result can be evaluated.
4. Its cost fits the stage budget.
5. It is not dominated by an existing branch.

Measure diversity through differences in assumptions, architecture, algorithm, evidence, operational risk, or predicted behavior. Different wording is not diversity.

## Resource allocation

Allocate an initial equal budget to preserve independence. After initial evidence, allocate additional work by expected information gain rather than current rhetorical confidence.

Use stronger or more expensive models for stage framing, difficult exploration, divergence auditing, and final judgment. Use faster models or deterministic code for classification, deduplication, formatting, memory compression, and mechanical verification.

Do not let an explorer grant itself more time, agents, permissions, or tools.

## Pruning

- **Hard failure:** Prune immediately when an invariant fails and cannot be repaired within budget.
- **Dominance:** Prune when another branch is at least as strong on every material criterion and stronger on one.
- **Duplication:** Merge branches that test the same hypothesis with equivalent methods.
- **Low information:** Prune work that cannot produce discriminating evidence.
- **Budget:** Stop the lowest-value branch before exceeding the stage ceiling.

Preserve a compact rejection record even after pruning.

## Stopping

Stop the current round when:

- every active branch completed or failed;
- one candidate wins by a predeclared evidence margin;
- remaining uncertainty cannot change the decision;
- marginal information gain is below exploration cost;
- a required user decision or permission blocks further work.

Do not continue branching solely to use the available budget.
