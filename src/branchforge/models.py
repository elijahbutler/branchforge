from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class BranchMode(StrEnum):
    RESEARCH = "research"
    IDEATION = "ideation"
    SOFTWARE = "software"
    HYBRID = "hybrid"


class BranchStatus(StrEnum):
    PROPOSED = "proposed"
    ADMITTED = "admitted"
    RUNNING = "running"
    EXPLORED = "explored"
    VERIFIED = "verified"
    PRUNED = "pruned"
    FAILED = "failed"
    COMMITTED = "committed"


@dataclass(slots=True)
class StageSpec:
    name: str
    objective: str
    deliverable: str = "A verified recommendation"
    invariants: list[str] = field(default_factory=list)
    mode: BranchMode = BranchMode.HYBRID
    rubric: dict[str, float] = field(
        default_factory=lambda: {
            "correctness": 0.4,
            "feasibility": 0.25,
            "simplicity": 0.2,
            "novelty": 0.15,
        }
    )


@dataclass(slots=True)
class RunConfig:
    max_branches: int = 3
    survivor_width: int = 2
    max_rounds: int = 2
    novelty_threshold: float = 0.6
    minimum_win_margin: float = 0.08
    branch_timeout_seconds: float = 180.0

    def validate(self) -> None:
        if not 2 <= self.max_branches <= 8:
            raise ValueError("max_branches must be between 2 and 8")
        if not 1 <= self.survivor_width <= self.max_branches:
            raise ValueError("survivor_width must be within max_branches")
        if not 1 <= self.max_rounds <= 10:
            raise ValueError("max_rounds must be between 1 and 10")


@dataclass(slots=True)
class Hypothesis:
    title: str
    claim: str
    difference: str
    predictions: list[str]
    falsifiers: list[str]
    novelty: float
    id: str = field(default_factory=lambda: new_id("branch"))
    parent_id: str | None = None
    round: int = 0


@dataclass(slots=True)
class BranchResult:
    hypothesis: Hypothesis
    proposal: str
    evidence: list[str]
    risks: list[str]
    confidence: float
    artifacts: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    verified: bool = False

    @property
    def score(self) -> float:
        return sum(self.scores.values()) if self.scores else 0.0


@dataclass(slots=True)
class StageOutcome:
    stage: StageSpec
    winner: BranchResult
    survivors: list[BranchResult]
    rationale: str
    confidence: float
    run_id: str


@dataclass(slots=True)
class Claim:
    branch_id: str
    statement: str
    kind: str = "hypothesis"
    status: str = "open"
    id: str = field(default_factory=lambda: new_id("claim"))


@dataclass(slots=True)
class Evidence:
    branch_id: str
    statement: str
    kind: str = "model_assertion"
    claim_id: str | None = None
    source_uri: str | None = None
    artifact_id: str | None = None
    observed: bool = False
    id: str = field(default_factory=lambda: new_id("evidence"))


@dataclass(slots=True)
class ArtifactRef:
    branch_id: str
    sha256: str
    media_type: str
    size: int
    role: str
    object_path: str
    source_uri: str | None = None
    id: str = field(default_factory=lambda: new_id("artifact"))


@dataclass(slots=True)
class Finding:
    branch_id: str
    statement: str
    kind: str = "insight"
    evidence_id: str | None = None
    revisit_if: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: new_id("finding"))


def to_dict(value: Any) -> dict[str, Any]:
    return asdict(value)
