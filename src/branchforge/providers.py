from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any


class ModelProvider(ABC):
    @abstractmethod
    async def complete(self, system: str, prompt: str) -> str:
        raise NotImplementedError


def _post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Provider returned HTTP {exc.code}: {detail}") from exc


class OpenAIProvider(ModelProvider):
    def __init__(self, model: str = "gpt-5.6-sol", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required")

    async def complete(self, system: str, prompt: str) -> str:
        data = await asyncio.to_thread(
            _post,
            "https://api.openai.com/v1/responses",
            {"authorization": f"Bearer {self.api_key}"},
            {"model": self.model, "instructions": system, "input": prompt},
        )
        if "output_text" in data:
            return str(data["output_text"])
        texts = [
            part.get("text", "")
            for item in data.get("output", [])
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        ]
        return "".join(texts)


class AnthropicProvider(ModelProvider):
    def __init__(self, model: str = "claude-fable-5", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")

    async def complete(self, system: str, prompt: str) -> str:
        data = await asyncio.to_thread(
            _post,
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            {
                "model": self.model,
                "max_tokens": 8192,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        return "".join(block.get("text", "") for block in data.get("content", []))


class MockProvider(ModelProvider):
    """Deterministic provider for local demos and orchestration tests."""

    async def complete(self, system: str, prompt: str) -> str:
        await asyncio.sleep(0)
        if "PROPOSE_BRANCHES" in prompt:
            return json.dumps({"branches": [
                {"title": "Evidence-first", "claim": "Prototype the riskiest assumption first", "difference": "Optimizes for information gain", "predictions": ["Key uncertainty resolves early"], "falsifiers": ["No measurable uncertainty reduction"], "novelty": 0.92},
                {"title": "Architecture-first", "claim": "Design stable interfaces before implementation", "difference": "Optimizes for composability", "predictions": ["Components remain replaceable"], "falsifiers": ["Interfaces block necessary iteration"], "novelty": 0.84},
                {"title": "Vertical slice", "claim": "Build the smallest end-to-end path", "difference": "Optimizes for integration feedback", "predictions": ["Integration defects surface early"], "falsifiers": ["Slice cannot test core risks"], "novelty": 0.79},
            ]})
        if "EXPLORE_BRANCH" in prompt:
            title = prompt.split("TITLE:", 1)[-1].splitlines()[0].strip()
            return json.dumps({"proposal": f"Execute {title} with explicit checkpoints and measurable acceptance tests.", "evidence": ["The approach has a falsifiable milestone", "Work can be reviewed incrementally"], "risks": ["The first checkpoint may expose invalid assumptions"], "confidence": 0.76, "artifacts": []})
        if "VERIFY_BRANCH" in prompt:
            return json.dumps({"verified": True, "scores": {"correctness": 0.82, "feasibility": 0.78, "simplicity": 0.74, "novelty": 0.70}, "notes": ["All declared invariants addressed"]})
        if "PAIRWISE_JUDGE" in prompt:
            return json.dumps({"winner": "A", "confidence": 0.72, "rationale": "A offers clearer falsification and earlier evidence."})
        if "FINAL_JUDGE" in prompt:
            return json.dumps({"winner_id": "FIRST", "confidence": 0.78, "rationale": "Selected for evidence quality and controlled execution risk."})
        return json.dumps({"ok": True})


def provider_from_name(name: str, model: str | None = None) -> ModelProvider:
    if name == "mock":
        return MockProvider()
    if name == "openai":
        return OpenAIProvider(model or "gpt-5.6-sol")
    if name == "anthropic":
        return AnthropicProvider(model or "claude-fable-5")
    raise ValueError(f"Unknown provider: {name}")
