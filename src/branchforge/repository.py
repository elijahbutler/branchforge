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
    Check,
    CHECK_KINDS,
    Claim,
    Evidence,
    EVIDENCE_KINDS,
    EVIDENCE_POLICIES,
    Finding,
    Hypothesis,
    RunConfig,
    StageSpec,
)
from . import dossier
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


SCHEMA_VERSION = 1
TERMINAL = {BranchStatus.PRUNED, BranchStatus.FAILED, BranchStatus.COMMITTED}
UNFINISHED = {BranchStatus.PROPOSED, BranchStatus.ADMITTED, BranchStatus.RUNNING}
EVENT_TYPES = {
    BranchStatus.ADMITTED: "BRANCH_ADMITTED",
    BranchStatus.RUNNING: "BRANCH_STARTED",
    BranchStatus.EXPLORED: "BRANCH_EXPLORED",
    BranchStatus.VERIFIED: "BRANCH_VERIFIED",
    BranchStatus.PRUNED: "BRANCH_PRUNED",
    BranchStatus.FAILED: "BRANCH_FAILED",
    BranchStatus.COMMITTED: "BRANCH_COMMITTED",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _title_key(title: str) -> str:
    return " ".join(title.lower().split())


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
    """Durable branch graph and the lifecycle rules every caller goes through.

    The agent-native tools and the headless orchestrator both write through
    this class, so a rule enforced here holds for both.
    """

    def __init__(self, store: EventStore, workspace: str | Path | None = None):
        self.store = store
        database = Path(store.path)
        self.workspace = Path(workspace) if workspace else database.parent / ".branchforge"
        self.artifacts = ArtifactStore(self.workspace / "objects")
        self._initialize()

    def _initialize(self) -> None:
        if self.store.query("PRAGMA user_version")[0][0] >= SCHEMA_VERSION:
            return
        with self.store.atomic():
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
                ("""CREATE TABLE IF NOT EXISTS checks (
                    check_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, branch_id TEXT NOT NULL,
                    name TEXT NOT NULL, kind TEXT NOT NULL, passed INTEGER NOT NULL,
                    invariant TEXT, command TEXT, exit_code INTEGER, artifact_id TEXT,
                    details TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
                )""", ()),
                ("CREATE INDEX IF NOT EXISTS idx_checks_branch ON checks(branch_id)", ()),
            ])
            # Columns added after the first release; older databases gain them here.
            self._add_column("stages", "evidence_policy", "TEXT NOT NULL DEFAULT 'judged'")
            self._write(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _add_column(self, table: str, column: str, definition: str) -> None:
        if column not in {row["name"] for row in self.store.query(f"PRAGMA table_info({table})")}:
            self._write(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _write(self, sql: str, parameters: tuple[Any, ...] = ()) -> None:
        self.store.transaction([(sql, parameters)])

    def _event(self, run_id: str, event_type: str, payload: Any, *, stage: str | None = None, branch_id: str | None = None) -> None:
        self._write(
            "INSERT INTO events(run_id, stage, branch_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, stage, branch_id, event_type, _json(payload), _now()),
        )

    # Guards

    def _running_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError(f"Unknown run: {run_id}")
        if run["status"] != "running":
            raise ValueError(
                f"Run {run_id} is {run['status']} and can no longer change; create a new run to continue"
            )
        return run

    def _branch(self, run_id: str, branch_id: str) -> dict[str, Any]:
        branch = self.get_branch(branch_id)
        if branch is None:
            raise ValueError(f"Unknown branch: {branch_id}")
        if branch["run_id"] != run_id:
            raise ValueError("Branch belongs to a different run")
        return branch

    def _require_record(self, table: str, column: str, value: str | None, run_id: str, label: str) -> None:
        if value and not self.store.query(f"SELECT 1 FROM {table} WHERE {column} = ? AND run_id = ?", (value, run_id)):
            raise ValueError(f"Unknown {label}: {value}")

    def _require_admissible(self, run: dict[str, Any], branch: dict[str, Any]) -> None:
        max_rounds = run["config"].get("max_rounds", 2)
        max_branches = run["config"].get("max_branches", 3)
        if branch["round"] >= max_rounds:
            raise ValueError(
                f"Round {branch['round']} is outside the run budget (max_rounds={max_rounds}, rounds start at 0); "
                "commit the stage with the current candidates or record the branch with admit=false"
            )
        admitted = self.store.query(
            """SELECT b.title FROM branches b JOIN events e
               ON e.branch_id = b.branch_id AND e.event_type = 'BRANCH_ADMITTED'
               WHERE b.run_id = ? AND b.stage = ? AND b.round = ?""",
            (branch["run_id"], branch["stage"], branch["round"]),
        )
        if _title_key(branch["title"]) in {_title_key(row["title"]) for row in admitted}:
            raise ValueError(
                f"A branch titled {branch['title']!r} is already admitted in round {branch['round']} of stage "
                f"{branch['stage']}; admit a materially different hypothesis"
            )
        if len(admitted) >= max_branches:
            raise ValueError(
                f"Round {branch['round']} of stage {branch['stage']} already admitted {len(admitted)} branches "
                f"(max_branches={max_branches}); record further candidates with admit=false or use the next round"
            )

    def check_gaps(self, branch: dict[str, Any]) -> tuple[list[str], list[str]]:
        """Return the invariants whose latest check failed, and those never checked."""
        stage = self.get_stage(branch["run_id"], branch["stage"])
        invariants = stage["invariants"] if stage else []
        latest: dict[str, bool] = {}
        for check in self.checks(branch["branch_id"]):
            if check["invariant"]:
                latest[check["invariant"]] = check["passed"]
        failed = [item for item in invariants if latest.get(item) is False]
        missing = [item for item in invariants if item not in latest]
        return failed, missing

    def _require_verifiable(self, branch: dict[str, Any]) -> None:
        branch_id = branch["branch_id"]
        failed, missing = self.check_gaps(branch)
        if failed:
            raise ValueError(
                f"Branch {branch_id} has failed invariant checks: {', '.join(failed)}. "
                "Fix the branch and record a passing check, or prune it; a verifier cannot override a failed check"
            )
        stage = self.get_stage(branch["run_id"], branch["stage"])
        if stage is None or stage["evidence_policy"] != "observed":
            return
        if missing:
            raise ValueError(
                f"Branch {branch_id} has no passing check for: {', '.join(missing)}. "
                "Run each check and record the result with check_record before verifying"
            )
        if not any(check["passed"] for check in self.checks(branch_id)):
            raise ValueError(
                f"Branch {branch_id} needs at least one passing check before verification; "
                "this stage accepts observed evidence only"
            )

    # Runs and stages

    def create_run(self, run_id: str, goal: str, config: RunConfig) -> None:
        now = _now()
        with self.store.atomic():
            self._write(
                "INSERT INTO runs(run_id, goal, status, config, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, goal, "running", _json(asdict(config)), now, now),
            )
            self._event(run_id, "RUN_STARTED", {"goal": goal, "config": asdict(config)})

    def finish_run(self, run_id: str, *, error: str | None = None) -> None:
        """Complete a run, or fail it and close every branch still open."""
        error = (error or "").strip() or None
        with self.store.atomic():
            self._running_run(run_id)
            stages = self.stages(run_id)
            now = _now()
            if error is None:
                if not stages:
                    raise ValueError("Cannot complete a run with no stages; create a stage or finish with an error")
                incomplete = [stage["name"] for stage in stages if stage["status"] != "committed"]
                if incomplete:
                    raise ValueError(f"Cannot complete run with unfinished stages: {incomplete}")
            else:
                for branch in self.branches(run_id):
                    status = BranchStatus(branch["status"])
                    if status in TERMINAL:
                        continue
                    target = BranchStatus.FAILED if status is BranchStatus.RUNNING else BranchStatus.PRUNED
                    self.transition(run_id, branch["branch_id"], target, reason=f"Run failed: {error}")
                self._write(
                    "UPDATE stages SET status = 'failed', updated_at = ? WHERE run_id = ? AND status = 'running'",
                    (now, run_id),
                )
            self._write(
                "UPDATE runs SET status = ?, error = ?, updated_at = ? WHERE run_id = ?",
                ("failed" if error else "completed", error, now, run_id),
            )
            if error:
                self._event(run_id, "RUN_FAILED", {"error": error})
            else:
                self._event(run_id, "RUN_COMPLETED", {"stages": len(stages)})

    def create_stage(self, run_id: str, stage: StageSpec) -> None:
        if stage.evidence_policy not in EVIDENCE_POLICIES:
            raise ValueError(f"evidence_policy must be one of: {', '.join(EVIDENCE_POLICIES)}")
        now = _now()
        with self.store.atomic():
            self._running_run(run_id)
            if self.get_stage(run_id, stage.name) is not None:
                raise ValueError(f"Stage already exists in this run: {stage.name}")
            self._write(
                """INSERT INTO stages(run_id, name, objective, deliverable, invariants, rubric, mode,
                   status, evidence_policy, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, stage.name, stage.objective, stage.deliverable, _json(stage.invariants),
                 _json(stage.rubric), stage.mode.value, "running", stage.evidence_policy, now, now),
            )
            self._event(run_id, "STAGE_STARTED", asdict(stage), stage=stage.name)

    def commit_stage(
        self,
        run_id: str,
        stage: str,
        winner_id: str,
        rationale: str,
        confidence: float,
        votes: dict[str, int] | None = None,
    ) -> None:
        """Commit one verified winner and prune the other candidates, all or nothing."""
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if not rationale.strip():
            raise ValueError("A commit rationale is required")
        with self.store.atomic():
            self._running_run(run_id)
            record = self.get_stage(run_id, stage)
            if record is None:
                raise ValueError(f"Unknown stage: {stage}")
            if record["status"] != "running":
                raise ValueError(f"Stage {stage} is already {record['status']}")
            winner = self.get_branch(winner_id)
            if winner is None or winner["run_id"] != run_id or winner["stage"] != stage:
                raise ValueError("Winner does not belong to the requested run and stage")
            if winner["status"] != BranchStatus.VERIFIED.value:
                raise ValueError("Only a verified branch can be committed")
            candidates = [branch for branch in self.branches(run_id) if branch["stage"] == stage]
            unfinished = [
                branch["branch_id"] for branch in candidates if BranchStatus(branch["status"]) in UNFINISHED
            ]
            if unfinished:
                raise ValueError(
                    "Cannot commit a stage with unfinished branches; record a result, "
                    f"failure, or prune them first: {unfinished}"
                )
            for branch in candidates:
                if branch["branch_id"] != winner_id and BranchStatus(branch["status"]) not in TERMINAL:
                    self.transition(run_id, branch["branch_id"], BranchStatus.PRUNED, reason="Not selected at stage collapse")
            self.transition(run_id, winner_id, BranchStatus.COMMITTED)
            self.record_finding(run_id, Finding(winner_id, f"Committed for stage {stage}: {rationale}", kind="decision"))
            self._write(
                """UPDATE stages SET status = 'committed', winner_id = ?, rationale = ?,
                   confidence = ?, updated_at = ? WHERE run_id = ? AND name = ?""",
                (winner_id, rationale, confidence, _now(), run_id, stage),
            )
            self._event(
                run_id, "STAGE_COMMITTED",
                {"winner": winner_id, "rationale": rationale, "confidence": confidence, "votes": votes or {}},
                stage=stage, branch_id=winner_id,
            )

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

    def get_stage(self, run_id: str, name: str) -> dict[str, Any] | None:
        return next((stage for stage in self.stages(run_id) if stage["name"] == name), None)

    def run_status(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError(f"Unknown run: {run_id}")
        stages = self.stages(run_id)
        branches = self.branches(run_id)
        blockers: list[str] = []
        next_actions: list[str] = []
        summaries: list[dict[str, Any]] = []
        for stage in stages:
            stage_branches = [branch for branch in branches if branch["stage"] == stage["name"]]
            counts = {status.value: 0 for status in BranchStatus}
            for branch in stage_branches:
                counts[branch["status"]] += 1
            unfinished = [branch for branch in stage_branches if BranchStatus(branch["status"]) in UNFINISHED]
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
                    failed, missing = self.check_gaps(branch)
                    if failed:
                        next_actions.append(
                            f"Branch {branch['branch_id']} failed invariant checks ({', '.join(failed)}); "
                            "fix it and record a passing check, or prune it."
                        )
                    elif missing and stage["evidence_policy"] == "observed":
                        next_actions.append(
                            f"Record a check_record result for each unchecked invariant of branch "
                            f"{branch['branch_id']}: {', '.join(missing)}."
                        )
                    elif stage["evidence_policy"] == "observed" and not any(
                        check["passed"] for check in self.checks(branch["branch_id"])
                    ):
                        next_actions.append(
                            f"Record at least one passing check for branch {branch['branch_id']} with "
                            "check_record before verifying it."
                        )
                    else:
                        next_actions.append(f"Verify or prune explored branch {branch['branch_id']}.")
                if verified and not unfinished:
                    next_actions.append(f"Commit a verified winner for stage {stage['name']} with stage_commit.")
                elif stage_branches and not verified:
                    blockers.append(f"Stage {stage['name']} has no verified branch to commit.")
            summaries.append({
                "name": stage["name"],
                "status": stage["status"],
                "mode": stage["mode"],
                "evidence_policy": stage["evidence_policy"],
                "winner_id": stage.get("winner_id"),
                "branch_counts": counts,
                "unresolved_branch_ids": [
                    branch["branch_id"]
                    for branch in stage_branches
                    if BranchStatus(branch["status"]) not in TERMINAL
                ],
            })

        incomplete = [stage["name"] for stage in stages if stage["status"] != "committed"]
        finishable = run["status"] == "running" and bool(stages) and not incomplete
        if run["status"] != "running":
            next_actions.append(f"Run is {run['status']}; create a new run to continue.")
        elif not stages:
            blockers.append("Run has no stages.")
            next_actions.append("Create a bounded stage with stage_create.")
        elif finishable:
            next_actions.append("Finish the run with run_finish.")
        else:
            blockers.append(f"Run cannot finish until stages are committed: {', '.join(incomplete)}.")

        return {
            "run": run,
            "stages": summaries,
            "blockers": list(dict.fromkeys(blockers)),
            "next_actions": list(dict.fromkeys(next_actions)),
            "finishable": finishable,
        }

    # Branches

    def create_branch(self, run_id: str, stage: str, hypothesis: Hypothesis, mode: BranchMode) -> None:
        with self.store.atomic():
            self._running_run(run_id)
            record = self.get_stage(run_id, stage)
            if record is None:
                raise ValueError(f"Stage does not exist: {stage}")
            if record["status"] != "running":
                raise ValueError(f"Stage {stage} is already {record['status']}")
            if hypothesis.parent_id:
                parent = self.get_branch(hypothesis.parent_id)
                if parent is None:
                    raise ValueError(f"Parent branch does not exist: {hypothesis.parent_id}")
                if parent["run_id"] != run_id:
                    raise ValueError("Parent branch belongs to a different run")
            now = _now()
            claim = Claim(hypothesis.id, hypothesis.claim)
            self._write(
                """INSERT INTO branches(
                    branch_id, run_id, stage, parent_id, mode, status, round, title, claim,
                    difference, predictions, falsifiers, novelty, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (hypothesis.id, run_id, stage, hypothesis.parent_id, mode.value,
                 BranchStatus.PROPOSED.value, hypothesis.round, hypothesis.title,
                 hypothesis.claim, hypothesis.difference, _json(hypothesis.predictions),
                 _json(hypothesis.falsifiers), hypothesis.novelty, now, now),
            )
            self._event(
                run_id, "BRANCH_PROPOSED",
                asdict(hypothesis) | {"mode": mode.value, "status": BranchStatus.PROPOSED.value},
                stage=stage, branch_id=hypothesis.id,
            )
            self._write(
                "INSERT INTO claims(claim_id, run_id, branch_id, kind, statement, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (claim.id, run_id, claim.branch_id, claim.kind, claim.statement, claim.status, now),
            )

    def transition(self, run_id: str, branch_id: str, status: BranchStatus, *, reason: str | None = None) -> None:
        with self.store.atomic():
            branch = self._branch(run_id, branch_id)
            run = self._running_run(run_id)
            current = BranchStatus(branch["status"])
            if status == current:
                return
            if status not in TRANSITIONS[current]:
                raise ValueError(f"Illegal branch transition: {current.value} -> {status.value}")
            if status is BranchStatus.ADMITTED:
                self._require_admissible(run, branch)
            if status is BranchStatus.VERIFIED:
                self._require_verifiable(branch)
            disposition = status.value if status in TERMINAL else branch.get("disposition")
            rejection = reason if status in {BranchStatus.PRUNED, BranchStatus.FAILED} else branch.get("rejection_reason")
            self._write(
                "UPDATE branches SET status = ?, disposition = ?, rejection_reason = ?, updated_at = ? WHERE branch_id = ?",
                (status.value, disposition, rejection, _now(), branch_id),
            )
            self._event(
                run_id, EVENT_TYPES[status], {"from": current.value, "to": status.value, "reason": reason},
                stage=branch["stage"], branch_id=branch_id,
            )

    def record_result(self, run_id: str, result: BranchResult) -> None:
        with self.store.atomic():
            self._running_run(run_id)
            branch = self._branch(run_id, result.hypothesis.id)
            if branch["status"] != BranchStatus.RUNNING.value:
                raise ValueError(f"Branch is {branch['status']}; a result is recorded only while the branch is running")
            self._write(
                """UPDATE branches SET proposal = ?, risks = ?, confidence = ?, scores = ?,
                   verified = ?, updated_at = ? WHERE branch_id = ?""",
                (result.proposal, _json(result.risks), result.confidence, _json(result.scores),
                 int(result.verified), _now(), branch["branch_id"]),
            )
            self._event(run_id, "BRANCH_RESULT_RECORDED", asdict(result), stage=branch["stage"], branch_id=branch["branch_id"])
            for statement in result.evidence:
                self.record_evidence(run_id, Evidence(branch["branch_id"], statement))

    def verify_branch(
        self,
        run_id: str,
        branch_id: str,
        *,
        verified: bool,
        scores: dict[str, float] | None = None,
        notes: list[str] | None = None,
    ) -> None:
        """Record a verifier's judgment. Scores are 0 to 1 per rubric criterion; the rubric applies the weights."""
        with self.store.atomic():
            self._running_run(run_id)
            branch = self._branch(run_id, branch_id)
            if branch["status"] != BranchStatus.EXPLORED.value:
                raise ValueError("Branch must be explored before verification")
            stage = self.get_stage(run_id, branch["stage"])
            rubric: dict[str, float] = stage["rubric"] if stage else {}
            scores = scores or {}
            unknown = sorted(set(scores) - set(rubric))
            if unknown:
                raise ValueError(f"Unknown rubric criteria: {', '.join(unknown)}. This stage scores: {', '.join(rubric)}")
            if any(not 0 <= value <= 1 for value in scores.values()):
                raise ValueError("Scores must be between 0 and 1; the stage rubric applies the weights")
            if verified:
                self._require_verifiable(branch)
            weighted = {key: value * rubric[key] for key, value in scores.items()}
            self._write_verification(run_id, branch, weighted, verified, notes or [])
            if verified:
                self.transition(run_id, branch_id, BranchStatus.VERIFIED)

    def record_verification(self, run_id: str, result: BranchResult, notes: list[str]) -> None:
        with self.store.atomic():
            self._running_run(run_id)
            branch = self._branch(run_id, result.hypothesis.id)
            if branch["status"] != BranchStatus.EXPLORED.value:
                raise ValueError(f"Branch is {branch['status']}; verification is recorded only while the branch is explored")
            self._write_verification(run_id, branch, result.scores, result.verified, notes)

    def _write_verification(self, run_id: str, branch: dict[str, Any], scores: dict[str, float], verified: bool, notes: list[str]) -> None:
        self._write(
            "UPDATE branches SET scores = ?, verified = ?, updated_at = ? WHERE branch_id = ?",
            (_json(scores), int(verified), _now(), branch["branch_id"]),
        )
        self._event(
            run_id, "BRANCH_VERIFICATION_RECORDED", {"verified": verified, "scores": scores, "notes": notes},
            stage=branch["stage"], branch_id=branch["branch_id"],
        )

    # Claims, evidence, checks, findings, artifacts

    def record_claim(self, run_id: str, claim: Claim) -> None:
        with self.store.atomic():
            self._running_run(run_id)
            branch = self._branch(run_id, claim.branch_id)
            self._write(
                "INSERT INTO claims(claim_id, run_id, branch_id, kind, statement, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (claim.id, run_id, claim.branch_id, claim.kind, claim.statement, claim.status, _now()),
            )
            self._event(run_id, "CLAIM_RECORDED", asdict(claim), stage=branch["stage"], branch_id=claim.branch_id)

    def record_evidence(self, run_id: str, evidence: Evidence) -> None:
        if evidence.kind not in EVIDENCE_KINDS:
            raise ValueError(f"Evidence kind must be one of: {', '.join(EVIDENCE_KINDS)}")
        with self.store.atomic():
            self._running_run(run_id)
            branch = self._branch(run_id, evidence.branch_id)
            self._require_record("claims", "claim_id", evidence.claim_id, run_id, "claim")
            self._require_record("artifacts", "artifact_id", evidence.artifact_id, run_id, "artifact")
            self._write(
                """INSERT INTO evidence(evidence_id, run_id, branch_id, claim_id, kind,
                   statement, source_uri, artifact_id, observed, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (evidence.id, run_id, evidence.branch_id, evidence.claim_id, evidence.kind,
                 evidence.statement, evidence.source_uri, evidence.artifact_id,
                 int(evidence.observed), _now()),
            )
            self._event(run_id, "EVIDENCE_RECORDED", asdict(evidence), stage=branch["stage"], branch_id=evidence.branch_id)

    def record_check(self, run_id: str, check: Check) -> None:
        """Record a reported pass or fail. The latest check per invariant decides verification."""
        if check.kind not in CHECK_KINDS:
            raise ValueError(f"Check kind must be one of: {', '.join(CHECK_KINDS)}")
        if not check.name.strip():
            raise ValueError("A check name is required")
        with self.store.atomic():
            self._running_run(run_id)
            branch = self._branch(run_id, check.branch_id)
            if branch["status"] not in {BranchStatus.ADMITTED.value, BranchStatus.RUNNING.value, BranchStatus.EXPLORED.value}:
                raise ValueError(
                    f"Branch {check.branch_id} is {branch['status']}; checks are recorded before verification. "
                    "To act on a late failure, prune the branch with the failing result as the reason"
                )
            stage = self.get_stage(run_id, branch["stage"])
            invariants = stage["invariants"] if stage else []
            if check.invariant and check.invariant not in invariants:
                declared = "; ".join(invariants) or "none declared"
                raise ValueError(f"Unknown invariant {check.invariant!r}. This stage declares: {declared}")
            self._require_record("artifacts", "artifact_id", check.artifact_id, run_id, "artifact")
            self._write(
                """INSERT INTO checks(check_id, run_id, branch_id, name, kind, passed, invariant,
                   command, exit_code, artifact_id, details, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (check.id, run_id, check.branch_id, check.name, check.kind, int(check.passed),
                 check.invariant, check.command, check.exit_code, check.artifact_id, check.details, _now()),
            )
            self._event(run_id, "CHECK_RECORDED", asdict(check), stage=branch["stage"], branch_id=check.branch_id)

    def checks(self, branch_id: str) -> list[dict[str, Any]]:
        return self.records("checks", branch_id)

    def record_finding(self, run_id: str, finding: Finding) -> None:
        with self.store.atomic():
            self._running_run(run_id)
            branch = self._branch(run_id, finding.branch_id)
            self._require_record("evidence", "evidence_id", finding.evidence_id, run_id, "evidence")
            self._write(
                """INSERT INTO findings(finding_id, run_id, branch_id, kind, statement,
                   evidence_id, revisit_if, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (finding.id, run_id, finding.branch_id, finding.kind, finding.statement,
                 finding.evidence_id, _json(finding.revisit_if), _now()),
            )
            self._event(run_id, "FINDING_RECORDED", asdict(finding), stage=branch["stage"], branch_id=finding.branch_id)

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
        self._running_run(run_id)
        branch = self._branch(run_id, branch_id)
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
        with self.store.atomic():
            # The copy above can be slow; the run may have finished meanwhile.
            self._running_run(run_id)
            self._write(
                """INSERT INTO artifacts(artifact_id, run_id, branch_id, sha256, media_type,
                   size, role, object_path, source_uri, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (artifact.id, run_id, branch_id, artifact.sha256, artifact.media_type,
                 artifact.size, artifact.role, artifact.object_path, artifact.source_uri, "{}", _now()),
            )
            self._event(run_id, "ARTIFACT_STORED", asdict(artifact), stage=branch["stage"], branch_id=branch_id)
        return artifact

    # Queries and projections

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
        return dossier.render_run(self, run_id)

    def render_branch(self, branch_id: str) -> Path:
        return dossier.render_branch(self, branch_id)

    def records(self, table: str, branch_id: str) -> list[dict[str, Any]]:
        if table not in {"claims", "evidence", "artifacts", "findings", "checks"}:
            raise ValueError("Unsupported record query")
        rows = self.store.query(f"SELECT * FROM {table} WHERE branch_id = ? ORDER BY created_at, rowid", (branch_id,))
        result = [dict(row) for row in rows]
        for item in result:
            for key in ("revisit_if", "metadata"):
                if key in item and isinstance(item[key], str):
                    item[key] = json.loads(item[key])
            for key in ("observed", "passed"):
                if key in item:
                    item[key] = bool(item[key])
        return result

    @staticmethod
    def _decode_branch(row: Any) -> dict[str, Any]:
        item = dict(row)
        for key in ("predictions", "falsifiers", "risks", "scores"):
            item[key] = json.loads(item[key])
        item["verified"] = bool(item["verified"])
        return item
