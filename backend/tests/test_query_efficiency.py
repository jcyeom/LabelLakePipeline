"""쿼리 효율 회귀 테스트 (OPTIMIZATION_PLAN E1).

배치 조회가 단일 쿼리로 수행되고, 핵심 경로에서 per-row N+1 메서드가 더 이상
호출되지 않음을 고정한다. N+1 재발 시 이 테스트가 실패한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.enums import FusionPolicy, L1Status, LabelMethod
from app.domain.schemas import DriftRunRequest, LabelObjectIn
from app.models.orm import LabelL1Candidate, LabelL3Gold
from app.repositories.labels import LabelRepository
from app.services.drift import DriftService
from app.services.fusion import FusionService
from app.util import new_id, now_utc
from tests.conftest import l1_payload


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


# --------------------------------------------------- 배치 리포지토리 = 단일 쿼리
def test_get_l1_by_samples_is_single_query(db_session, query_counter):
    repo = LabelRepository(db_session)
    for i in range(20):
        repo.create_l1(LabelObjectIn(**l1_payload(sample_id=f"s-{i}")))
    db_session.flush()

    with query_counter() as count:
        grouped = repo.get_l1_by_samples([f"s-{i}" for i in range(20)])
    assert len(grouped) == 20
    assert count.value == 1  # one IN query, not 20


def test_get_active_l3_by_samples_is_single_query(db_session, query_counter):
    repo = LabelRepository(db_session)
    for i in range(15):
        repo.create_l3(
            sample_id=f"g-{i}", value="high_risk", reviewer_id="r", review_reason=None,
            source_review_id=None, source_l1_ids=None, label_version="lv-1",
        )
    db_session.flush()

    with query_counter() as count:
        m = repo.get_active_l3_by_samples([f"g-{i}" for i in range(15)])
    assert len(m) == 15
    assert count.value == 1


def test_dashboard_l1_counts_single_query(db_session, query_counter):
    repo = LabelRepository(db_session)
    for m in ("llm", "rule", "human"):
        repo.create_l1(LabelObjectIn(**l1_payload(sample_id=f"s-{m}", method=m, method_ver=f"{m}-v1")))
    db_session.flush()

    with query_counter() as count:
        counts = repo.l1_total_and_failed_by_method()
    assert set(counts) == {"llm", "rule", "human"}
    assert count.value == 1


# --------------------------------------------------- N+1 제거 (per-row 메서드 미사용)
def _seed_fusion_samples(repo, n: int) -> list[str]:
    sample_ids = [f"fz-{i}" for i in range(n)]
    for sid in sample_ids:
        repo.create_l1(LabelObjectIn(**l1_payload(sample_id=sid, method="llm", method_ver="llm-v1", value="high_risk", confidence=0.8)))
        repo.create_l1(LabelObjectIn(**l1_payload(sample_id=sid, method="rule", method_ver="rule-v1", value="high_risk", confidence=0.7)))
    return sample_ids


def test_fusion_does_not_call_per_sample_l1_query(db_session, monkeypatch):
    """FusionService.run은 샘플별 get_l1_by_sample(N+1)을 더 이상 호출하지 않는다."""
    repo = LabelRepository(db_session)
    sample_ids = _seed_fusion_samples(repo, 6)
    db_session.flush()

    def _forbidden(self, *a, **k):
        raise AssertionError("get_l1_by_sample (per-sample N+1) must not be used by fusion")

    monkeypatch.setattr(LabelRepository, "get_l1_by_sample", _forbidden)

    resp = FusionService(db_session).run(sample_ids, policy=FusionPolicy.CONFIDENCE_GAP)
    assert resp.created_l2_count == 6  # all unanimous → L2 via the batch path


def test_fusion_read_queries_do_not_scale_with_sample_count(db_session, query_counter):
    """융합의 SELECT 수는 샘플 수 N(2→6)에 따라 증가하지 않는다(읽기 N+1 부재)."""
    repo = LabelRepository(db_session)

    small = _seed_fusion_samples(repo, 2)
    db_session.flush()
    with query_counter() as c_small:
        FusionService(db_session).run(small, policy=FusionPolicy.CONFIDENCE_GAP)

    big = [f"fz2-{i}" for i in range(6)]
    for sid in big:
        repo.create_l1(LabelObjectIn(**l1_payload(sample_id=sid, method="llm", method_ver="llm-v1", value="high_risk", confidence=0.8)))
        repo.create_l1(LabelObjectIn(**l1_payload(sample_id=sid, method="rule", method_ver="rule-v1", value="high_risk", confidence=0.7)))
    db_session.flush()
    with query_counter() as c_big:
        FusionService(db_session).run(big, policy=FusionPolicy.CONFIDENCE_GAP)

    # The active-gold read + batched L1 read are constant; a per-sample N+1 would make
    # SELECTs grow by ≥4 from 2→6 samples. Allow tiny slack but reject linear growth.
    assert c_big.selects - c_small.selects <= 1


def test_anchor_accuracy_query_count_is_bounded(db_session, query_counter):
    """_anchor_accuracy는 앵커 수에 비례하지 않는 상수 쿼리만 수행한다."""
    cur = _dt("2026-02-15T00:00:00")
    for i in range(15):
        sid = f"anchor-{i}"
        db_session.add(LabelL3Gold(
            gold_label_id=new_id("l3"), sample_id=sid, value="high_risk", reviewer_id="r",
            review_reason=None, source_review_id=None, source_l1_ids=None, created_at=now_utc(),
            label_version="lv", status="active", superseded_by=None,
        ))
        db_session.add(LabelL1Candidate(
            label_id=new_id("l1"), sample_id=sid, feature_id="f", feature_version="fv",
            value="high_risk", task_type="classification", method="llm", method_ver="llm-v1",
            confidence=0.9, rationale=None, inputs_hash="sha256:x", labeled_at=cur,
            run_id="r", agreement_group_id=None, status=L1Status.CREATED.value, extra_metadata=None,
        ))
    db_session.flush()

    svc = DriftService(db_session)
    with query_counter() as count:
        acc = svc._anchor_accuracy("llm", "2026-02-01T00:00:00/2026-03-01T00:00:00")
    assert acc == 1.0
    assert count.value <= 2  # 1 anchor-load + 1 prediction batch (not 15+)


def test_drift_route_anchors_pending_check_is_batched(db_session, query_counter):
    """_route_anchors_to_review의 pending 체크가 앵커당 1쿼리가 아니다."""
    for i in range(10):
        db_session.add(LabelL3Gold(
            gold_label_id=new_id("l3"), sample_id=f"dr-{i}", value="v", reviewer_id="r",
            review_reason=None, source_review_id=None, source_l1_ids=None, created_at=now_utc(),
            label_version="lv", status="active", superseded_by=None,
        ))
    db_session.flush()

    svc = DriftService(db_session)
    with query_counter() as count:
        enqueued = svc._route_anchors_to_review(run_id="run-x", actor=None)
    assert enqueued == 10
    # Reads are constant (1 anchor-id load + 1 batched pending check); writes are the
    # inherent 2 inserts per created review (queue row + audit row). The invariant we
    # lock: read queries do NOT scale with anchor count.
    #   batched:     2 + 2*N  = 22
    #   per-anchor:  2 + N(pending) + 2*N = 32  → would fail
    assert count.value <= 3 + 2 * enqueued
