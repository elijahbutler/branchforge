from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from .models import BranchMode, RunConfig, StageSpec
from .orchestrator import BranchForge
from .providers import provider_from_name
from .repository import BranchRepository
from .store import EventStore


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="branchforge", description="Adaptive multi-agent branch search")
    root.add_argument("--db", default="branchforge.db", help="SQLite event store")
    root.add_argument("--workspace", help="Dossiers and content-addressed artifact directory")
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run a staged search")
    run.add_argument("goal")
    run.add_argument("--stage", action="append", default=[], help="Stage objective; may be repeated")
    run.add_argument("--provider", choices=["mock", "openai", "anthropic"], default="mock")
    run.add_argument("--model")
    run.add_argument("--judge-provider", choices=["mock", "openai", "anthropic"])
    run.add_argument("--judge-model")
    run.add_argument("--branches", type=int, default=3)
    run.add_argument("--rounds", type=int, default=1)
    run.add_argument("--mode", choices=[mode.value for mode in BranchMode], default=BranchMode.HYBRID.value)
    run.add_argument("--stage-mode", action="append", choices=[mode.value for mode in BranchMode], default=[], help="Mode for each --stage; repeat in stage order")
    inspect = commands.add_parser("inspect", help="Print a run's event history")
    inspect.add_argument("run_id", nargs="?")
    status = commands.add_parser("status", help="Summarize run progress, blockers, and next actions")
    status.add_argument("run_id", nargs="?")
    tree = commands.add_parser("tree", help="Print a run's reconstructed branch tree")
    tree.add_argument("run_id", nargs="?")
    dossier = commands.add_parser("dossier", help="Render portable dossiers for a run")
    dossier.add_argument("run_id", nargs="?")
    commands.add_parser("runs", help="List recorded run IDs")
    commands.add_parser("mcp", help="Run the agent-native MCP server over stdio")
    return root


async def execute(args: argparse.Namespace) -> int:
    store = EventStore(args.db)
    repository = BranchRepository(store, args.workspace)
    try:
        if args.command == "runs":
            print("\n".join(store.run_ids()))
            return 0
        if args.command == "inspect":
            run_id = args.run_id or next(iter(store.run_ids()), None)
            if not run_id:
                print("No runs found.")
                return 1
            print(json.dumps(store.events(run_id), indent=2))
            return 0
        if args.command == "status":
            tools_repository = BranchRepository(store, args.workspace)
            run_id = args.run_id or next(iter(store.run_ids()), None)
            if not run_id:
                print(json.dumps({
                    "run": None,
                    "stages": [],
                    "blockers": ["No BranchForge runs found."],
                    "next_actions": ["Create a run with branchforge run or run_create."],
                    "finishable": False,
                }, indent=2))
                return 1
            print(json.dumps(tools_repository.run_status(run_id), indent=2))
            return 0
        if args.command in {"tree", "dossier"}:
            run_id = args.run_id or next(iter(store.run_ids()), None)
            if not run_id:
                print("No runs found.")
                return 1
            if args.command == "tree":
                print(json.dumps(repository.tree(run_id), indent=2))
            else:
                print(repository.render_run(run_id))
            return 0
        provider = provider_from_name(args.provider, args.model)
        judge = provider_from_name(args.judge_provider, args.judge_model) if args.judge_provider else None
        config = RunConfig(max_branches=args.branches, max_rounds=args.rounds)
        stage_names = args.stage or ["Develop and verify the best implementation approach"]
        if args.stage_mode and len(args.stage_mode) not in {1, len(stage_names)}:
            raise ValueError("--stage-mode must be given once or once per --stage")
        stage_modes = args.stage_mode * len(stage_names) if len(args.stage_mode) == 1 else args.stage_mode
        if not stage_modes:
            stage_modes = [args.mode] * len(stage_names)
        stages = [
            StageSpec(f"stage-{index}", objective, mode=BranchMode(stage_modes[index - 1]))
            for index, objective in enumerate(stage_names, 1)
        ]
        outcomes = await BranchForge(provider, store, config, judge_provider=judge, repository=repository).run(args.goal, stages)
        print(json.dumps([asdict(outcome) for outcome in outcomes], indent=2))
        return 0
    finally:
        store.close()


def main() -> None:
    args = parser().parse_args()
    if args.command == "mcp":
        from .mcp_server import run

        run()
        return
    raise SystemExit(asyncio.run(execute(args)))


if __name__ == "__main__":
    main()
