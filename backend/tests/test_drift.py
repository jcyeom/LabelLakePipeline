"""Tests for drift detection (FR-7, AC-5).

Pure-function tests on PSI/KL math, plus DriftService integration tests
using the db_session fixture and LabelRepository for seeding.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.enums import DriftStatus, L1Status, LabelMethod
from app.domain.schemas import DriftRunRequest, LabelObjectIn
from app.models.orm import LabelL1Candidate, LabelL3Gold
from app.repositories.labels import LabelRepository
from app.services.drift import DriftService, kl_divergence, population_stability_index
from app.util import new_id, now_utc


# ---------------------------------------------------------------------------
# Pure-function tests: PSI
# ---------------------------------------------------------------------------

class TestPopulationStabilityIndex:
    def test_identical_distributions_psi_is_near_zero(self):
        dist = {"high_risk": 0.6, "low_risk": 0.4}
        result = population_stability_index(dist, dist)
        assert result < 1e-6

    def test_clearly_shifted_distributions_psi_is_positive(self):
        baseline = {"high_risk": 0.6, "low_risk": 0.4}
        current = {"high_risk": 0.1, "low_risk": 0.9}
        result = population_stability_index(baseline, current)
        assert result > 0.0

    def test_larger_shift_produces_larger_psi(self):
        baseline = {"high_risk": 0.5, "low_risk": 0.5}
        small_shift = {"high_risk": 0.45, "low_risk": 0.55}
        large_shift = {"high_risk": 0.1, "low_risk": 0.9}
        psi_small = population_stability_index(baseline, small_shift)
        psi_large = population_stability_index(baseline, large_shift)
        assert psi_large > psi_small

    def test_psi_symmetric_same_categories(self):
        """PSI is not strictly symmetric, but a perfectly inverted shift still > 0."""
        baseline = {"a": 0.7, "b": 0.3}
        current = {"a": 0.3, "b": 0.7}
        result = population_stability_index(baseline, current)
        assert result > 0.0

    def test_psi_with_category_only_in_baseline(self):
        """A category that disappears from current should still produce a positive PSI."""
        baseline = {"a": 0.6, "b": 0.4}
        current = {"a": 1.0}
        result = population_stability_index(baseline, current)
        assert result > 0.0

    def test_psi_with_category_only_in_current(self):
        """A new category in current should still produce a positive PSI."""
        baseline = {"a": 1.0}
        current = {"a": 0.6, "b": 0.4}
        result = population_stability_index(baseline, current)
        assert result > 0.0


# ---------------------------------------------------------------------------
# Pure-function tests: KL divergence
# ---------------------------------------------------------------------------

class TestKLDivergence:
    def test_identical_distributions_kl_is_near_zero(self):
        dist = {"high_risk": 0.6, "low_risk": 0.4}
        result = kl_divergence(dist, dist)
        assert result < 1e-6

    def test_shifted_distributions_kl_is_positive(self):
        baseline = {"high_risk": 0.6, "low_risk": 0.4}
        current = {"high_risk": 0.1, "low_risk": 0.9}
        result = kl_divergence(baseline, current)
        assert result > 0.0

    def test_larger_shift_produces_larger_kl(self):
        baseline = {"high_risk": 0.5, "low_risk": 0.5}
        small_shift = {"high_risk": 0.45, "low_risk": 0.55}
        large_shift = {"high_risk": 0.1, "low_risk": 0.9}
        kl_small = kl_divergence(baseline, small_shift)
        kl_large = kl_divergence(baseline, large_shift)
        assert kl_large > kl_small

    def test_kl_with_category_only_in_current(self):
        """New category in current produces a finite, positive KL value."""
        baseline = {"a": 1.0}
        current = {"a": 0.5, "b": 0.5}
        result = kl_divergence(baseline, current)
        assert result > 0.0


# ---------------------------------------------------------------------------
# Helpers for DB-backed tests
# ---------------------------------------------------------------------------

_BASELINE_START = "2026-01-01T00:00:00"
_BASELINE_END = "2026-02-01T00:00:00"
_CURRENT_START = "2026-02-01T00:00:00"
_CURRENT_END = "2026-03-01T00:00:00"

BASELINE_WINDOW = f"{_BASELINE_START}/{_BASELINE_END}"
CURRENT_WINDOW = f"{_CURRENT_START}/{_CURRENT_END}"

_METHOD = "llm"
_METHOD_VER = "llm-test-v1"


def _dt(iso: str) -> datetime:
    """Parse an ISO string into a UTC-aware datetime."""
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


def _seed_l1(
    session,
    value,
    labeled_at: datetime,
    *,
    sample_id: str = "sample-seed",
    method: str = _METHOD,
    method_ver: str = _METHOD_VER,
) -> LabelL1Candidate:
    """Directly insert an L1 row with a controlled labeled_at timestamp."""
    row = LabelL1Candidate(
        label_id=new_id("l1"),
        sample_id=sample_id,
        feature_id="feat-001",
        feature_version="fv-1",
        value=value,
        task_type="classification",
        method=method,
        method_ver=method_ver,
        confidence=0.9,
        rationale=None,
        inputs_hash="sha256:test",
        labeled_at=labeled_at,
        run_id="run-drift-test",
        agreement_group_id=None,
        status=L1Status.CREATED.value,
        extra_metadata=None,
    )
    session.add(row)
    session.flush()
    return row


def _seed_l3(session, sample_id: str, value) -> LabelL3Gold:
    """Directly insert an active L3 gold row."""
    row = LabelL3Gold(
        gold_label_id=new_id("l3"),
        sample_id=sample_id,
        value=value,
        reviewer_id="reviewer-test",
        review_reason="test anchor",
        source_review_id=None,
        source_l1_ids=None,
        created_at=now_utc(),
        label_version="lv-test",
        status="active",
        superseded_by=None,
    )
    session.add(row)
    session.flush()
    return row


def _build_drift_request(metrics: list[str] | None = None) -> DriftRunRequest:
    return DriftRunRequest(
        method=LabelMethod.LLM,
        method_ver=_METHOD_VER,
        baseline_window=BASELINE_WINDOW,
        current_window=CURRENT_WINDOW,
        metrics=metrics or ["psi", "kl_divergence"],
    )


# ---------------------------------------------------------------------------
# DriftService integration tests
# ---------------------------------------------------------------------------

class TestDriftServiceRun:
    def _seed_shifted_data(self, db_session):
        """Seed baseline with mostly high_risk, current with mostly low_risk."""
        baseline_mid = _dt("2026-01-15T00:00:00")
        current_mid = _dt("2026-02-15T00:00:00")

        # baseline: 4 high_risk, 1 low_risk
        for _ in range(4):
            _seed_l1(db_session, "high_risk", baseline_mid)
        _seed_l1(db_session, "low_risk", baseline_mid)

        # current: 1 high_risk, 4 low_risk  (clearly shifted)
        _seed_l1(db_session, "high_risk", current_mid)
        for _ in range(4):
            _seed_l1(db_session, "low_risk", current_mid)

        db_session.commit()

    def test_run_returns_psi_value(self, db_session):
        self._seed_shifted_data(db_session)
        svc = DriftService(db_session)
        resp = svc.run(_build_drift_request(["psi", "kl_divergence"]))
        assert resp.psi is not None

    def test_run_returns_kl_divergence_value(self, db_session):
        self._seed_shifted_data(db_session)
        svc = DriftService(db_session)
        resp = svc.run(_build_drift_request(["psi", "kl_divergence"]))
        assert resp.kl_divergence is not None

    def test_run_returns_valid_status(self, db_session):
        self._seed_shifted_data(db_session)
        svc = DriftService(db_session)
        resp = svc.run(_build_drift_request(["psi", "kl_divergence"]))
        assert resp.status in (DriftStatus.NORMAL, DriftStatus.WARNING, DriftStatus.CRITICAL)

    def test_run_returns_metric_id(self, db_session):
        self._seed_shifted_data(db_session)
        svc = DriftService(db_session)
        resp = svc.run(_build_drift_request(["psi", "kl_divergence"]))
        assert resp.metric_id is not None and resp.metric_id != ""

    def test_run_with_no_data_returns_none_metrics(self, db_session):
        """When there is no data in either window, psi and kl should be None."""
        svc = DriftService(db_session)
        resp = svc.run(_build_drift_request(["psi", "kl_divergence"]))
        assert resp.psi is None
        assert resp.kl_divergence is None

    def test_run_status_is_normal_for_identical_distributions(self, db_session):
        """Identical distributions across windows should yield NORMAL status."""
        baseline_mid = _dt("2026-01-15T00:00:00")
        current_mid = _dt("2026-02-15T00:00:00")
        for _ in range(3):
            _seed_l1(db_session, "high_risk", baseline_mid)
            _seed_l1(db_session, "high_risk", current_mid)
        db_session.commit()

        svc = DriftService(db_session)
        resp = svc.run(_build_drift_request(["psi", "kl_divergence"]))
        assert resp.status == DriftStatus.NORMAL


# ---------------------------------------------------------------------------
# DriftService threshold tests
# ---------------------------------------------------------------------------

class TestDriftServiceThresholds:
    def test_status_is_critical_when_psi_exceeds_critical_threshold(self, db_session):
        """PSI >= 0.25 must produce CRITICAL status (§14.2)."""
        svc = DriftService(db_session)
        # psi_critical_threshold = 0.25; pass a value just above it
        status = svc._status(psi=0.30, kl=None, anchor_drop=None)
        assert status == DriftStatus.CRITICAL

    def test_status_is_warning_when_psi_between_warning_and_critical(self, db_session):
        """0.10 <= PSI < 0.25 must produce WARNING status."""
        svc = DriftService(db_session)
        status = svc._status(psi=0.15, kl=None, anchor_drop=None)
        assert status == DriftStatus.WARNING

    def test_status_is_normal_when_psi_below_warning_threshold(self, db_session):
        """PSI < 0.10 must produce NORMAL status."""
        svc = DriftService(db_session)
        status = svc._status(psi=0.05, kl=None, anchor_drop=None)
        assert status == DriftStatus.NORMAL

    def test_status_is_critical_when_kl_exceeds_critical_threshold(self, db_session):
        """KL >= 0.10 must produce CRITICAL status."""
        svc = DriftService(db_session)
        status = svc._status(psi=None, kl=0.15, anchor_drop=None)
        assert status == DriftStatus.CRITICAL

    def test_status_is_warning_when_kl_between_warning_and_critical(self, db_session):
        """0.05 <= KL < 0.10 must produce WARNING status."""
        svc = DriftService(db_session)
        status = svc._status(psi=None, kl=0.07, anchor_drop=None)
        assert status == DriftStatus.WARNING

    def test_status_is_normal_when_all_metrics_none(self, db_session):
        """No metrics available should default to NORMAL."""
        svc = DriftService(db_session)
        status = svc._status(psi=None, kl=None, anchor_drop=None)
        assert status == DriftStatus.NORMAL

    def test_psi_critical_overrides_kl_warning(self, db_session):
        """CRITICAL from PSI takes precedence even if KL is only at WARNING level."""
        svc = DriftService(db_session)
        status = svc._status(psi=0.30, kl=0.07, anchor_drop=None)
        assert status == DriftStatus.CRITICAL

    def test_data_that_exceeds_psi_critical_threshold_produces_critical_run(self, db_session):
        """Seed data so heavily shifted that PSI > 0.25, confirm CRITICAL response."""
        baseline_mid = _dt("2026-01-15T00:00:00")
        current_mid = _dt("2026-02-15T00:00:00")

        # Extreme shift: 100% class-A in baseline, 100% class-B in current
        for _ in range(10):
            _seed_l1(db_session, "class_a", baseline_mid)
        for _ in range(10):
            _seed_l1(db_session, "class_b", current_mid)
        db_session.commit()

        svc = DriftService(db_session)
        resp = svc.run(_build_drift_request(["psi"]))
        assert resp.psi is not None and resp.psi >= 0.25
        assert resp.status == DriftStatus.CRITICAL


# ---------------------------------------------------------------------------
# Anchor accuracy tests
# ---------------------------------------------------------------------------

class TestAnchorAccuracy:
    def test_anchor_accuracy_is_one_when_l1_matches_l3(self, db_session):
        """L1 in current window matching the L3 value → anchor_accuracy == 1.0."""
        sample_id = "anchor-sample-match"
        current_mid = _dt("2026-02-15T00:00:00")

        _seed_l3(db_session, sample_id, "high_risk")
        _seed_l1(db_session, "high_risk", current_mid, sample_id=sample_id)
        db_session.commit()

        svc = DriftService(db_session)
        resp = svc.run(
            DriftRunRequest(
                method=LabelMethod.LLM,
                method_ver=_METHOD_VER,
                baseline_window=BASELINE_WINDOW,
                current_window=CURRENT_WINDOW,
                metrics=["anchor_accuracy"],
            )
        )
        assert resp.anchor_accuracy == 1.0

    def test_anchor_accuracy_is_zero_when_l1_mismatches_l3(self, db_session):
        """L1 in current window with a different value from L3 → anchor_accuracy == 0.0."""
        sample_id = "anchor-sample-miss"
        current_mid = _dt("2026-02-15T00:00:00")

        _seed_l3(db_session, sample_id, "high_risk")
        _seed_l1(db_session, "low_risk", current_mid, sample_id=sample_id)
        db_session.commit()

        svc = DriftService(db_session)
        resp = svc.run(
            DriftRunRequest(
                method=LabelMethod.LLM,
                method_ver=_METHOD_VER,
                baseline_window=BASELINE_WINDOW,
                current_window=CURRENT_WINDOW,
                metrics=["anchor_accuracy"],
            )
        )
        assert resp.anchor_accuracy == 0.0

    def test_anchor_accuracy_is_none_when_no_l3_anchors_exist(self, db_session):
        """No L3 anchors → anchor_accuracy is None (cannot compute)."""
        current_mid = _dt("2026-02-15T00:00:00")
        _seed_l1(db_session, "high_risk", current_mid)
        db_session.commit()

        svc = DriftService(db_session)
        resp = svc.run(
            DriftRunRequest(
                method=LabelMethod.LLM,
                method_ver=_METHOD_VER,
                baseline_window=BASELINE_WINDOW,
                current_window=CURRENT_WINDOW,
                metrics=["anchor_accuracy"],
            )
        )
        assert resp.anchor_accuracy is None

    def test_anchor_accuracy_mixed_match_and_miss(self, db_session):
        """2 anchors: 1 match, 1 miss → anchor_accuracy == 0.5."""
        current_mid = _dt("2026-02-15T00:00:00")

        _seed_l3(db_session, "anchor-a", "high_risk")
        _seed_l3(db_session, "anchor-b", "high_risk")
        _seed_l1(db_session, "high_risk", current_mid, sample_id="anchor-a")
        _seed_l1(db_session, "low_risk", current_mid, sample_id="anchor-b")
        db_session.commit()

        svc = DriftService(db_session)
        resp = svc.run(
            DriftRunRequest(
                method=LabelMethod.LLM,
                method_ver=_METHOD_VER,
                baseline_window=BASELINE_WINDOW,
                current_window=CURRENT_WINDOW,
                metrics=["anchor_accuracy"],
            )
        )
        assert resp.anchor_accuracy == pytest.approx(0.5)


class TestAnchorAccuracyDrop:
    """B-G4: anchor accuracy drop vs the previous run escalates drift status (§7)."""

    def test_status_escalates_with_anchor_drop(self, db_session):
        svc = DriftService(db_session)
        # drop_threshold = 0.05
        assert svc._status(psi=None, kl=None, anchor_drop=0.0) == DriftStatus.NORMAL
        assert svc._status(psi=None, kl=None, anchor_drop=0.06) == DriftStatus.WARNING
        assert svc._status(psi=None, kl=None, anchor_drop=0.11) == DriftStatus.CRITICAL

    def test_anchor_accuracy_drop_computed_and_critical(self, db_session):
        from app.repositories.drift import DriftRepository

        # A previous run recorded 1.0 anchor accuracy for this labeler.
        DriftRepository(db_session).create(
            method=_METHOD,
            method_ver=_METHOD_VER,
            baseline_window=BASELINE_WINDOW,
            current_window=CURRENT_WINDOW,
            psi=None,
            kl_divergence=None,
            anchor_accuracy=1.0,
            status="NORMAL",
        )
        # Current window: the labeler now MISMATCHES the L3 anchor → accuracy 0.0.
        sid = "drop-sample"
        _seed_l3(db_session, sid, "high_risk")
        _seed_l1(db_session, "low_risk", _dt("2026-02-15T00:00:00"), sample_id=sid)
        db_session.commit()

        resp = DriftService(db_session).run(
            DriftRunRequest(
                method=LabelMethod.LLM,
                method_ver=_METHOD_VER,
                baseline_window=BASELINE_WINDOW,
                current_window=CURRENT_WINDOW,
                metrics=["anchor_accuracy"],
            )
        )
        assert resp.anchor_accuracy == 0.0
        assert resp.anchor_accuracy_drop == pytest.approx(1.0)
        # A full (≥3× threshold) anchor collapse mandates a Gold republish (B-G8).
        assert resp.status == DriftStatus.REPUBLISH_REQUIRED
