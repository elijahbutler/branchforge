# Usage

## Agent-Native Invocation

Codex:

```text
$branchforge develop an auditable event-processing product. Begin with
research, compare product concepts, then explore competing software
architectures. Preserve every branch and ask before consequential actions.
```

Claude Code:

```text
/branchforge develop an auditable event-processing product. Begin with
research, compare product concepts, then explore competing software
architectures. Preserve every branch and ask before consequential actions.
```

The active host model performs reasoning and spawns native subagents. BranchForge stores the run, branch graph, evidence, artifacts, and dossiers.

## Good BranchForge Tasks

Use BranchForge when there is a real decision under uncertainty:

- competing product or architecture directions;
- root-cause investigations with several plausible causes;
- risky implementation approaches that need isolated exploration;
- research tasks where contradictory evidence matters;
- decisions where rejected alternatives should remain auditable.

Do not use BranchForge for tiny edits or obvious single-path tasks.

## CLI Examples

Run an offline mock search:

```bash
branchforge run "Choose an event-processing architecture" \
  --stage "Compare persistence models" \
  --provider mock \
  --branches 3 \
  --rounds 1
```

Inspect recent runs:

```bash
branchforge runs
branchforge status
branchforge tree
branchforge dossier
```

Use a specific run ID:

```bash
branchforge status run_123
branchforge tree run_123
branchforge dossier run_123
```

Use a non-default database and workspace:

```bash
branchforge --db work/search.db --workspace work/archive run "..."
branchforge --db work/search.db --workspace work/archive status
```

## Provider Mode

Headless provider mode is useful for automation outside an agent host.

OpenAI:

```bash
OPENAI_API_KEY=... branchforge run "Choose a cache strategy" \
  --provider openai \
  --model gpt-5.6-sol
```

Anthropic:

```bash
ANTHROPIC_API_KEY=... branchforge run "Choose a cache strategy" \
  --provider anthropic \
  --model claude-fable-5
```

Cross-model exploration and judgment:

```bash
branchforge run "Choose a migration strategy" \
  --provider openai \
  --model gpt-5.6-sol \
  --judge-provider anthropic \
  --judge-model claude-fable-5
```

## Python API

```python
import asyncio

from branchforge import BranchForge, BranchMode, RunConfig, StageSpec
from branchforge.providers import OpenAIProvider
from branchforge.store import EventStore


async def main() -> None:
    store = EventStore("branchforge.db")
    try:
        forge = BranchForge(
            provider=OpenAIProvider("gpt-5.6-sol"),
            store=store,
            config=RunConfig(max_branches=3, max_rounds=1),
        )
        outcomes = await forge.run(
            "Design an auditable payment reconciliation service",
            [
                StageSpec(
                    name="architecture",
                    objective="Choose the persistence model",
                    mode=BranchMode.HYBRID,
                    invariants=["Idempotent writes", "Complete audit trail"],
                )
            ],
        )
        print(outcomes[0].winner.hypothesis.title)
    finally:
        store.close()


asyncio.run(main())
```
