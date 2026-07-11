from __future__ import annotations

from .models import BranchResult, Hypothesis, RunConfig


class BranchPolicy:
    """Deterministic resource policy around model-generated hypotheses."""

    def __init__(self, config: RunConfig):
        self.config = config

    def admit(self, hypotheses: list[Hypothesis]) -> list[Hypothesis]:
        unique: list[Hypothesis] = []
        seen: set[str] = set()
        for hypothesis in sorted(hypotheses, key=lambda item: item.novelty, reverse=True):
            signature = " ".join(hypothesis.title.lower().split())
            if hypothesis.novelty < self.config.novelty_threshold or signature in seen:
                continue
            seen.add(signature)
            unique.append(hypothesis)
            if len(unique) == self.config.max_branches:
                break
        return unique

    def survivors(self, results: list[BranchResult]) -> list[BranchResult]:
        valid = [result for result in results if result.verified]
        ranked = sorted(valid or results, key=lambda result: (result.score, result.confidence), reverse=True)
        return ranked[: self.config.survivor_width]
