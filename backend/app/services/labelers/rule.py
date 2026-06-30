"""Rule labeler adapter (FR-3 Rule Labeler)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from app.domain.enums import L1Status, LabelMethod
from app.services.labelers.base import LabelerAdapter, LabelResult, Sample


@dataclass
class Rule:
    """A deterministic rule: ``predicate(features)`` -> bool, emitting ``value``."""

    rule_id: str
    name: str
    predicate: Callable[[dict], bool]
    value: object
    confidence: float = 1.0


class RuleLabeler(LabelerAdapter):
    """Deterministic rule evaluation. Stores rule id/version + matched rule name in
    rationale (FR-3). Returns SKIPPED when no rule matches."""

    method = LabelMethod.RULE

    def __init__(self, run_id: str, rules: list[Rule], *, ruleset_version: str = "rule-v1"):
        super().__init__(run_id)
        self.rules = rules
        self.ruleset_version = ruleset_version
        self._matched: Optional[Rule] = None

    def method_ver(self) -> str:
        matched = self._matched.rule_id if self._matched else "none"
        return f"{self.ruleset_version}:{matched}"

    def run(self, sample: Sample) -> LabelResult:
        for rule in self.rules:
            try:
                if rule.predicate(sample.features):
                    self._matched = rule
                    payload = self._build(
                        sample,
                        rule.value,
                        confidence=rule.confidence,
                        rationale={"rule_id": rule.rule_id, "matched_rule": rule.name},
                    )
                    return LabelResult(status=L1Status.CREATED, payload=payload)
            except Exception as exc:  # a faulty predicate must not crash the pipeline (NFR-2)
                return LabelResult(status=L1Status.FAILED, error=f"rule {rule.rule_id} error: {exc}")
        self._matched = None
        return LabelResult(status=L1Status.SKIPPED, error="no rule matched")
