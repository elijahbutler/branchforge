from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from .models import (
    BranchMode,
    BranchResult,
    BranchStatus,
    Check,
    Claim,
    Evidence,
    Finding,
    Hypothesis,
    RunConfig,
    StageSpec,
    new_id,
)
from .repository import BranchRepository
from .store import EventStore


def _choice(value: str, allowed: list[str], name: str) -> str:
    if value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(allowed)} (got {value!r})")
    return value


class BranchForgeTools:
    """Deterministic operations exposed to an agent-native tool protocol.

    Lifecycle rules live in BranchRepository. This layer resolves the project
    directory, validates input shape, and keeps responses small enough to sit
    in an agent's context.
    """

    def __init__(self, cwd: str | Path | None = None):
        self.cwd = Path(cwd or Path.cwd()).resolve()
        self.state_dir = self.cwd / ".branchforge"
        self.database = self.state_dir / "state.db"

    @contextmanager
    def _repository(self) -> Iterator[BranchRepository]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        store = EventStore(self.database)
        try:
            yield BranchRepository(store, self.state_dir)
        finally:
            store.close()

    @staticmethod
    def _summary(repository: BranchRepository, branch: dict[str, Any]) -> dict[str, Any]:
        """The fields an orchestrator needs to choose its next action."""
        checks = repository.checks(branch["branch_id"])
        summary = {
            "branch_id": branch["branch_id"],
            "stage": branch["stage"],
            "round": branch["round"],
            "parent_id": branch["parent_id"],
            "title": branch["title"],
            "status": branch["status"],
            "confidence": branch["confidence"],
            "score": round(sum(branch["scores"].values()), 4),
            "checks_passed": sum(check["passed"] for check in checks),
            "checks_failed": sum(not check["passed"] for check in checks),
        }
        if branch["rejection_reason"]:
            summary["rejection_reason"] = branch["rejection_reason"]
        return summary

    def run_create(
        self,
        goal: str,
        *,
        max_branches: int = 3,
        survivor_width: int = 2,
        max_rounds: int = 2,
        novelty_threshold: float = 0.6,
    ) -> dict[str, Any]:
        config = RunConfig(
            max_branches=max_branches,
            survivor_width=survivor_width,
            max_rounds=max_rounds,
            novelty_threshold=novelty_threshold,
        )
        config.validate()
        run_id = new_id("run")
        with self._repository() as repository:
            repository.create_run(run_id, goal, config)
            return repository.get_run(run_id) or {}

    def run_view(self, run_id: str) -> dict[str, Any]:
        with self._repository() as repository:
            run = repository.get_run(run_id)
            if run is None:
                raise ValueError(f"Unknown run: {run_id}")
            return {"run": run, "stages": repository.stages(run_id)}

    def run_status(self, run_id: str | None = None) -> dict[str, Any]:
        """Summarize run progress, blockers, and safe next actions."""
        with self._repository() as repository:
            selected = run_id
            if selected is None:
                selected = next(iter(repository.store.run_ids()), None)
                if selected is None:
                    return {
                        "run": None,
                        "stages": [],
                        "blockers": ["No BranchForge runs found."],
                        "next_actions": ["Create a run with run_create."],
                        "finishable": False,
                    }
            return repository.run_status(selected)

    def run_finish(self, run_id: str, *, error: str | None = None) -> dict[str, Any]:
        with self._repository() as repository:
            repository.finish_run(run_id, error=error)
            output = repository.render_run(run_id)
            return {"run": repository.get_run(run_id), "dossier_path": str(output)}

    def stage_create(
        self,
        run_id: str,
        name: str,
        objective: str,
        *,
        mode: str = "hybrid",
        deliverable: str = "A verified recommendation",
        invariants: list[str] | None = None,
        rubric: dict[str, float] | None = None,
        evidence_policy: str | None = None,
    ) -> dict[str, Any]:
        _choice(mode, [item.value for item in BranchMode], "mode")
        stage = StageSpec(
            name=name,
            objective=objective,
            deliverable=deliverable,
            invariants=invariants or [],
            mode=BranchMode(mode),
            rubric=rubric or StageSpec(name, objective).rubric,
            evidence_policy=evidence_policy,
        )
        if not stage.rubric or any(weight < 0 for weight in stage.rubric.values()):
            raise ValueError("Rubric weights must be non-negative")
        with self._repository() as repository:
            repository.create_stage(run_id, stage)
            return repository.get_stage(run_id, name) or {}

    def stage_commit(
        self,
        run_id: str,
        stage: str,
        winner_id: str,
        rationale: str,
        confidence: float,
        *,
        votes: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        with self._repository() as repository:
            repository.commit_stage(run_id, stage, winner_id, rationale, confidence, votes)
            repository.render_run(run_id)
            return repository.get_stage(run_id, stage) or {}

    def branch_add(
        self,
        run_id: str,
        stage: str,
        title: str,
        claim: str,
        difference: str,
        *,
        predictions: list[str] | None = None,
        falsifiers: list[str] | None = None,
        novelty: float = 0.5,
        parent_id: str | None = None,
        round_number: int = 0,
        admit: bool = True,
    ) -> dict[str, Any]:
        if not 0 <= novelty <= 1:
            raise ValueError("novelty must be between 0 and 1")
        if round_number < 0:
            raise ValueError("round_number starts at 0")
        with self._repository() as repository:
            stage_record = repository.get_stage(run_id, stage)
            if stage_record is None:
                raise ValueError(f"Unknown stage: {stage}")
            hypothesis = Hypothesis(
                title=title,
                claim=claim,
                difference=difference,
                predictions=predictions or [],
                falsifiers=falsifiers or [],
                novelty=novelty,
                parent_id=parent_id,
                round=round_number,
            )
            with repository.store.atomic():
                repository.create_branch(run_id, stage, hypothesis, BranchMode(stage_record["mode"]))
                repository.transition(
                    run_id,
                    hypothesis.id,
                    BranchStatus.ADMITTED if admit else BranchStatus.PRUNED,
                    reason=None if admit else "Rejected at admission",
                )
            return self._summary(repository, repository.get_branch(hypothesis.id) or {})

    def branch_view(self, branch_id: str) -> dict[str, Any]:
        with self._repository() as repository:
            branch = repository.get_branch(branch_id)
            if branch is None:
                raise ValueError(f"Unknown branch: {branch_id}")
            return {**branch, "checks": repository.checks(branch_id)}

    def branch_list(
        self,
        run_id: str,
        *,
        stage: str | None = None,
        status: str | None = None,
        detail: bool = False,
    ) -> list[dict[str, Any]]:
        if status:
            _choice(status, [item.value for item in BranchStatus], "status")
        with self._repository() as repository:
            if repository.get_run(run_id) is None:
                raise ValueError(f"Unknown run: {run_id}")
            branches = repository.branches(run_id)
            if stage:
                branches = [branch for branch in branches if branch["stage"] == stage]
            if status:
                branches = [branch for branch in branches if branch["status"] == status]
            return branches if detail else [self._summary(repository, branch) for branch in branches]

    def branch_start(self, run_id: str, branch_id: str) -> dict[str, Any]:
        with self._repository() as repository:
            repository.transition(run_id, branch_id, BranchStatus.RUNNING)
            return self._summary(repository, repository.get_branch(branch_id) or {})

    def branch_record_result(
        self,
        run_id: str,
        branch_id: str,
        proposal: str,
        *,
        evidence: list[str] | None = None,
        risks: list[str] | None = None,
        confidence: float = 0.5,
    ) -> dict[str, Any]:
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        with self._repository() as repository:
            with repository.store.atomic():
                branch = self._require_branch(repository, run_id, branch_id)
                if branch["status"] == BranchStatus.ADMITTED.value:
                    repository.transition(run_id, branch_id, BranchStatus.RUNNING)
                elif branch["status"] != BranchStatus.RUNNING.value:
                    raise ValueError(
                        f"Branch is {branch['status']}; a result can be recorded only while it is admitted or running"
                    )
                result = BranchResult(self._hypothesis(branch), proposal, evidence or [], risks or [], confidence)
                repository.record_result(run_id, result)
                repository.transition(run_id, branch_id, BranchStatus.EXPLORED)
            repository.render_branch(branch_id)
            return self._summary(repository, repository.get_branch(branch_id) or {})

    def branch_verify(
        self,
        run_id: str,
        branch_id: str,
        *,
        verified: bool,
        scores: dict[str, float] | None = None,
        notes: list[str] | None = None,
    ) -> dict[str, Any]:
        with self._repository() as repository:
            repository.verify_branch(run_id, branch_id, verified=verified, scores=scores, notes=notes)
            repository.render_branch(branch_id)
            return self._summary(repository, repository.get_branch(branch_id) or {})

    def branch_prune(self, run_id: str, branch_id: str, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("A prune reason is required")
        with self._repository() as repository:
            repository.transition(run_id, branch_id, BranchStatus.PRUNED, reason=reason)
            repository.render_branch(branch_id)
            return self._summary(repository, repository.get_branch(branch_id) or {})

    def branch_fail(self, run_id: str, branch_id: str, reason: str) -> dict[str, Any]:
        """Record a terminal explorer failure without inventing a result."""
        if not reason.strip():
            raise ValueError("A failure reason is required")
        with self._repository() as repository:
            with repository.store.atomic():
                branch = self._require_branch(repository, run_id, branch_id)
                if branch["status"] == BranchStatus.ADMITTED.value:
                    repository.transition(run_id, branch_id, BranchStatus.RUNNING)
                elif branch["status"] not in {BranchStatus.RUNNING.value, BranchStatus.EXPLORED.value}:
                    raise ValueError("Only admitted, running, or explored branches can fail")
                repository.transition(run_id, branch_id, BranchStatus.FAILED, reason=reason)
                repository.record_finding(run_id, Finding(branch_id, reason, kind="failure"))
            repository.render_branch(branch_id)
            return self._summary(repository, repository.get_branch(branch_id) or {})

    def check_record(
        self,
        run_id: str,
        branch_id: str,
        name: str,
        passed: bool,
        *,
        kind: str = "test",
        invariant: str | None = None,
        command: str | None = None,
        exit_code: int | None = None,
        artifact_id: str | None = None,
        details: str = "",
    ) -> dict[str, Any]:
        """Record what a test, benchmark, or inspection showed. The caller ran it; BranchForge never executes commands."""
        check = Check(
            branch_id, name, passed, kind=kind, invariant=invariant, command=command,
            exit_code=exit_code, artifact_id=artifact_id, details=details,
        )
        with self._repository() as repository:
            repository.record_check(run_id, check)
            repository.render_branch(branch_id)
            return asdict(check)

    def claim_record(self, run_id: str, branch_id: str, statement: str, *, kind: str = "claim", status: str = "open") -> dict[str, Any]:
        claim = Claim(branch_id, statement, kind=kind, status=status)
        with self._repository() as repository:
            repository.record_claim(run_id, claim)
            return asdict(claim)

    def evidence_record(
        self,
        run_id: str,
        branch_id: str,
        statement: str,
        *,
        kind: str = "observation",
        claim_id: str | None = None,
        source_uri: str | None = None,
        artifact_id: str | None = None,
        observed: bool = True,
    ) -> dict[str, Any]:
        evidence = Evidence(
            branch_id, statement, kind=kind, claim_id=claim_id, source_uri=source_uri,
            artifact_id=artifact_id, observed=observed,
        )
        with self._repository() as repository:
            repository.record_evidence(run_id, evidence)
            return asdict(evidence)

    def finding_record(
        self,
        run_id: str,
        branch_id: str,
        statement: str,
        *,
        kind: str = "insight",
        evidence_id: str | None = None,
        revisit_if: list[str] | None = None,
    ) -> dict[str, Any]:
        finding = Finding(
            branch_id, statement, kind=kind, evidence_id=evidence_id,
            revisit_if=revisit_if or [],
        )
        with self._repository() as repository:
            repository.record_finding(run_id, finding)
            return asdict(finding)

    def artifact_store(
        self,
        run_id: str,
        branch_id: str,
        path: str,
        *,
        role: str = "branch-output",
        media_type: str | None = None,
    ) -> dict[str, Any]:
        source = (self.cwd / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        if not source.is_relative_to(self.cwd):
            raise ValueError("Artifact path must remain inside the target project")
        if not source.is_file():
            raise ValueError(f"Artifact is not a file: {source}")
        with self._repository() as repository:
            artifact = repository.store_artifact(
                run_id, branch_id, source, role=role, media_type=media_type,
            )
            repository.render_branch(branch_id)
            return asdict(artifact)

    def tree_view(self, run_id: str, *, fmt: str = "compact") -> str | dict[str, Any]:
        _choice(fmt, ["compact", "markdown", "json"], "fmt")
        with self._repository() as repository:
            if repository.get_run(run_id) is None:
                raise ValueError(f"Unknown run: {run_id}")
            tree = repository.tree(run_id)
            if fmt == "json":
                return {"run_id": run_id, "roots": [self._tree_node(repository, root) for root in tree["roots"]]}
            lines = [f"# Branch tree: {run_id}", ""] if fmt == "markdown" else []
            self._render_tree(tree["roots"], lines, 0)
            return "\n".join(lines)

    def dossier_render(self, run_id: str) -> dict[str, Any]:
        with self._repository() as repository:
            output = repository.render_run(run_id)
            return {"run_id": run_id, "path": str(output)}

    @staticmethod
    def _require_branch(repository: BranchRepository, run_id: str, branch_id: str) -> dict[str, Any]:
        branch = repository.get_branch(branch_id)
        if branch is None or branch["run_id"] != run_id:
            raise ValueError("Branch does not belong to run")
        return branch

    @staticmethod
    def _hypothesis(branch: dict[str, Any]) -> Hypothesis:
        return Hypothesis(
            branch["title"], branch["claim"], branch["difference"],
            branch["predictions"], branch["falsifiers"], branch["novelty"],
            id=branch["branch_id"], parent_id=branch["parent_id"], round=branch["round"],
        )

    @classmethod
    def _tree_node(cls, repository: BranchRepository, branch: dict[str, Any]) -> dict[str, Any]:
        return {
            **cls._summary(repository, branch),
            "children": [cls._tree_node(repository, child) for child in branch.get("children", [])],
        }

    @classmethod
    def _render_tree(cls, branches: list[dict[str, Any]], lines: list[str], depth: int) -> None:
        for branch in branches:
            lines.append(
                f"{'  ' * depth}- {branch['branch_id']} [{branch['status']}] "
                f"{branch['title']} (score={sum(branch['scores'].values()):.3f})"
            )
            cls._render_tree(branch.get("children", []), lines, depth + 1)
