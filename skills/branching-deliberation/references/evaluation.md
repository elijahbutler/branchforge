# Evidence and judgment

## Contents

- Evidence hierarchy
- Verification workflow
- Pairwise evaluation
- Bias controls
- Confidence
- Synthesis

## Evidence hierarchy

Prefer evidence in this order:

1. Machine-checked proof or externally enforced invariant
2. Reproducible test, benchmark, or experiment
3. Direct inspection of the produced artifact
4. Primary-source documentation or data
5. Independently corroborated expert analysis
6. Model critique or self-reported confidence

Do not allow a lower tier to overrule a contradictory higher tier without explaining why the higher-tier evidence is invalid.

## Verification workflow

1. Check hard invariants and disqualify irreparable failures.
2. Separate observed evidence from predictions and opinions.
3. Reproduce important measurements when practical.
4. Identify the earliest consequential divergence.
5. Run the smallest discriminating experiment within budget.
6. Score only after evidence collection closes.

## Pairwise evaluation

Compare two candidates at a time. Randomize or reverse order when position bias matters. Hide branch identity and model provenance when practical.

For each rubric criterion, return:

```yaml
criterion: correctness
candidate_a: 0.84
candidate_b: 0.72
evidence:
  - Candidate A passes the recovery test
uncertainty: 0.08
```

Compute the weighted total in code when possible. Keep raw criterion scores separate from their weighted contributions.

## Bias controls

- Do not reward verbosity, polish, or confident language.
- Do not infer correctness from majority agreement.
- Ask whether agents share the same model, prompt, sources, or assumptions.
- Preserve a strategically distinct minority branch when evidence remains inconclusive.
- Require the judge to state what evidence would reverse its choice.
- Use an independent verifier or model family for high-impact decisions when available.

## Confidence

Confidence represents support from available evidence, not the judge's subjective certainty. Lower it for missing tests, correlated agents, unverifiable claims, unstable external facts, or narrow evaluation coverage.

Do not commit when the top candidates fall inside the declared uncertainty margin. Request another experiment or preserve a beam of two.

## Synthesis

Merge candidates only when their components are compatible and the combined design is verified. A synthesis is a new candidate, not an automatic winner. Check interface assumptions, resource interactions, and failure modes before commitment.
