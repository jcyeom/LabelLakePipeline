"""LLM labeler adapter (FR-3 LLM Labeler, §14.3, §19.1).

The model call is injected as ``client`` (a callable) so tests run deterministically
without a network. Parse failures return FAILED instead of raising — failure must not
propagate to the whole pipeline (FR-3 수용 기준, NFR-2).
"""
from __future__ import annotations

import json
from typing import Callable, Optional

from app.domain.enums import L1Status, LabelMethod
from app.services.labelers.base import LabelerAdapter, LabelResult, Sample
from app.util import sha256_hash

# A client maps a rendered prompt string to a raw model response string.
LLMClient = Callable[[str], str]


class LLMLabeler(LabelerAdapter):
    method = LabelMethod.LLM

    def __init__(
        self,
        run_id: str,
        client: LLMClient,
        *,
        model: str = "llm-model-name",
        prompt_template: str = "Classify: {features}",
        temperature: float = 0.0,
        top_p: float = 1.0,
        seed: int = 42,
        max_retries: int = 3,
    ):
        super().__init__(run_id)
        self.client = client
        self.model = model
        self.prompt_template = prompt_template
        self.temperature = temperature
        self.top_p = top_p
        self.seed = seed
        self.max_retries = max_retries

    def prompt_hash(self) -> str:
        return sha256_hash(self.prompt_template)[:23]  # short "sha256:" + prefix

    def method_ver(self) -> str:
        # Prompt change ⇒ method_ver change (FR-3 수용 기준).
        return f"{self.model}_{self.prompt_hash()}"

    def _render(self, sample: Sample) -> str:
        return self.prompt_template.format(features=json.dumps(sample.features, sort_keys=True))

    def _parse(self, raw: str) -> dict:
        """Parse the model response. Expected JSON: {"value": ..., "confidence": ...}."""
        obj = json.loads(raw)
        if "value" not in obj:
            raise ValueError("missing 'value' in model response")
        return obj

    def run(self, sample: Sample) -> LabelResult:
        prompt = self._render(sample)
        last_error: Optional[str] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                raw = self.client(prompt)
                parsed = self._parse(raw)
            except Exception as exc:  # parse/call failure is isolated (NFR-2)
                last_error = f"attempt {attempt}: {exc}"
                continue
            payload = self._build(
                sample,
                parsed["value"],
                confidence=parsed.get("confidence"),
                rationale=parsed.get("rationale") or {"raw": raw[:2000]},
                metadata={
                    "model": self.model,
                    "prompt_hash": self.prompt_hash(),
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                    "seed": self.seed,
                },
            )
            return LabelResult(status=L1Status.CREATED, payload=payload)
        return LabelResult(status=L1Status.FAILED, error=last_error or "llm parse failure")
