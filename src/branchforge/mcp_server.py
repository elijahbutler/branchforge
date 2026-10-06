from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal

from .native import BranchForgeTools

try:
    import anyio
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    from pydantic import Field
except ModuleNotFoundError:  # The MCP extra is optional; build_server reports it.
    FastMCP = None

    def Field(**_: Any) -> None:  # noqa: N802 - stands in for pydantic.Field
        return None


MISSING_MCP = "Install the MCP extra first: pip install 'branchforge[mcp]'"

Mode = Literal["research", "ideation", "software", "hybrid"]
Status = Literal["proposed", "admitted", "running", "explored", "verified", "pruned", "failed", "committed"]
EvidencePolicy = Literal["observed", "judged"]
CheckKind = Literal["test", "benchmark", "static_analysis", "inspection", "source"]
EvidenceKind = Literal[
    "observation", "test_result", "benchmark", "source", "artifact_inspection", "analysis", "model_assertion"
]

Cwd = Annotated[str | None, Field(description="Absolute path of the target project. State lives in <cwd>/.branchforge. Defaults to the server's working directory.")]
RunId = Annotated[str, Field(description="Run ID returned by run_create, for example run_1a2b3c4d5e6f.")]
BranchId = Annotated[str, Field(description="Branch ID returned by branch_add, for example branch_1a2b3c4d5e6f.")]
StageName = Annotated[str, Field(description="Stage name given to stage_create.")]


def _tools(cwd: str | None) -> BranchForgeTools:
    return BranchForgeTools(Path(cwd) if cwd else Path.cwd())


def build_server() -> Any:
    if FastMCP is None:
        raise RuntimeError(MISSING_MCP)

    server = FastMCP("branchforge")
    read = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
    rerunnable = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @server.prompt()
    def branchforge(goal: str) -> str:
        """Start a durable branching-deliberation workflow for a goal."""
        return f"""Use BranchForge for this goal: {goal}

Keep reasoning in the host and use the BranchForge MCP tools as authoritative state.
Call run_create, then create bounded stages. For each stage, persist two to four
materially distinct hypotheses with branch_add and explore them independently.
Run the tests, benchmarks, or inspections that bear on each stage invariant and
record every result, pass or fail, with check_record. If the user allowed
named check commands, reference them in stage_create and run them with check_run instead. Record results and evidence,
verify viable candidates, resolve every admitted branch, and commit only a
verified winner. Finish with run_finish and report the dossier path.
Never broaden the user's permissions through branching."""

    @server.tool(annotations=write)
    def run_create(
        goal: Annotated[str, Field(description="The decision or deliverable the run must produce.")],
        max_branches: Annotated[int, Field(description="Most branches that can be admitted per stage round, 2 to 8. Enforced by branch_add.")] = 3,
        survivor_width: Annotated[int, Field(description="How many candidates to carry into a later round. Advisory for the host.")] = 2,
        max_rounds: Annotated[int, Field(description="Rounds allowed per stage, 1 to 10. Enforced by branch_add; rounds start at 0.")] = 2,
        novelty_threshold: Annotated[float, Field(description="Minimum novelty the headless kernel admits. Advisory in agent hosts.")] = 0.6,
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Create a durable run in the target project. Returns the run record; keep its run_id."""
        return _tools(cwd).run_create(goal, max_branches=max_branches, survivor_width=survivor_width, max_rounds=max_rounds, novelty_threshold=novelty_threshold)

    @server.tool(annotations=read)
    def run_view(run_id: RunId, cwd: Cwd = None) -> dict[str, Any]:
        """Read a run and its full stage records, including invariants and rubric."""
        return _tools(cwd).run_view(run_id)

    @server.tool(annotations=read)
    def run_status(
        run_id: Annotated[str | None, Field(description="Run to summarize. Omit for the most recent run.")] = None,
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Summarize progress, blockers, and the next valid actions. Call this first when resuming a run."""
        return _tools(cwd).run_status(run_id)

    @server.tool(annotations=write)
    def run_finish(
        run_id: RunId,
        error: Annotated[str | None, Field(description="Omit to complete the run. Give a reason to fail it; open branches are closed with that reason.")] = None,
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Complete a run whose stages are all committed, or fail it with a reason. A finished run cannot change."""
        return _tools(cwd).run_finish(run_id, error=error)

    @server.tool(annotations=write)
    def stage_create(
        run_id: RunId,
        name: Annotated[str, Field(description="Short unique stage name, for example architecture.")],
        objective: Annotated[str, Field(description="The one decision this stage settles.")],
        mode: Annotated[Mode, Field(description="Kind of work the branches do.")] = "hybrid",
        deliverable: Annotated[str, Field(description="What the committed winner must hand over.")] = "A verified recommendation",
        invariants: Annotated[list[str] | None, Field(description="Hard constraints every candidate must satisfy. check_record refers to these by exact text.")] = None,
        rubric: Annotated[dict[str, float] | None, Field(description="Criterion name to weight. Defaults to correctness 0.4, feasibility 0.25, simplicity 0.2, novelty 0.15.")] = None,
        evidence_policy: Annotated[EvidencePolicy | None, Field(description="observed: a branch verifies only after a passing check for every invariant. judged: the verifier decides, but a failed check still blocks. Defaults to observed for software stages, judged otherwise.")] = None,
        checks: Annotated[list[dict[str, str]] | None, Field(description="Checks BranchForge runs through check_run, the same for every branch. Each item has name, plus optional invariant (exact text). A name must be one the user allowed in their checks file; you cannot supply a command. If the tool answers that running commands is off, omit this and report results with check_record.")] = None,
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Create a bounded stage. Returns the stage record."""
        return _tools(cwd).stage_create(run_id, name, objective, mode=mode, deliverable=deliverable, invariants=invariants, rubric=rubric, evidence_policy=evidence_policy, checks=checks)

    @server.tool(annotations=write)
    def stage_commit(
        run_id: RunId,
        stage: StageName,
        winner_id: Annotated[str, Field(description="Branch ID of the verified branch to commit.")],
        rationale: Annotated[str, Field(description="Why this branch won, citing the decisive evidence.")],
        confidence: Annotated[float, Field(description="Confidence in the decision, 0 to 1.")],
        votes: Annotated[dict[str, int] | None, Field(description="Optional pairwise wins per branch ID.")] = None,
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Commit one verified winner and prune the other candidates in a single step. Fails while any branch is still proposed, admitted, or running."""
        return _tools(cwd).stage_commit(run_id, stage, winner_id, rationale, confidence, votes=votes)

    @server.tool(annotations=write)
    def branch_add(
        run_id: RunId,
        stage: StageName,
        title: Annotated[str, Field(description="Short name for the hypothesis. Must differ from other admitted titles in the round.")],
        claim: Annotated[str, Field(description="The falsifiable claim this branch tests.")],
        difference: Annotated[str, Field(description="How this branch differs materially from its competitors.")],
        predictions: Annotated[list[str] | None, Field(description="Observable outcomes expected if the claim holds.")] = None,
        falsifiers: Annotated[list[str] | None, Field(description="Observations that would refute the claim.")] = None,
        novelty: Annotated[float, Field(description="Self-assessed novelty, 0 to 1. Recorded, not enforced.")] = 0.5,
        parent_id: Annotated[str | None, Field(description="Branch ID this one refines, for later rounds.")] = None,
        round_number: Annotated[int, Field(description="Refinement round, starting at 0. Must be below the run's max_rounds.")] = 0,
        admit: Annotated[bool, Field(description="False records a rejected candidate without exploring it.")] = True,
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Add a hypothesis and admit it for exploration. Returns a branch summary; keep its branch_id."""
        return _tools(cwd).branch_add(run_id, stage, title, claim, difference, predictions=predictions, falsifiers=falsifiers, novelty=novelty, parent_id=parent_id, round_number=round_number, admit=admit)

    @server.tool(annotations=read)
    def branch_view(branch_id: BranchId, cwd: Cwd = None) -> dict[str, Any]:
        """Read one branch in full: hypothesis, proposal, risks, scores, and recorded checks."""
        return _tools(cwd).branch_view(branch_id)

    @server.tool(annotations=read)
    def branch_list(
        run_id: RunId,
        stage: Annotated[str | None, Field(description="Only branches in this stage.")] = None,
        status: Annotated[Status | None, Field(description="Only branches in this lifecycle status.")] = None,
        detail: Annotated[bool, Field(description="True returns full records including proposals. The default summaries are far smaller.")] = False,
        cwd: Cwd = None,
    ) -> list[dict[str, Any]]:
        """List branch summaries: ID, title, status, score, and check counts."""
        return _tools(cwd).branch_list(run_id, stage=stage, status=status, detail=detail)

    @server.tool(annotations=write)
    def branch_start(run_id: RunId, branch_id: BranchId, cwd: Cwd = None) -> dict[str, Any]:
        """Mark an admitted branch as running. Optional: branch_record_result starts an admitted branch itself."""
        return _tools(cwd).branch_start(run_id, branch_id)

    @server.tool(annotations=write)
    def branch_record_result(
        run_id: RunId,
        branch_id: BranchId,
        proposal: Annotated[str, Field(description="What the explorer concluded or built.")],
        evidence: Annotated[list[str] | None, Field(description="Supporting statements, stored as unobserved model assertions. Record observed results with check_record or evidence_record.")] = None,
        risks: Annotated[list[str] | None, Field(description="Known risks and open questions.")] = None,
        confidence: Annotated[float, Field(description="The explorer's confidence, 0 to 1.")] = 0.5,
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Record an explorer's result and move the branch to explored. Use branch_fail when there is no result."""
        return _tools(cwd).branch_record_result(run_id, branch_id, proposal, evidence=evidence, risks=risks, confidence=confidence)

    @server.tool(annotations=write)
    def check_record(
        run_id: RunId,
        branch_id: BranchId,
        name: Annotated[str, Field(description="What was checked, for example pytest tests/test_isolation.py.")],
        passed: Annotated[bool, Field(description="The observed outcome. Record failures too.")],
        kind: Annotated[CheckKind, Field(description="How the result was observed.")] = "test",
        invariant: Annotated[str | None, Field(description="Exact text of the stage invariant this check decides. Omit for checks that inform the rubric only. Refused for an invariant that has a declared command; use check_run for those.")] = None,
        command: Annotated[str | None, Field(description="Command that produced the result, so it can be rerun.")] = None,
        exit_code: Annotated[int | None, Field(description="Exit code of the command.")] = None,
        artifact_id: Annotated[str | None, Field(description="ID from artifact_store for the saved log or report.")] = None,
        details: Annotated[str, Field(description="Short summary of the output, such as counts or the measured value.")] = "",
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Record the result of a test, benchmark, static analysis, inspection, or source check you ran. The latest check per invariant decides whether branch_verify can pass; a failed one cannot be overridden."""
        return _tools(cwd).check_record(run_id, branch_id, name, passed, kind=kind, invariant=invariant, command=command, exit_code=exit_code, artifact_id=artifact_id, details=details)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True))
    async def check_run(
        run_id: RunId,
        branch_id: BranchId,
        name: Annotated[str, Field(description="Name of a check the stage referenced in stage_create.")],
        workdir: Annotated[str | None, Field(description="Directory holding this branch's work: a path inside cwd, or a git worktree of the project. Defaults to cwd.")] = None,
        timeout_seconds: Annotated[float, Field(description="Seconds before the command is killed and recorded as failed.")] = 600.0,
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Run a user-allowed check command in the branch's directory and record the result. BranchForge runs it, so the outcome does not depend on what an agent reports. Returns pass or fail, the exit code, and the tail of the output; the full log is stored as an artifact."""
        return await anyio.to_thread.run_sync(partial(_tools(cwd).check_run, run_id, branch_id, name, workdir=workdir, timeout_seconds=timeout_seconds))

    @server.tool(annotations=write)
    def branch_verify(
        run_id: RunId,
        branch_id: BranchId,
        verified: Annotated[bool, Field(description="True moves the branch to verified. False records the judgment and leaves it explored.")],
        scores: Annotated[dict[str, float] | None, Field(description="Score from 0 to 1 for each rubric criterion. The stage rubric applies the weights.")] = None,
        notes: Annotated[list[str] | None, Field(description="Verifier notes, such as what would reverse the judgment.")] = None,
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Record independent verification of an explored branch. verified=true is refused while an invariant check has failed, and in observed stages until every invariant has a passing check."""
        return _tools(cwd).branch_verify(run_id, branch_id, verified=verified, scores=scores, notes=notes)

    @server.tool(annotations=write)
    def branch_prune(
        run_id: RunId,
        branch_id: BranchId,
        reason: Annotated[str, Field(description="Specific reason, kept in the decision record.")],
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Reject a branch that lost or was falsified. Terminal."""
        return _tools(cwd).branch_prune(run_id, branch_id, reason)

    @server.tool(annotations=write)
    def branch_fail(
        run_id: RunId,
        branch_id: BranchId,
        reason: Annotated[str, Field(description="What stopped the explorer.")],
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Close a branch whose explorer could not produce a result. Terminal."""
        return _tools(cwd).branch_fail(run_id, branch_id, reason)

    @server.tool(annotations=write)
    def claim_record(
        run_id: RunId,
        branch_id: BranchId,
        statement: Annotated[str, Field(description="The claim, stated so evidence can support or refute it.")],
        kind: Annotated[str, Field(description="For example claim, assumption, or prediction.")] = "claim",
        status: Annotated[str, Field(description="For example open, supported, or refuted.")] = "open",
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Attach a claim to a branch. Returns its id for evidence_record."""
        return _tools(cwd).claim_record(run_id, branch_id, statement, kind=kind, status=status)

    @server.tool(annotations=write)
    def evidence_record(
        run_id: RunId,
        branch_id: BranchId,
        statement: Annotated[str, Field(description="What was found.")],
        kind: Annotated[EvidenceKind, Field(description="Where the statement comes from.")] = "observation",
        claim_id: Annotated[str | None, Field(description="ID from claim_record that this supports or refutes.")] = None,
        source_uri: Annotated[str | None, Field(description="Exact URL or file path of the source.")] = None,
        artifact_id: Annotated[str | None, Field(description="ID from artifact_store holding the supporting file.")] = None,
        observed: Annotated[bool, Field(description="False for inference that nobody observed directly.")] = True,
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Attach evidence with provenance to a branch. For a pass or fail result, use check_record."""
        return _tools(cwd).evidence_record(run_id, branch_id, statement, kind=kind, claim_id=claim_id, source_uri=source_uri, artifact_id=artifact_id, observed=observed)

    @server.tool(annotations=write)
    def finding_record(
        run_id: RunId,
        branch_id: BranchId,
        statement: Annotated[str, Field(description="The reusable lesson.")],
        kind: Annotated[Literal["insight", "pitfall", "decision"], Field(description="What sort of lesson this is.")] = "insight",
        evidence_id: Annotated[str | None, Field(description="ID from evidence_record that backs the finding.")] = None,
        revisit_if: Annotated[list[str] | None, Field(description="Conditions that should reopen the finding.")] = None,
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Record an insight, pitfall, or decision that later stages should reuse."""
        return _tools(cwd).finding_record(run_id, branch_id, statement, kind=kind, evidence_id=evidence_id, revisit_if=revisit_if)

    @server.tool(annotations=write)
    def artifact_store(
        run_id: RunId,
        branch_id: BranchId,
        path: Annotated[str, Field(description="File to copy, relative to cwd or absolute. Must be inside cwd.")],
        role: Annotated[str, Field(description="What the file is, for example test-log, diff, or benchmark-report.")] = "branch-output",
        media_type: Annotated[str | None, Field(description="MIME type. Guessed from the file name when omitted.")] = None,
        cwd: Cwd = None,
    ) -> dict[str, Any]:
        """Copy a project file into content-addressed storage. Returns its id for check_record and evidence_record."""
        return _tools(cwd).artifact_store(run_id, branch_id, path, role=role, media_type=media_type)

    @server.tool(annotations=read)
    def tree_view(
        run_id: RunId,
        fmt: Annotated[Literal["compact", "markdown", "json"], Field(description="compact and markdown return one line per branch. json returns nested summaries.")] = "compact",
        cwd: Cwd = None,
    ) -> Any:
        """Show branch lineage and status for a run."""
        return _tools(cwd).tree_view(run_id, fmt=fmt)

    @server.tool(annotations=rerunnable)
    def dossier_render(run_id: RunId, cwd: Cwd = None) -> dict[str, Any]:
        """Rewrite the run's decision record and every branch dossier on disk. Returns the directory path."""
        return _tools(cwd).dossier_render(run_id)

    return server


def run() -> None:
    build_server().run()
