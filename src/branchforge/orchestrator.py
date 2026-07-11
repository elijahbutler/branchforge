from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import asdict

from .jsonutil import parse_json_object
from .models import BranchResult, BranchStatus, Finding, Hypothesis, RunConfig, StageOutcome, StageSpec, new_id
from .policy import BranchPolicy
from .providers import ModelProvider
from .repository import BranchRepository
from .store import EventStore


SYSTEM = """You are one component in BranchForge, an evidence-driven agent search system.
Obey the requested role. Return only valid JSON. Separate claims from evidence. Never invent
completed tests, measurements, sources, or artifacts. Express uncertainty numerically."""

MODE_GUIDANCE = {
    "research": "Prioritize primary sources, citations, contradictory evidence, retrieval dates, and reproducible experiments.",
    "ideation": "Prioritize explicit assumptions, user value, comparable ideas, prototypes, critiques, and discriminating experiments.",
    "software": "Prioritize executable artifacts, diffs, commands, tests, benchmarks, failure behavior, and rollback evidence.",
    "hybrid": "Separate researched claims, product assumptions, and executable implementation evidence by type.",
}


class BranchForge:
    def __init__(self, provider: ModelProvider, store: EventStore, config: RunConfig | None = None, *, judge_provider: ModelProvider | None = None, repository: BranchRepository | None = None):
        self.provider = provider
        self.judge_provider = judge_provider or provider
        self.store = store
        self.config = config or RunConfig()
        self.config.validate()
        self.policy = BranchPolicy(self.config)
        self.repository = repository or BranchRepository(store)

    async def run(self, goal: str, stages: list[StageSpec]) -> list[StageOutcome]:
        run_id = new_id("run")
        committed_context = "No earlier stages."
        outcomes: list[StageOutcome] = []
        self.repository.create_run(run_id, goal, self.config)
        try:
            for stage in stages:
                outcome = await self._run_stage(run_id, goal, stage, committed_context)
                outcomes.append(outcome)
                committed_context += f"\nCommitted {stage.name}: {outcome.winner.proposal}"
            self.repository.finish_run(run_id)
            self.repository.render_run(run_id)
            return outcomes
        except Exception as exc:
            self.repository.finish_run(run_id, error=str(exc))
            self.repository.render_run(run_id)
            raise

    async def _run_stage(self, run_id: str, goal: str, stage: StageSpec, context: str) -> StageOutcome:
        self.repository.create_stage(run_id, stage)
        survivors: list[BranchResult] = []
        for round_number in range(self.config.max_rounds):
            round_context = context
            if survivors:
                round_context += "\nSURVIVING CANDIDATES TO CHALLENGE OR IMPROVE:\n" + json.dumps([asdict(item) for item in survivors])
            hypotheses = await self._propose(goal, stage, round_context, round_number, survivors)
            admitted = self.policy.admit(hypotheses)
            if len(admitted) < 2:
                raise RuntimeError("Branch policy admitted fewer than two competing hypotheses")
            for item in hypotheses:
                self.repository.create_branch(run_id, stage.name, item, stage.mode)
                if item in admitted:
                    self.repository.transition(run_id, item.id, BranchStatus.ADMITTED)
                else:
                    self.repository.transition(run_id, item.id, BranchStatus.PRUNED, reason="Rejected by novelty or duplicate admission policy")
            results = await asyncio.gather(*(self._explore_and_verify(run_id, goal, stage, round_context, item) for item in admitted))
            candidates = [*survivors, *results]
            survivors = self.policy.survivors(candidates)
            survivor_ids = {item.hypothesis.id for item in survivors}
            for item in candidates:
                if item.hypothesis.id in survivor_ids:
                    continue
                branch = self.repository.get_branch(item.hypothesis.id)
                if branch and branch["status"] in {BranchStatus.EXPLORED.value, BranchStatus.VERIFIED.value}:
                    self.repository.transition(run_id, item.hypothesis.id, BranchStatus.PRUNED, reason="Removed from survivor beam")
            self.store.append(run_id, "ROUND_COMPLETED", {"round": round_number, "survivors": [item.hypothesis.id for item in survivors]}, stage=stage.name)
        votes = await self._pairwise_tournament(run_id, stage, survivors)
        if not any(candidate.verified for candidate in survivors):
            raise RuntimeError(f"Stage {stage.name!r} has no verified candidate to commit")
        winner, rationale, confidence = await self._final_judge(goal, stage, survivors, votes)
        outcome = StageOutcome(stage, winner, survivors, rationale, confidence, run_id)
        for branch in self.repository.branches(run_id):
            if branch["stage"] != stage.name or branch["branch_id"] == winner.hypothesis.id:
                continue
            if branch["status"] in {BranchStatus.EXPLORED.value, BranchStatus.VERIFIED.value}:
                self.repository.transition(run_id, branch["branch_id"], BranchStatus.PRUNED, reason="Not selected at stage collapse")
        self.repository.transition(run_id, winner.hypothesis.id, BranchStatus.COMMITTED)
        self.repository.record_finding(run_id, Finding(
            winner.hypothesis.id,
            f"Committed for stage {stage.name}: {rationale}",
            kind="decision",
        ))
        self.repository.finish_stage(run_id, stage.name, winner.hypothesis.id, rationale, confidence, dict(votes))
        self.repository.render_run(run_id)
        return outcome

    async def _propose(self, goal: str, stage: StageSpec, context: str, round_number: int, parents: list[BranchResult]) -> list[Hypothesis]:
        prompt = f"""PROPOSE_BRANCHES
GOAL: {goal}
STAGE: {json.dumps(asdict(stage))}
COMMITTED CONTEXT: {context}
ROUND: {round_number}
Generate {self.config.max_branches} materially different, mutually competing hypotheses.
Schema: {{"branches":[{{"title":str,"claim":str,"difference":str,"predictions":[str],"falsifiers":[str],"novelty":0..1}}]}}"""
        data = parse_json_object(await self.provider.complete(SYSTEM, prompt))
        parent_ids = {parent.hypothesis.id for parent in parents}
        return [Hypothesis(
            title=str(item["title"]), claim=str(item["claim"]), difference=str(item["difference"]),
            predictions=list(item.get("predictions", [])), falsifiers=list(item.get("falsifiers", [])),
            novelty=float(item.get("novelty", 0)),
            parent_id=(str(item.get("parent_id")) if item.get("parent_id") in parent_ids else parents[0].hypothesis.id if parents else None),
            round=round_number,
        ) for item in data.get("branches", [])]

    async def _explore_and_verify(self, run_id: str, goal: str, stage: StageSpec, context: str, hypothesis: Hypothesis) -> BranchResult:
        prompt = f"""EXPLORE_BRANCH
GOAL: {goal}
STAGE: {json.dumps(asdict(stage))}
CONTEXT: {context}
TITLE: {hypothesis.title}
HYPOTHESIS: {json.dumps(asdict(hypothesis))}
MODE EVIDENCE POLICY: {MODE_GUIDANCE[stage.mode.value]}
Develop only this branch. Schema: {{"proposal":str,"evidence":[str],"risks":[str],"confidence":0..1,"artifacts":[str]}}"""
        try:
            self.repository.transition(run_id, hypothesis.id, BranchStatus.RUNNING)
            raw = await asyncio.wait_for(self.provider.complete(SYSTEM, prompt), self.config.branch_timeout_seconds)
            data = parse_json_object(raw)
            result = BranchResult(hypothesis, str(data["proposal"]), list(data.get("evidence", [])), list(data.get("risks", [])), float(data.get("confidence", 0)), list(data.get("artifacts", [])))
            self.repository.record_result(run_id, result)
            self.repository.transition(run_id, hypothesis.id, BranchStatus.EXPLORED)
            await self._verify(run_id, stage, result)
            return result
        except Exception as exc:
            branch = self.repository.get_branch(hypothesis.id)
            if branch and branch["status"] in {BranchStatus.RUNNING.value, BranchStatus.EXPLORED.value}:
                self.repository.transition(run_id, hypothesis.id, BranchStatus.FAILED, reason=str(exc))
            return BranchResult(hypothesis, "Branch execution failed", [], [str(exc)], 0.0)

    async def _verify(self, run_id: str, stage: StageSpec, result: BranchResult) -> None:
        prompt = f"""VERIFY_BRANCH
STAGE: {json.dumps(asdict(stage))}
CANDIDATE: {json.dumps(asdict(result))}
Check invariants and score each rubric key from 0 to 1. Unsupported claims score poorly.
Schema: {{"verified":bool,"scores":{{"criterion":0..1}},"notes":[str]}}"""
        data = parse_json_object(await self.judge_provider.complete(SYSTEM, prompt))
        result.verified = bool(data.get("verified", False))
        weights = stage.rubric
        raw_scores = data.get("scores", {})
        result.scores = {key: float(raw_scores.get(key, 0)) * weight for key, weight in weights.items()}
        notes = list(data.get("notes", []))
        self.repository.record_verification(run_id, result, notes)
        if result.verified:
            self.repository.transition(run_id, result.hypothesis.id, BranchStatus.VERIFIED)

    async def _pairwise_tournament(self, run_id: str, stage: StageSpec, candidates: list[BranchResult]) -> Counter[str]:
        votes: Counter[str] = Counter()
        for index, left in enumerate(candidates):
            for right in candidates[index + 1:]:
                prompt = f"""PAIRWISE_JUDGE
RUBRIC: {json.dumps(stage.rubric)}
CANDIDATE A: {json.dumps(asdict(left))}
CANDIDATE B: {json.dumps(asdict(right))}
Judge evidence, not style. Schema: {{"winner":"A"|"B"|"TIE","confidence":0..1,"rationale":str}}"""
                data = parse_json_object(await self.judge_provider.complete(SYSTEM, prompt))
                selected = left if data.get("winner") == "A" else right if data.get("winner") == "B" else None
                if selected:
                    votes[selected.hypothesis.id] += 1
                self.store.append(run_id, "PAIRWISE_JUDGMENT", {"a": left.hypothesis.id, "b": right.hypothesis.id, **data}, stage=stage.name)
        return votes

    async def _final_judge(self, goal: str, stage: StageSpec, candidates: list[BranchResult], votes: Counter[str]) -> tuple[BranchResult, str, float]:
        prompt = f"""FINAL_JUDGE
GOAL: {goal}
STAGE: {json.dumps(asdict(stage))}
CANDIDATES: {json.dumps([asdict(item) for item in candidates])}
TOURNAMENT VOTES: {json.dumps(dict(votes))}
Choose a candidate ID. Schema: {{"winner_id":str,"confidence":0..1,"rationale":str}}"""
        data = parse_json_object(await self.judge_provider.complete(SYSTEM, prompt))
        requested = data.get("winner_id")
        winner = next((item for item in candidates if item.hypothesis.id == requested), None)
        if winner is None:  # Also makes mock/local mode deterministic.
            winner = max(candidates, key=lambda item: (votes[item.hypothesis.id], item.score, item.confidence))
        return winner, str(data.get("rationale", "Highest verified candidate.")), float(data.get("confidence", winner.confidence))
