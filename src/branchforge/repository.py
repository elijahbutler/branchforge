from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from .models import (
    ArtifactRef,
    BranchMode,
    BranchResult,
    BranchStatus,
    Claim,
    Evidence,
    Finding,
    Hypothesis,
    RunConfig,
    StageSpec,
)
from .store import EventStore


TRANSITIONS: dict[BranchStatus, set[BranchStatus]] = {
    BranchStatus.PROPOSED: {BranchStatus.ADMITTED, BranchStatus.PRUNED},
    BranchStatus.ADMITTED: {BranchStatus.RUNNING, BranchStatus.PRUNED},
    BranchStatus.RUNNING: {BranchStatus.EXPLORED, BranchStatus.FAILED},
    BranchStatus.EXPLORED: {BranchStatus.VERIFIED, BranchStatus.PRUNED, BranchStatus.FAILED},
    BranchStatus.VERIFIED: {BranchStatus.COMMITTED, BranchStatus.PRUNED},
    BranchStatus.PRUNED: set(),
    BranchStatus.FAILED: set(),
    BranchStatus.COMMITTED: set(),
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


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


class ArtifactStore:
    """Immutable, content-addressed binary storage."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def store_file(self, source: str | Path) -> tuple[str, int, Path]:
        source_path = Path(source)
        with source_path.open("rb") as handle:
            return self.store_stream(handle)

    def store_bytes(self, content: bytes) -> tuple[str, int, Path]:
        from io import BytesIO

        return self.store_stream(BytesIO(content))

    def store_stream(self, stream: BinaryIO) -> tuple[str, int, Path]:
        digest = hashlib.sha256()
        size = 0
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.root, prefix=".object-", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "wb") as output:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            sha256 = digest.hexdigest()
            destination = self.root / "sha256" / sha256[:2] / sha256
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                Path(temporary).unlink(missing_ok=True)
            else:
                os.replace(temporary, destination)
            return sha256, size, destination
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


class BranchRepository:
    """Durable branch graph, evidence ledger, artifacts, and dossier projections."""

    def __init__(self, store: EventStore, workspace: str | Path | None = None):
        self.store = store
        database = Path(store.path)
        self.workspace = Path(workspace) if workspace else database.parent / ".branchforge"
        self.artifacts = ArtifactStore(self.workspace / "objects")
        self._initialize()

    def _initialize(self) -> None:
        self.store.transaction([
            ("""CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, goal TEXT NOT NULL, status TEXT NOT NULL,
                config TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""", ()),
            ("""CREATE TABLE IF NOT EXISTS stages (
                run_id TEXT NOT NULL, name TEXT NOT NULL, objective TEXT NOT NULL,
                deliverable TEXT NOT NULL, invariants TEXT NOT NULL, rubric TEXT NOT NULL,
                mode TEXT NOT NULL, status TEXT NOT NULL, winner_id TEXT,
                rationale TEXT, confidence REAL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(run_id, name)
            )""", ()),
            ("""CREATE TABLE IF NOT EXISTS branches (
                branch_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, stage TEXT NOT NULL,
                parent_id TEXT, mode TEXT NOT NULL, status TEXT NOT NULL, round INTEGER NOT NULL,
                title TEXT NOT NULL, claim TEXT NOT NULL, difference TEXT NOT NULL,
                predictions TEXT NOT NULL, falsifiers TEXT NOT NULL, novelty REAL NOT NULL,
                proposal TEXT, risks TEXT NOT NULL DEFAULT '[]', confidence REAL,
                scores TEXT NOT NULL DEFAULT '{}', verified INTEGER NOT NULL DEFAULT 0,
                disposition TEXT, rejection_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""", ()),
            ("CREATE INDEX IF NOT EXISTS idx_branches_run ON branches(run_id, stage, round)", ()),
            ("CREATE INDEX IF NOT EXISTS idx_branches_parent ON branches(parent_id)", ()),
            ("""CREATE TABLE IF NOT EXISTS claims (
                claim_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, branch_id TEXT NOT NULL,
                kind TEXT NOT NULL, statement TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
            )""", ()),
            ("""CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, branch_id TEXT NOT NULL,
                claim_id TEXT, kind TEXT NOT NULL, statement TEXT NOT NULL, source_uri TEXT,
                artifact_id TEXT, observed INTEGER NOT NULL, created_at TEXT NOT NULL
            )""", ()),
            ("""CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, branch_id TEXT NOT NULL,
                sha256 TEXT NOT NULL, media_type TEXT NOT NULL, size INTEGER NOT NULL,
                role TEXT NOT NULL, object_path TEXT NOT NULL, source_uri TEXT,
                metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            )""", ()),
            ("CREATE INDEX IF NOT EXISTS idx_artifacts_hash ON artifacts(sha256)", ()),
            ("""CREATE TABLE IF NOT EXISTS findings (
                finding_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, branch_id TEXT NOT NULL,
                kind TEXT NOT NULL, statement TEXT NOT NULL, evidence_id TEXT,
                revisit_if TEXT NOT NULL, created_at TEXT NOT NULL
            )""", ()),
        ])

    def create_run(self, run_id: str, goal: str, config: RunConfig) -> None:
        now = _now()
        payload = {"goal": goal, "config": asdict(config)}
        self.store.transaction([
            ("INSERT INTO runs(run_id, goal, status, config, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
             (run_id, goal, "running", _json(asdict(config)), now, now)),
            ("INSERT INTO events(run_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
             (run_id, "RUN_STARTED", _json(payload), now)),
        ])

    def finish_run(self, run_id: str, *, error: str | None = None) -> None:
        status = "failed" if error else "completed"
        event_type = "RUN_FAILED" if error else "RUN_COMPLETED"
        now = _now()
        payload = {"error": error} if error else {"stages": len(self.stages(run_id))}
        statements = [
            ("UPDATE runs SET status = ?, error = ?, updated_at = ? WHERE run_id = ?",
             (status, error, now, run_id)),
            ("INSERT INTO events(run_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
             (run_id, event_type, _json(payload), now)),
        ]
        if error:
            statements.insert(1, (
                "UPDATE stages SET status = 'failed', updated_at = ? WHERE run_id = ? AND status = 'running'",
                (now, run_id),
            ))
        self.store.transaction(statements)

    def create_stage(self, run_id: str, stage: StageSpec) -> None:
        if self.get_run(run_id) is None:
            raise ValueError(f"Run does not exist: {run_id}")
        now = _now()
        self.store.transaction([
            ("""INSERT INTO stages(run_id, name, objective, deliverable, invariants,
               rubric, mode, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                run_id, stage.name, stage.objective, stage.deliverable, _json(stage.invariants),
                _json(stage.rubric), stage.mode.value, "running", now, now,
            )),
            ("INSERT INTO events(run_id, stage, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
             (run_id, stage.name, "STAGE_STARTED", _json(asdict(stage)), now)),
        ])

    def finish_stage(self, run_id: str, stage: str, winner_id: str, rationale: str, confidence: float, votes: dict[str, int]) -> None:
        now = _now()
        payload = {"winner": winner_id, "rationale": rationale, "confidence": confidence, "votes": votes}
        self.store.transaction([
            ("""UPDATE stages SET status = 'committed', winner_id = ?, rationale = ?,
               confidence = ?, updated_at = ? WHERE run_id = ? AND name = ?""",
             (winner_id, rationale, confidence, now, run_id, stage)),
            ("INSERT INTO events(run_id, stage, branch_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
             (run_id, stage, winner_id, "STAGE_COMMITTED", _json(payload), now)),
        ])

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self.store.query("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        if not rows:
            return None
        item = dict(rows[0])
        item["config"] = json.loads(item["config"])
        return item

    def stages(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.store.query("SELECT * FROM stages WHERE run_id = ? ORDER BY created_at", (run_id,))
        result = [dict(row) for row in rows]
        for item in result:
            item["invariants"] = json.loads(item["invariants"])
            item["rubric"] = json.loads(item["rubric"])
        return result

    def run_status(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(f"Unknown run: {run_id}")
        stages = self.stages(run_id)
        branches = self.branches(run_id)
        blockers: list[str] = []
        next_actions: list[str] = []
        summaries: list[dict[str, Any]] = []
        terminal = {
            BranchStatus.PRUNED.value,
            BranchStatus.FAILED.value,
            BranchStatus.COMMITTED.value,
        }
        active = {
            BranchStatus.PROPOSED.value,
            BranchStatus.ADMITTED.value,
            BranchStatus.RUNNING.value,
        }
        for stage in stages:
            stage_branches = [branch for branch in branches if branch["stage"] == stage["name"]]
            counts = {status.value: 0 for status in BranchStatus}
            for branch in stage_branches:
                counts[branch["status"]] += 1
            unfinished = [branch for branch in stage_branches if branch["status"] in active]
            verified = [branch for branch in stage_branches if branch["status"] == BranchStatus.VERIFIED.value]
            explored = [branch for branch in stage_branches if branch["status"] == BranchStatus.EXPLORED.value]
            if stage["status"] == "running":
                if not stage_branches:
                    blockers.append(f"Stage {stage['name']} has no branches.")
                    next_actions.append(f"Add two to four branches with branch_add for stage {stage['name']}.")
                for branch in unfinished:
                    blockers.append(f"Branch {branch['branch_id']} is {branch['status']} in stage {stage['name']}.")
                    if branch["status"] in {BranchStatus.PROPOSED.value, BranchStatus.ADMITTED.value}:
                        next_actions.append(f"Start, prune, fail, or record a result for branch {branch['branch_id']}.")
                    elif branch["status"] == BranchStatus.RUNNING.value:
                        next_actions.append(f"Record a result with branch_record_result or fail branch {branch['branch_id']}.")
                for branch in explored:
                    next_actions.append(f"Verify or prune explored branch {branch['branch_id']}.")
                if verified and not unfinished:
                    next_actions.append(f"Commit a verified winner for stage {stage['name']} with stage_commit.")
                elif stage_branches and not verified:
                    blockers.append(f"Stage {stage['name']} has no verified branch to commit.")
            summaries.append({
                "name": stage["name"],
                "status": stage["status"],
                "mode": stage["mode"],
                "winner_id": stage.get("winner_id"),
                "branch_counts": counts,
                "unresolved_branch_ids": [
                    branch["branch_id"]
                    for branch in stage_branches
                    if branch["status"] not in terminal
                ],
            })

        if not stages:
            blockers.append("Run has no stages.")
            next_actions.append("Create a bounded stage with stage_create.")
        incomplete = [stage["name"] for stage in stages if stage["status"] != "committed"]
        finishable = run["status"] == "running" and bool(stages) and not incomplete
        if finishable:
            next_actions.append("Finish the run with run_finish.")
        elif incomplete:
            blockers.append(f"Run cannot finish until stages are committed: {', '.join(incomplete)}.")

        return {
            "run": run,
            "stages": summaries,
            "blockers": list(dict.fromkeys(blockers)),
            "next_actions": list(dict.fromkeys(next_actions)),
            "finishable": finishable,
        }

    def create_branch(self, run_id: str, stage: str, hypothesis: Hypothesis, mode: BranchMode) -> None:
        if self.get_run(run_id) is None:
            raise ValueError(f"Run does not exist: {run_id}")
        if not any(item["name"] == stage for item in self.stages(run_id)):
            raise ValueError(f"Stage does not exist: {stage}")
        if hypothesis.parent_id:
            parent = self.get_branch(hypothesis.parent_id)
            if parent is None:
                raise ValueError(f"Parent branch does not exist: {hypothesis.parent_id}")
            if parent["run_id"] != run_id:
                raise ValueError("Parent branch belongs to a different run")
        now = _now()
        payload = asdict(hypothesis) | {"mode": mode.value, "status": BranchStatus.PROPOSED.value}
        claim = Claim(hypothesis.id, hypothesis.claim)
        self.store.transaction([
            ("""INSERT INTO branches(
                branch_id, run_id, stage, parent_id, mode, status, round, title, claim,
                difference, predictions, falsifiers, novelty, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                hypothesis.id, run_id, stage, hypothesis.parent_id, mode.value,
                BranchStatus.PROPOSED.value, hypothesis.round, hypothesis.title,
                hypothesis.claim, hypothesis.difference, _json(hypothesis.predictions),
                _json(hypothesis.falsifiers), hypothesis.novelty, now, now,
            )),
            ("INSERT INTO events(run_id, stage, branch_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
             (run_id, stage, hypothesis.id, "BRANCH_PROPOSED", _json(payload), now)),
            ("INSERT INTO claims(claim_id, run_id, branch_id, kind, statement, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
             (claim.id, run_id, claim.branch_id, claim.kind, claim.statement, claim.status, now)),
        ])

    def transition(self, run_id: str, branch_id: str, status: BranchStatus, *, reason: str | None = None) -> None:
        branch = self.get_branch(branch_id)
        if branch is None:
            raise KeyError(f"Unknown branch: {branch_id}")
        if branch["run_id"] != run_id:
            raise ValueError("Branch belongs to a different run")
        current = BranchStatus(branch["status"])
        if status == current:
            return
        if status not in TRANSITIONS[current]:
            raise ValueError(f"Illegal branch transition: {current.value} -> {status.value}")
        now = _now()
        event_type = {
            BranchStatus.ADMITTED: "BRANCH_ADMITTED",
            BranchStatus.RUNNING: "BRANCH_STARTED",
            BranchStatus.EXPLORED: "BRANCH_EXPLORED",
            BranchStatus.VERIFIED: "BRANCH_VERIFIED",
            BranchStatus.PRUNED: "BRANCH_PRUNED",
            BranchStatus.FAILED: "BRANCH_FAILED",
            BranchStatus.COMMITTED: "BRANCH_COMMITTED",
        }[status]
        disposition = status.value if status in {BranchStatus.PRUNED, BranchStatus.FAILED, BranchStatus.COMMITTED} else branch.get("disposition")
        rejection = reason if status in {BranchStatus.PRUNED, BranchStatus.FAILED} else branch.get("rejection_reason")
        self.store.transaction([
            ("UPDATE branches SET status = ?, disposition = ?, rejection_reason = ?, updated_at = ? WHERE branch_id = ?",
             (status.value, disposition, rejection, now, branch_id)),
            ("INSERT INTO events(run_id, stage, branch_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
             (run_id, branch["stage"], branch_id, event_type, _json({"from": current.value, "to": status.value, "reason": reason}), now)),
        ])

    def record_result(self, run_id: str, result: BranchResult) -> None:
        now = _now()
        statements = [
            ("""UPDATE branches SET proposal = ?, risks = ?, confidence = ?, scores = ?,
               verified = ?, updated_at = ? WHERE branch_id = ?""", (
                result.proposal, _json(result.risks), result.confidence, _json(result.scores),
                int(result.verified), now, result.hypothesis.id,
            )),
            ("INSERT INTO events(run_id, stage, branch_id, event_type, payload, created_at) SELECT ?, stage, ?, ?, ?, ? FROM branches WHERE branch_id = ?",
             (run_id, result.hypothesis.id, "BRANCH_RESULT_RECORDED", _json(asdict(result)), now, result.hypothesis.id)),
        ]
        for statement in result.evidence:
            evidence = Evidence(result.hypothesis.id, statement)
            statements.extend([
                ("""INSERT INTO evidence(evidence_id, run_id, branch_id, claim_id, kind,
                   statement, source_uri, artifact_id, observed, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    evidence.id, run_id, evidence.branch_id, evidence.claim_id, evidence.kind,
                    evidence.statement, evidence.source_uri, evidence.artifact_id,
                    int(evidence.observed), now,
                )),
                ("INSERT INTO events(run_id, stage, branch_id, event_type, payload, created_at) SELECT ?, stage, ?, ?, ?, ? FROM branches WHERE branch_id = ?",
                 (run_id, evidence.branch_id, "EVIDENCE_RECORDED", _json(asdict(evidence)), now, evidence.branch_id)),
            ])
        self.store.transaction(statements)

    def record_verification(self, run_id: str, result: BranchResult, notes: list[str]) -> None:
        now = _now()
        self.store.transaction([
            ("UPDATE branches SET scores = ?, verified = ?, updated_at = ? WHERE branch_id = ?",
             (_json(result.scores), int(result.verified), now, result.hypothesis.id)),
            ("INSERT INTO events(run_id, stage, branch_id, event_type, payload, created_at) SELECT ?, stage, ?, ?, ?, ? FROM branches WHERE branch_id = ?",
             (run_id, result.hypothesis.id, "BRANCH_VERIFICATION_RECORDED",
              _json({"verified": result.verified, "scores": result.scores, "notes": notes}),
              now, result.hypothesis.id)),
        ])

    def record_claim(self, run_id: str, claim: Claim) -> None:
        self.store.transaction([(
            "INSERT INTO claims(claim_id, run_id, branch_id, kind, statement, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (claim.id, run_id, claim.branch_id, claim.kind, claim.statement, claim.status, _now()),
        )])

    def record_evidence(self, run_id: str, evidence: Evidence) -> None:
        now = _now()
        self.store.transaction([
            ("""INSERT INTO evidence(evidence_id, run_id, branch_id, claim_id, kind,
               statement, source_uri, artifact_id, observed, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                evidence.id, run_id, evidence.branch_id, evidence.claim_id, evidence.kind,
                evidence.statement, evidence.source_uri, evidence.artifact_id,
                int(evidence.observed), now,
            )),
            ("INSERT INTO events(run_id, stage, branch_id, event_type, payload, created_at) SELECT ?, stage, ?, ?, ?, ? FROM branches WHERE branch_id = ?",
             (run_id, evidence.branch_id, "EVIDENCE_RECORDED", _json(asdict(evidence)), now, evidence.branch_id)),
        ])

    def record_finding(self, run_id: str, finding: Finding) -> None:
        now = _now()
        self.store.transaction([
            ("""INSERT INTO findings(finding_id, run_id, branch_id, kind, statement,
               evidence_id, revisit_if, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                finding.id, run_id, finding.branch_id, finding.kind, finding.statement,
                finding.evidence_id, _json(finding.revisit_if), now,
            )),
            ("INSERT INTO events(run_id, stage, branch_id, event_type, payload, created_at) SELECT ?, stage, ?, ?, ?, ? FROM branches WHERE branch_id = ?",
             (run_id, finding.branch_id, "FINDING_RECORDED", _json(asdict(finding)), now, finding.branch_id)),
        ])

    def store_artifact(
        self,
        run_id: str,
        branch_id: str,
        source: str | Path | bytes,
        *,
        role: str = "branch-output",
        media_type: str | None = None,
        source_uri: str | None = None,
    ) -> ArtifactRef:
        if isinstance(source, bytes):
            sha256, size, destination = self.artifacts.store_bytes(source)
        else:
            sha256, size, destination = self.artifacts.store_file(source)
            source_uri = source_uri or str(Path(source).resolve())
            media_type = media_type or mimetypes.guess_type(str(source))[0]
        artifact = ArtifactRef(
            branch_id=branch_id, sha256=sha256, media_type=media_type or "application/octet-stream",
            size=size, role=role, object_path=str(destination), source_uri=source_uri,
        )
        now = _now()
        self.store.transaction([
            ("""INSERT INTO artifacts(artifact_id, run_id, branch_id, sha256, media_type,
               size, role, object_path, source_uri, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                artifact.id, run_id, branch_id, artifact.sha256, artifact.media_type,
                artifact.size, artifact.role, artifact.object_path, artifact.source_uri, "{}", now,
            )),
            ("INSERT INTO events(run_id, stage, branch_id, event_type, payload, created_at) SELECT ?, stage, ?, ?, ?, ? FROM branches WHERE branch_id = ?",
             (run_id, branch_id, "ARTIFACT_STORED", _json(asdict(artifact)), now, branch_id)),
        ])
        return artifact

    def get_branch(self, branch_id: str) -> dict[str, Any] | None:
        rows = self.store.query("SELECT * FROM branches WHERE branch_id = ?", (branch_id,))
        return self._decode_branch(rows[0]) if rows else None

    def branches(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.store.query("SELECT * FROM branches WHERE run_id = ? ORDER BY round, created_at", (run_id,))
        return [self._decode_branch(row) for row in rows]

    def tree(self, run_id: str) -> dict[str, Any]:
        branches = self.branches(run_id)
        by_parent: dict[str | None, list[dict[str, Any]]] = {}
        for branch in branches:
            by_parent.setdefault(branch["parent_id"], []).append(branch)

        def node(branch: dict[str, Any]) -> dict[str, Any]:
            return {**branch, "children": [node(child) for child in by_parent.get(branch["branch_id"], [])]}

        return {"run_id": run_id, "roots": [node(branch) for branch in by_parent.get(None, [])]}

    def render_run(self, run_id: str) -> Path:
        run_dir = self.workspace / "runs" / run_id
        tree = self.tree(run_id)
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(f"Unknown run: {run_id}")
        stages = self.stages(run_id)
        _atomic_text(run_dir / "RUN.json", json.dumps({"run": run, "stages": stages}, indent=2, ensure_ascii=False))
        _atomic_text(run_dir / "TREE.json", json.dumps(tree, indent=2, ensure_ascii=False))
        for branch in self.branches(run_id):
            self.render_branch(branch["branch_id"])
        lines = [f"# Decision record: {run_id}", "", "## Goal", "", run["goal"], ""]
        branches_by_id = {item["branch_id"]: item for item in self.branches(run_id)}
        for stage in stages:
            if not stage.get("winner_id"):
                continue
            item = branches_by_id.get(stage["winner_id"])
            if item is None:
                continue
            lines.extend([
                f"## {stage['name']}: {item['title']}", "",
                item.get("proposal") or "", "", "### Rationale", "",
                stage.get("rationale") or "", "",
            ])
        _atomic_text(run_dir / "DECISION.md", "\n".join(lines))
        return run_dir

    def render_branch(self, branch_id: str) -> Path:
        branch = self.get_branch(branch_id)
        if branch is None:
            raise KeyError(f"Unknown branch: {branch_id}")
        directory = self.workspace / "runs" / branch["run_id"] / "branches" / branch_id
        claims = self._records("claims", "branch_id", branch_id)
        evidence = self._records("evidence", "branch_id", branch_id)
        artifacts = self._records("artifacts", "branch_id", branch_id)
        findings = self._records("findings", "branch_id", branch_id)
        manifest = {"branch": branch, "claims": claims, "findings": findings}
        _atomic_text(directory / "MANIFEST.json", json.dumps(manifest, indent=2, ensure_ascii=False))
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
        if branch.get("rejection_reason"):
            outcome.extend(["## Rejection reason", "", branch["rejection_reason"], ""])
        _atomic_text(directory / "OUTCOME.md", "\n".join(outcome))
        _atomic_text(directory / "EVIDENCE.jsonl", "".join(_json(item) + "\n" for item in evidence))
        _atomic_text(directory / "ARTIFACTS.json", json.dumps(artifacts, indent=2, ensure_ascii=False))
        return directory

    def _records(self, table: str, column: str, value: str) -> list[dict[str, Any]]:
        allowed = {"claims", "evidence", "artifacts", "findings"}
        if table not in allowed or column != "branch_id":
            raise ValueError("Unsupported record query")
        rows = self.store.query(f"SELECT * FROM {table} WHERE {column} = ? ORDER BY created_at", (value,))
        result = [dict(row) for row in rows]
        for item in result:
            for key in ("revisit_if", "metadata"):
                if key in item and isinstance(item[key], str):
                    item[key] = json.loads(item[key])
            if "observed" in item:
                item["observed"] = bool(item["observed"])
        return result

    @staticmethod
    def _decode_branch(row: Any) -> dict[str, Any]:
        item = dict(row)
        for key in ("predictions", "falsifiers", "risks", "scores"):
            item[key] = json.loads(item[key])
        item["verified"] = bool(item["verified"])
        return item
