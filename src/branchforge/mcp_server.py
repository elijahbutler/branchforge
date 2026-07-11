from __future__ import annotations

from pathlib import Path
from typing import Any

from .native import BranchForgeTools


MISSING_MCP = "Install the MCP extra first: pip install 'branchforge[mcp]'"


def _tools(cwd: str | None) -> BranchForgeTools:
    return BranchForgeTools(Path(cwd) if cwd else Path.cwd())


def build_server() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        raise RuntimeError(MISSING_MCP) from exc

    server = FastMCP("branchforge")

    @server.tool()
    def run_create(goal: str, max_branches: int = 3, survivor_width: int = 2, max_rounds: int = 2, novelty_threshold: float = 0.6, cwd: str | None = None) -> dict[str, Any]:
        """Create a durable BranchForge run in the target project."""
        return _tools(cwd).run_create(goal, max_branches=max_branches, survivor_width=survivor_width, max_rounds=max_rounds, novelty_threshold=novelty_threshold)

    @server.tool()
    def run_view(run_id: str, cwd: str | None = None) -> dict[str, Any]:
        """Read a run and its stage records."""
        return _tools(cwd).run_view(run_id)

    @server.tool()
    def run_finish(run_id: str, error: str | None = None, cwd: str | None = None) -> dict[str, Any]:
        """Complete or fail a run and render its durable dossier."""
        return _tools(cwd).run_finish(run_id, error=error)

    @server.tool()
    def stage_create(run_id: str, name: str, objective: str, mode: str = "hybrid", deliverable: str = "A verified recommendation", invariants: list[str] | None = None, rubric: dict[str, float] | None = None, cwd: str | None = None) -> dict[str, Any]:
        """Create a research, ideation, software, or hybrid stage."""
        return _tools(cwd).stage_create(run_id, name, objective, mode=mode, deliverable=deliverable, invariants=invariants, rubric=rubric)

    @server.tool()
    def stage_commit(run_id: str, stage: str, winner_id: str, rationale: str, confidence: float, votes: dict[str, int] | None = None, cwd: str | None = None) -> dict[str, Any]:
        """Commit one verified winner and prune remaining stage candidates."""
        return _tools(cwd).stage_commit(run_id, stage, winner_id, rationale, confidence, votes=votes)

    @server.tool()
    def branch_add(run_id: str, stage: str, title: str, claim: str, difference: str, predictions: list[str] | None = None, falsifiers: list[str] | None = None, novelty: float = 0.5, parent_id: str | None = None, round_number: int = 0, admit: bool = True, cwd: str | None = None) -> dict[str, Any]:
        """Add and optionally admit a materially distinct branch."""
        return _tools(cwd).branch_add(run_id, stage, title, claim, difference, predictions=predictions, falsifiers=falsifiers, novelty=novelty, parent_id=parent_id, round_number=round_number, admit=admit)

    @server.tool()
    def branch_view(branch_id: str, cwd: str | None = None) -> dict[str, Any]:
        """Read one branch record."""
        return _tools(cwd).branch_view(branch_id)

    @server.tool()
    def branch_list(run_id: str, stage: str | None = None, status: str | None = None, cwd: str | None = None) -> list[dict[str, Any]]:
        """List branches, optionally filtering by stage or status."""
        return _tools(cwd).branch_list(run_id, stage=stage, status=status)

    @server.tool()
    def branch_start(run_id: str, branch_id: str, cwd: str | None = None) -> dict[str, Any]:
        """Move an admitted branch into running state."""
        return _tools(cwd).branch_start(run_id, branch_id)

    @server.tool()
    def branch_record_result(run_id: str, branch_id: str, proposal: str, evidence: list[str] | None = None, risks: list[str] | None = None, confidence: float = 0.5, artifacts: list[str] | None = None, cwd: str | None = None) -> dict[str, Any]:
        """Record an explorer result and move the branch to explored."""
        return _tools(cwd).branch_record_result(run_id, branch_id, proposal, evidence=evidence, risks=risks, confidence=confidence, artifacts=artifacts)

    @server.tool()
    def branch_verify(run_id: str, branch_id: str, verified: bool, scores: dict[str, float] | None = None, notes: list[str] | None = None, cwd: str | None = None) -> dict[str, Any]:
        """Record independent verification and optionally mark the branch verified."""
        return _tools(cwd).branch_verify(run_id, branch_id, verified=verified, scores=scores, notes=notes)

    @server.tool()
    def branch_prune(run_id: str, branch_id: str, reason: str, cwd: str | None = None) -> dict[str, Any]:
        """Prune a non-terminal branch with a durable reason."""
        return _tools(cwd).branch_prune(run_id, branch_id, reason)

    @server.tool()
    def branch_fail(run_id: str, branch_id: str, reason: str, cwd: str | None = None) -> dict[str, Any]:
        """Record a terminal branch failure and its reason."""
        return _tools(cwd).branch_fail(run_id, branch_id, reason)

    @server.tool()
    def claim_record(run_id: str, branch_id: str, statement: str, kind: str = "claim", status: str = "open", cwd: str | None = None) -> dict[str, Any]:
        """Attach a structured claim to a branch."""
        return _tools(cwd).claim_record(run_id, branch_id, statement, kind=kind, status=status)

    @server.tool()
    def evidence_record(run_id: str, branch_id: str, statement: str, kind: str = "observation", claim_id: str | None = None, source_uri: str | None = None, artifact_id: str | None = None, observed: bool = True, cwd: str | None = None) -> dict[str, Any]:
        """Attach typed evidence and provenance to a branch."""
        return _tools(cwd).evidence_record(run_id, branch_id, statement, kind=kind, claim_id=claim_id, source_uri=source_uri, artifact_id=artifact_id, observed=observed)

    @server.tool()
    def finding_record(run_id: str, branch_id: str, statement: str, kind: str = "insight", evidence_id: str | None = None, revisit_if: list[str] | None = None, cwd: str | None = None) -> dict[str, Any]:
        """Record a reusable insight, pitfall, or decision."""
        return _tools(cwd).finding_record(run_id, branch_id, statement, kind=kind, evidence_id=evidence_id, revisit_if=revisit_if)

    @server.tool()
    def artifact_store(run_id: str, branch_id: str, path: str, role: str = "branch-output", media_type: str | None = None, cwd: str | None = None) -> dict[str, Any]:
        """Store an explicitly authorized project file by content hash."""
        return _tools(cwd).artifact_store(run_id, branch_id, path, role=role, media_type=media_type)

    @server.tool()
    def tree_view(run_id: str, fmt: str = "compact", cwd: str | None = None) -> Any:
        """Render the durable branch tree as compact text, Markdown, or JSON."""
        return _tools(cwd).tree_view(run_id, fmt=fmt)

    @server.tool()
    def dossier_render(run_id: str, cwd: str | None = None) -> dict[str, Any]:
        """Render every branch dossier and the run decision record."""
        return _tools(cwd).dossier_render(run_id)

    return server


def run() -> None:
    build_server().run()
