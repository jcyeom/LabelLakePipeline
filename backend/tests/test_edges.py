"""Targeted edge-case coverage: labeler parse guard, repo empty/active-only paths,
fusion policy fallbacks."""
from __future__ import annotations

from app.domain.enums import FusionPolicy, L1Status, L2Flag
from app.domain.schemas import LabelObjectIn
from app.repositories.labels import LabelRepository
from app.services.fusion import FusionEngine
from app.services.labelers.base import Sample
from app.services.labelers.llm import LLMLabeler
from tests.conftest import l1_payload


def _l1(repo, **ov):
    return repo.create_l1(LabelObjectIn(**l1_payload(**ov)))


def test_llm_valid_json_missing_value_key_fails():
    """Valid JSON without a 'value' key is a parse failure (FAILED, not raise)."""
    labeler = LLMLabeler("run-x", lambda _prompt: '{"confidence": 0.9}')
    result = labeler.run(Sample("s1", "f1", "fv1", {"x": 1}))
    assert result.status == L1Status.FAILED


def test_get_l1_by_samples_active_only_filters_non_created(db_session):
    repo = LabelRepository(db_session)
    _l1(repo, sample_id="ao")
    repo.create_l1(LabelObjectIn(**l1_payload(sample_id="ao")), status=L1Status.FAILED)
    grouped = repo.get_l1_by_samples(["ao"], active_only=True)
    assert len(grouped["ao"]) == 1
    assert grouped["ao"][0].status == L1Status.CREATED.value


def test_get_active_l3_by_samples_empty_input_returns_empty(db_session):
    assert LabelRepository(db_session).get_active_l3_by_samples([]) == {}


def test_get_l1_by_ids_empty_input_returns_empty(db_session):
    assert LabelRepository(db_session).get_l1_by_ids([]) == []


def test_all_sample_ids_returns_distinct(db_session):
    repo = LabelRepository(db_session)
    _l1(repo, sample_id="d1")
    _l1(repo, sample_id="d1")
    _l1(repo, sample_id="d2")
    assert set(repo.all_sample_ids()) == {"d1", "d2"}


def test_rule_priority_falls_back_to_majority_without_rule_labels(db_session):
    repo = LabelRepository(db_session)
    a = _l1(repo, method="llm", method_ver="v1", value="high", confidence=0.9)
    b = _l1(repo, method="human", method_ver="h1", value="high", confidence=0.8)
    decision = FusionEngine().decide([a, b], policy=FusionPolicy.RULE_PRIORITY)
    assert decision.value == "high"  # no rule labels → majority fallback


def test_confidence_weighted_unanimous_is_agreed(db_session):
    repo = LabelRepository(db_session)
    a = _l1(repo, method="llm", method_ver="v1", value="high", confidence=0.9)
    b = _l1(repo, method="rule", method_ver="r1", value="high", confidence=0.8)
    decision = FusionEngine().decide([a, b], policy=FusionPolicy.CONFIDENCE_WEIGHTED)
    assert decision.flag == L2Flag.AGREED


def test_human_priority_prefers_human_value(db_session):
    repo = LabelRepository(db_session)
    a = _l1(repo, method="llm", method_ver="v1", value="high", confidence=0.95)
    b = _l1(repo, method="human", method_ver="h1", value="low", confidence=0.5)
    decision = FusionEngine().decide([a, b], policy=FusionPolicy.HUMAN_PRIORITY)
    assert decision.value == "low"  # human-priority overrides higher-confidence llm
