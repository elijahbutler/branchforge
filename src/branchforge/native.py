from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
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


CHECKS_FILE_FLAG = "BRANCHFORGE_CHECKS_FILE"
LOG_TAIL = 600
MAX_TIMEOUT_SECONDS = 3600
MAX_LOG_BYTES = 1024 * 1024


def _allowed_checks(project: Path) -> tuple[dict[str, dict[str, Any]], list[Path]]:
    """Load the commands the user allows the server to run.

    They come from a file the user names in the server's environment, never
    from a tool argument or the project's own state, so an agent cannot author
    or alter what gets executed. The file also lists the projects it applies
    to: `project` arrives as a tool argument, so it is trusted only when the
    user's file names it. Returns the checks and the extra directories the
    user allows them to run in.
    """
    location = os.environ.get(CHECKS_FILE_FLAG)
    if not location:
        raise ValueError(
            "Running check commands is off. The user enables it by listing allowed commands in a JSON file "
            f"outside the project and setting {CHECKS_FILE_FLAG} to its path in the BranchForge MCP server's "
            "environment. Until then, run the command yourself and report the result with check_record"
        )
    path = Path(location).expanduser().resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read the checks file {path}: {exc}") from exc
    checks = data.get("checks") if isinstance(data, dict) else None
    listed = data.get("projects") if isinstance(data, dict) else None
    roots = data.get("workdir_roots", []) if isinstance(data, dict) else None
    if not isinstance(checks, dict) or not all(
        isinstance(paths, list) and all(isinstance(item, str) for item in paths) for paths in (listed, roots)
    ):
        raise ValueError(
            'The checks file must look like {"projects": ["/absolute/project/path"], '
            '"checks": {"<name>": {"command": ["program", "arg"]}}}, '
            'with an optional "workdir_roots" list of directories'
        )
    projects = [Path(item).expanduser().resolve() for item in listed]
    if any(path.is_relative_to(root) for root in projects):
        raise ValueError(f"{CHECKS_FILE_FLAG} must point outside the project, where project edits cannot change it: {path}")
    if project not in projects:
        raise ValueError(
            f"The checks file does not list this project: {project}. "
            'The user adds its path under "projects" to allow checks to run there'
        )
    allowed: dict[str, dict[str, Any]] = {}
    for name, spec in checks.items():
        command = spec.get("command") if isinstance(spec, dict) else None
        argv = shlex.split(command) if isinstance(command, str) else command
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            raise ValueError(f"Check {name!r} in the checks file needs a command")
        allowed[name] = {"command": argv, "kind": spec.get("kind", "test")}
    return allowed, [Path(item).expanduser().resolve() for item in roots]


def _run_command(argv: list[str], directory: Path, timeout: float) -> tuple[int | None, bytes, bool]:
    """Run an allowed check without a shell. Returns exit code, combined output, and whether it timed out."""
    process = subprocess.Popen(
        argv, cwd=directory, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
        return process.returncode, output, False
    except subprocess.TimeoutExpired:
        # Kill the whole process group so a test runner's children do not outlive it.
        if hasattr(os, "killpg"):
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        output, _ = process.communicate()
        return None, output, True


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
        checks: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        _choice(mode, [item.value for item in BranchMode], "mode")
        references: list[dict[str, str]] = []
        if checks:
            allowed, _ = _allowed_checks(self.cwd)
            for item in checks:
                if "command" in item:
                    raise ValueError(
                        "A stage cannot supply a command. Reference a check by name; "
                        "the command comes from the user's checks file"
                    )
                if item.get("name") not in allowed:
                    raise ValueError(f"Unknown check {item.get('name')!r}. Allowed checks: {', '.join(allowed) or 'none'}")
                references.append({key: item[key] for key in ("name", "invariant") if item.get(key)})
        stage = StageSpec(
            name=name,
            objective=objective,
            deliverable=deliverable,
            invariants=invariants or [],
            mode=BranchMode(mode),
            rubric=rubric or StageSpec(name, objective).rubric,
            # Software branches can run their checks, so they must show the results.
            evidence_policy=evidence_policy or ("observed" if mode == BranchMode.SOFTWARE.value else "judged"),
            checks=references,
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
        """Record what a test, benchmark, or inspection showed. The caller ran it; this stores the result."""
        check = Check(
            branch_id, name, passed, kind=kind, invariant=invariant, command=command,
            exit_code=exit_code, artifact_id=artifact_id, details=details,
        )
        with self._repository() as repository:
            repository.record_check(run_id, check)
            repository.render_branch(branch_id)
            return asdict(check)

    def check_run(
        self,
        run_id: str,
        branch_id: str,
        name: str,
        *,
        workdir: str | None = None,
        timeout_seconds: float = 600.0,
    ) -> dict[str, Any]:
        """Run a check the user allowed and the stage referenced, and record what it did. Exit code 0 passes."""
        allowed, workdir_roots = _allowed_checks(self.cwd)
        if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError(f"timeout_seconds must be positive and at most {MAX_TIMEOUT_SECONDS}")
        with self._repository() as repository:
            branch = self._require_branch(repository, run_id, branch_id)
            if branch["status"] not in {BranchStatus.ADMITTED.value, BranchStatus.RUNNING.value, BranchStatus.EXPLORED.value}:
                raise ValueError(f"Branch is {branch['status']}; checks run before verification")
            stage = repository.get_stage(run_id, branch["stage"]) or {}
            declared = {item["name"]: item for item in stage.get("checks", [])}
            if name not in declared:
                raise ValueError(f"Unknown check {name!r}. Declared checks: {', '.join(declared) or 'none'}")
        if name not in allowed:
            raise ValueError(f"Check {name!r} is no longer in the checks file, so it cannot run")
        # The command comes from the user's file at run time, never from stored state.
        argv: list[str] = allowed[name]["command"]
        directory = self._check_directory(workdir, workdir_roots)
        try:
            # No database connection is held while the command runs.
            exit_code, output, timed_out = _run_command(argv, directory, timeout_seconds)
        except OSError as exc:
            raise ValueError(f"Cannot start check {name!r}: {exc}") from exc
        tail = output.decode(errors="replace")[-LOG_TAIL:].strip()
        with self._repository() as repository:
            with repository.store.atomic():
                artifact = repository.store_artifact(
                    run_id, branch_id, output[-MAX_LOG_BYTES:], role="check-log", media_type="text/plain",
                )
                check = Check(
                    branch_id, name, exit_code == 0 and not timed_out, kind=allowed[name]["kind"],
                    invariant=declared[name].get("invariant"), command=shlex.join(argv), exit_code=exit_code,
                    artifact_id=artifact.id, executed=True, workdir=str(directory),
                    details=f"timed out after {timeout_seconds:g}s\n{tail}".strip() if timed_out else tail,
                )
                repository.record_check(run_id, check)
            repository.render_branch(branch_id)
            return asdict(check)

    def _check_directory(self, workdir: str | None, workdir_roots: list[Path]) -> Path:
        if not workdir:
            return self.cwd
        directory = (self.cwd / workdir).resolve()
        if not directory.is_dir():
            raise ValueError(f"Not a directory: {directory}")
        if directory.is_relative_to(self.cwd):
            return directory
        # Only the user's own list widens this. Anything the project can assert about
        # itself, such as a git worktree registration, is writable by the agent.
        if any(directory.is_relative_to(root) for root in workdir_roots):
            return directory
        raise ValueError(
            f"{directory} is outside the project and not under a directory the user listed in the "
            'checks file ("workdir_roots"); run the check inside the project instead'
        )

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
