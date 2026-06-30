"""Tests for labeler adapters (FR-3) and LabelingPipeline (§10.1).

Adapter tests use direct object calls — no DB needed.
Pipeline tests use the db_session fixture from conftest.
"""
from __future__ import annotations

import pytest

from app.domain.enums import L1Status, LabelMethod
from app.repositories.labels import LabelRepository
from app.services.labelers.base import Sample
from app.services.labelers.human import HumanLabeler
from app.services.labelers.llm import LLMLabeler
from app.services.labelers.rule import Rule, RuleLabeler
from app.services.pipeline import LabelingPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample(sample_id: str = "s-001", features: dict | None = None) -> Sample:
    return Sample(
        sample_id=sample_id,
        feature_id="feat-001",
        feature_version="fv-1",
        features=features or {"risk_score": 0.9},
        task_type="classification",
    )


def _matching_rule(value="high_risk") -> Rule:
    return Rule(
        rule_id="rule-001",
        name="high-risk-rule",
        predicate=lambda f: f.get("risk_score", 0) > 0.5,
        value=value,
        confidence=1.0,
    )


def _non_matching_rule() -> Rule:
    return Rule(
        rule_id="rule-002",
        name="low-risk-rule",
        predicate=lambda f: f.get("risk_score", 0) > 0.99,
        value="low_risk",
    )


def _exploding_rule() -> Rule:
    def _bad_predicate(f: dict) -> bool:
        raise RuntimeError("predicate boom")

    return Rule(
        rule_id="rule-boom",
        name="boom",
        predicate=_bad_predicate,
        value="error_value",
    )


# ---------------------------------------------------------------------------
# RuleLabeler tests
# ---------------------------------------------------------------------------

class TestRuleLabeler:
    def test_matching_rule_returns_created_status(self):
        labeler = RuleLabeler("run-1", [_matching_rule()])
        result = labeler.run(_sample())
        assert result.status == L1Status.CREATED

    def test_matching_rule_payload_value_is_correct(self):
        labeler = RuleLabeler("run-1", [_matching_rule(value="high_risk")])
        result = labeler.run(_sample())
        assert result.payload is not None
        assert result.payload.value == "high_risk"

    def test_matching_rule_rationale_contains_rule_id(self):
        labeler = RuleLabeler("run-1", [_matching_rule()])
        result = labeler.run(_sample())
        assert result.payload is not None
        assert result.payload.rationale is not None
        assert "rule_id" in result.payload.rationale
        assert result.payload.rationale["rule_id"] == "rule-001"

    def test_matching_rule_rationale_contains_matched_rule(self):
        labeler = RuleLabeler("run-1", [_matching_rule()])
        result = labeler.run(_sample())
        assert result.payload is not None
        assert "matched_rule" in result.payload.rationale

    def test_no_matching_rule_returns_skipped_status(self):
        labeler = RuleLabeler("run-1", [_non_matching_rule()])
        result = labeler.run(_sample())
        assert result.status == L1Status.SKIPPED

    def test_no_matching_rule_payload_is_none(self):
        labeler = RuleLabeler("run-1", [_non_matching_rule()])
        result = labeler.run(_sample())
        assert result.payload is None

    def test_exploding_predicate_returns_failed_status(self):
        """A faulty predicate must not crash the pipeline (NFR-2)."""
        labeler = RuleLabeler("run-1", [_exploding_rule()])
        result = labeler.run(_sample())
        assert result.status == L1Status.FAILED

    def test_exploding_predicate_payload_is_none(self):
        labeler = RuleLabeler("run-1", [_exploding_rule()])
        result = labeler.run(_sample())
        assert result.payload is None

    def test_exploding_predicate_does_not_raise(self):
        """Running a labeler with an exploding predicate must not raise."""
        labeler = RuleLabeler("run-1", [_exploding_rule()])
        try:
            labeler.run(_sample())
        except Exception as exc:
            pytest.fail(f"RuleLabeler.run raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# LLMLabeler tests
# ---------------------------------------------------------------------------

class TestLLMLabeler:
    def _good_client(self, prompt: str) -> str:
        return '{"value": "high_risk", "confidence": 0.9}'

    def test_valid_response_returns_created_status(self):
        labeler = LLMLabeler("run-llm", self._good_client)
        result = labeler.run(_sample())
        assert result.status == L1Status.CREATED

    def test_valid_response_payload_value_is_correct(self):
        labeler = LLMLabeler("run-llm", self._good_client)
        result = labeler.run(_sample())
        assert result.payload is not None
        assert result.payload.value == "high_risk"

    def test_valid_response_metadata_contains_model(self):
        labeler = LLMLabeler("run-llm", self._good_client, model="test-model")
        result = labeler.run(_sample())
        assert result.payload is not None
        assert result.payload.metadata is not None
        assert result.payload.metadata["model"] == "test-model"

    def test_valid_response_metadata_contains_prompt_hash(self):
        labeler = LLMLabeler("run-llm", self._good_client)
        result = labeler.run(_sample())
        assert "prompt_hash" in result.payload.metadata

    def test_valid_response_metadata_contains_seed(self):
        labeler = LLMLabeler("run-llm", self._good_client, seed=99)
        result = labeler.run(_sample())
        assert result.payload.metadata["seed"] == 99

    def test_valid_response_metadata_contains_temperature(self):
        labeler = LLMLabeler("run-llm", self._good_client, temperature=0.5)
        result = labeler.run(_sample())
        assert result.payload.metadata["temperature"] == 0.5

    def test_invalid_json_returns_failed_after_retries(self):
        """Client returning invalid JSON must yield FAILED, not raise (FR-3 수용 기준)."""
        bad_client = lambda p: "not json"
        labeler = LLMLabeler("run-llm", bad_client, max_retries=3)
        result = labeler.run(_sample())
        assert result.status == L1Status.FAILED

    def test_invalid_json_payload_is_none(self):
        bad_client = lambda p: "not json"
        labeler = LLMLabeler("run-llm", bad_client, max_retries=3)
        result = labeler.run(_sample())
        assert result.payload is None

    def test_invalid_json_does_not_raise(self):
        bad_client = lambda p: "not json"
        labeler = LLMLabeler("run-llm", bad_client, max_retries=3)
        try:
            labeler.run(_sample())
        except Exception as exc:
            pytest.fail(f"LLMLabeler.run raised unexpectedly: {exc}")

    def test_method_ver_changes_when_prompt_template_changes(self):
        """Different prompt templates must produce different method_ver (FR-3 수용 기준)."""
        client = self._good_client
        labeler_a = LLMLabeler("run-a", client, prompt_template="Classify: {features}")
        labeler_b = LLMLabeler("run-b", client, prompt_template="Rate risk: {features}")
        assert labeler_a.method_ver() != labeler_b.method_ver()

    def test_method_ver_stable_for_same_prompt_template(self):
        """Same prompt template always yields the same method_ver."""
        client = self._good_client
        labeler_a = LLMLabeler("run-a", client, prompt_template="Classify: {features}")
        labeler_b = LLMLabeler("run-b", client, prompt_template="Classify: {features}")
        assert labeler_a.method_ver() == labeler_b.method_ver()


# ---------------------------------------------------------------------------
# HumanLabeler tests
# ---------------------------------------------------------------------------

class TestHumanLabeler:
    def test_label_returns_created_status(self):
        labeler = HumanLabeler("run-human", reviewer_id="reviewer-42")
        result = labeler.label(_sample(), "high_risk", comment="looks risky")
        assert result.status == L1Status.CREATED

    def test_label_payload_value_is_correct(self):
        labeler = HumanLabeler("run-human", reviewer_id="reviewer-42")
        result = labeler.label(_sample(), "medium_risk")
        assert result.payload is not None
        assert result.payload.value == "medium_risk"

    def test_label_metadata_contains_reviewer_id(self):
        labeler = HumanLabeler("run-human", reviewer_id="reviewer-42")
        result = labeler.label(_sample(), "high_risk", comment="check this")
        assert result.payload is not None
        assert result.payload.metadata is not None
        assert result.payload.metadata["reviewer_id"] == "reviewer-42"

    def test_label_rationale_contains_reviewer_id(self):
        labeler = HumanLabeler("run-human", reviewer_id="reviewer-42")
        result = labeler.label(_sample(), "high_risk", comment="my note")
        assert result.payload.rationale is not None
        assert result.payload.rationale["reviewer_id"] == "reviewer-42"

    def test_label_rationale_contains_comment(self):
        labeler = HumanLabeler("run-human", reviewer_id="reviewer-42")
        result = labeler.label(_sample(), "high_risk", comment="my note")
        assert result.payload.rationale["comment"] == "my note"

    def test_run_without_explicit_value_returns_skipped(self):
        """run() without an explicit value must be SKIPPED — human flow requires label()."""
        labeler = HumanLabeler("run-human", reviewer_id="reviewer-42")
        result = labeler.run(_sample())
        assert result.status == L1Status.SKIPPED


# ---------------------------------------------------------------------------
# LabelingPipeline tests
# ---------------------------------------------------------------------------

class TestLabelingPipeline:
    def test_pipeline_persists_created_and_failed_rows(self, db_session):
        """Running [matching RuleLabeler, failing LLMLabeler] persists both rows."""
        sample = _sample()

        rule_labeler = RuleLabeler("run-pipe", [_matching_rule()])
        bad_llm = LLMLabeler("run-pipe", lambda p: "not json", max_retries=1)

        pipeline = LabelingPipeline(db_session)
        pipeline.run_sample(sample, [rule_labeler, bad_llm])
        db_session.commit()

        repo = LabelRepository(db_session)
        all_rows = repo.get_l1_by_sample(sample.sample_id, active_only=False)
        assert len(all_rows) == 2

    def test_pipeline_created_row_has_created_status(self, db_session):
        sample = _sample()
        rule_labeler = RuleLabeler("run-pipe", [_matching_rule()])
        bad_llm = LLMLabeler("run-pipe", lambda p: "not json", max_retries=1)

        pipeline = LabelingPipeline(db_session)
        pipeline.run_sample(sample, [rule_labeler, bad_llm])
        db_session.commit()

        repo = LabelRepository(db_session)
        all_rows = repo.get_l1_by_sample(sample.sample_id, active_only=False)
        statuses = {row.status for row in all_rows}
        assert "CREATED" in statuses

    def test_pipeline_failed_row_has_failed_status(self, db_session):
        sample = _sample()
        rule_labeler = RuleLabeler("run-pipe", [_matching_rule()])
        bad_llm = LLMLabeler("run-pipe", lambda p: "not json", max_retries=1)

        pipeline = LabelingPipeline(db_session)
        pipeline.run_sample(sample, [rule_labeler, bad_llm])
        db_session.commit()

        repo = LabelRepository(db_session)
        all_rows = repo.get_l1_by_sample(sample.sample_id, active_only=False)
        statuses = {row.status for row in all_rows}
        assert "FAILED" in statuses

    def test_pipeline_returns_ids_for_created_rows_only(self, db_session):
        """run_sample returns label_ids only for CREATED rows."""
        sample = _sample()
        rule_labeler = RuleLabeler("run-pipe", [_matching_rule()])
        bad_llm = LLMLabeler("run-pipe", lambda p: "not json", max_retries=1)

        pipeline = LabelingPipeline(db_session)
        created_ids = pipeline.run_sample(sample, [rule_labeler, bad_llm])

        # Only the CREATED row id is returned
        assert len(created_ids) == 1
        assert created_ids[0].startswith("l1-")

    def test_pipeline_does_not_crash_when_all_adapters_fail(self, db_session):
        """Pipeline is resilient to all adapters failing (NFR-2)."""
        sample = _sample()
        bad_llm = LLMLabeler("run-pipe", lambda p: "not json", max_retries=1)

        pipeline = LabelingPipeline(db_session)
        try:
            pipeline.run_sample(sample, [bad_llm])
        except Exception as exc:
            pytest.fail(f"Pipeline raised unexpectedly: {exc}")
