# Development

## Run Tests

Installed environment:

```bash
python -m unittest discover -s tests -v
```

Directly from the checkout:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Validate Skills And Plugin

```bash
for skill in skills/*; do
  python3 /path/to/skill-creator/scripts/quick_validate.py "$skill"
done

python3 /path/to/plugin-creator/scripts/validate_plugin.py plugins/branchforge
```

The repository includes behavioral skill evals in `skills/branching-deliberation/evals/evals.json`.

## Add A Provider

Implement `ModelProvider.complete`, expose it in `provider_from_name`, update the CLI choices, and add parser plus end-to-end tests. Preserve the JSON contracts used by the orchestrator.

## Add An Objective Evaluator

The highest-value extension is a domain-specific verifier. It should:

1. receive a candidate and declared invariants;
2. run deterministic checks outside the model;
3. return structured evidence with provenance;
4. distinguish observed results from model interpretations;
5. prevent a judge from overriding failed hard constraints.

## Contributing

Useful contributions include:

- objective evaluators for coding, research, and architecture;
- semantic diversity scoring;
- provider adapters and resilient request handling;
- resumable event replay;
- isolated branch workspaces;
- benchmark datasets comparing single-agent and branching performance;
- visualization of live and historical search trees.

Keep control-plane decisions deterministic where practical, preserve failed-search evidence, and add tests for every new state transition.
