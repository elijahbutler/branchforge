"""Render a run's durable state as portable files under the workspace."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .repository import BranchRepository


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def _check_line(check: dict[str, Any]) -> str:
    target = f" for {check['invariant']}" if check["invariant"] else ""
    return f"- {'pass' if check['passed'] else 'FAIL'}: {check['name']} ({check['kind']}, reported){target}"


def render_run(repository: BranchRepository, run_id: str) -> Path:
    run = repository.get_run(run_id)
    if run is None:
        raise ValueError(f"Unknown run: {run_id}")
    run_dir = repository.workspace / "runs" / run_id
    stages = repository.stages(run_id)
    branches = repository.branches(run_id)
    _atomic_text(run_dir / "RUN.json", _dump({"run": run, "stages": stages}))
    _atomic_text(run_dir / "TREE.json", _dump(repository.tree(run_id)))
    for branch in branches:
        render_branch(repository, branch["branch_id"])

    lines = [f"# Decision record: {run_id}", "", "## Goal", "", run["goal"], ""]
    by_id = {branch["branch_id"]: branch for branch in branches}
    for stage in stages:
        winner = by_id.get(stage.get("winner_id") or "")
        if winner is None:
            continue
        lines.extend([
            f"## {stage['name']}: {winner['title']}", "",
            winner.get("proposal") or "", "", "### Rationale", "",
            stage.get("rationale") or "", "",
        ])
        checks = repository.checks(winner["branch_id"])
        if checks:
            lines.extend(["### Checks", "", *[_check_line(check) for check in checks], ""])
        rejected = [
            branch for branch in branches
            if branch["stage"] == stage["name"] and branch["branch_id"] != winner["branch_id"]
        ]
        if rejected:
            lines.extend(["### Rejected alternatives", ""])
            lines.extend(
                f"- {branch['title']} ({branch['status']}): {branch.get('rejection_reason') or 'no reason recorded'}"
                for branch in rejected
            )
            lines.append("")
    _atomic_text(run_dir / "DECISION.md", "\n".join(lines))
    return run_dir


def render_branch(repository: BranchRepository, branch_id: str) -> Path:
    branch = repository.get_branch(branch_id)
    if branch is None:
        raise ValueError(f"Unknown branch: {branch_id}")
    directory = repository.workspace / "runs" / branch["run_id"] / "branches" / branch_id
    claims = repository.records("claims", branch_id)
    findings = repository.records("findings", branch_id)
    checks = repository.checks(branch_id)
    _atomic_text(directory / "MANIFEST.json", _dump({"branch": branch, "claims": claims, "findings": findings}))
    hypothesis = [
        f"# {branch['title']}", "", f"**Mode:** {branch['mode']}",
        f"**Status:** {branch['status']}", f"**Parent:** {branch['parent_id'] or 'root'}", "",
        "## Claim", "", branch["claim"], "", "## Material difference", "",
        branch["difference"], "", "## Predictions", "",
        *[f"- {item}" for item in branch["predictions"]], "", "## Falsifiers", "",
        *[f"- {item}" for item in branch["falsifiers"]], "",
    ]
    _atomic_text(directory / "HYPOTHESIS.md", "\n".join(hypothesis))
    outcome = [
        f"# Outcome: {branch['title']}", "", f"**Disposition:** {branch.get('disposition') or 'active'}",
        f"**Confidence:** {branch.get('confidence')}", f"**Verified:** {bool(branch['verified'])}", "",
        "## Proposal", "", branch.get("proposal") or "Not completed.", "", "## Risks", "",
        *[f"- {item}" for item in branch["risks"]], "",
    ]
    if checks:
        outcome.extend(["## Checks", "", *[_check_line(check) for check in checks], ""])
    if branch.get("rejection_reason"):
        outcome.extend(["## Rejection reason", "", branch["rejection_reason"], ""])
    _atomic_text(directory / "OUTCOME.md", "\n".join(outcome))
    _atomic_text(
        directory / "EVIDENCE.jsonl",
        "".join(json.dumps(item, ensure_ascii=False, default=str) + "\n" for item in repository.records("evidence", branch_id)),
    )
    _atomic_text(directory / "CHECKS.json", _dump(checks))
    _atomic_text(directory / "ARTIFACTS.json", _dump(repository.records("artifacts", branch_id)))
    return directory
