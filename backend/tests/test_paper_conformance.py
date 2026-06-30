"""논문(kcc2026_제출본_FINAL) 정합성 테스트.

논문이 원본 설계 기준이다. 코드가 다음 논문 명세와 일치함을 고정한다.
- 표 1 Label Object `agreement` (다중 라벨러 raw 결과의 구조화 기록)
- 알고리즘 1 Label Fusion Engine (정본 기본값: agree → confidence_gap>θ → human)
- §3.3 폐루프(closed loop): L3 검수 결과의 라벨러별 회귀 검증 재투입
- §3.4 동일 feature 분위수 구간 조건의 L1 분포 드리프트
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.enums import L1Status, L2Flag, LabelMethod, Role
from app.domain.schemas import (
    DriftRunRequest,
    LabelObjectIn,
    ReviewCompleteRequest,
    ReviewCreateRequest,
)
from app.models.orm import LabelL1Candidate
from app.repositories.audit import AuditRepository
from app.repositories.labels import LabelRepository
from app.services.drift import DriftService
from app.services.fusion import FusionEngine
from app.services.review import ReviewService
from app.util import new_id
from tests.conftest import l1_payload


def _l1(repo: LabelRepository, **ov) -> LabelL1Candidate:
    return repo.create_l1(LabelObjectIn(**l1_payload(**ov)))


# --------------------------------------------------- 알고리즘 1 (정본 기본값)
def test_default_policy_is_algorithm1_agree(db_session):
    """정책 미지정 시 알고리즘 1 — 값 일치는 'agreed'."""
    repo = LabelRepository(db_session)
    a = _l1(repo, method="llm", method_ver="llm-v1", value="high_risk", confidence=0.8)
    b = _l1(repo, method="rule", method_ver="rule-v1", value="high_risk", confidence=0.6)

    d = FusionEngine().decide([a, b])  # no policy → CONFIDENCE_GAP

    assert d.flag == L2Flag.AGREED
    assert d.value == "high_risk"
    assert d.agreement_score == 1.0


def test_algorithm1_confidence_gap_picks_argmax_conf(db_session):
    """confidence_gap(L1) > θ → argmax_conf 값 채택, flag='soft_disagreement'."""
    repo = LabelRepository(db_session)
    a = _l1(repo, method="llm", method_ver="llm-v1", value="high_risk", confidence=0.9)
    b = _l1(repo, method="rule", method_ver="rule-v1", value="low_risk", confidence=0.5)

    d = FusionEngine().decide([a, b])  # gap 0.4 > θ 0.15

    assert d.human_review_required is False
    assert d.flag == L2Flag.SOFT_DISAGREEMENT
    assert d.value == "high_risk"  # 최고 신뢰도 단일 라벨


def test_algorithm1_small_gap_routes_human_with_null_l2(db_session):
    """confidence_gap ≤ θ 불일치 → human queue, L2 = NULL."""
    repo = LabelRepository(db_session)
    a = _l1(repo, method="llm", method_ver="llm-v1", value="high_risk", confidence=0.55)
    b = _l1(repo, method="rule", method_ver="rule-v1", value="low_risk", confidence=0.5)

    d = FusionEngine().decide([a, b])  # gap 0.05 ≤ θ

    assert d.human_review_required is True
    assert d.flag == L2Flag.HUMAN_REQUIRED
    assert d.value is None  # L2(x) ← NULL


# ----------------------------------------- 표 1 `agreement` 구조화 기록 (L2)
def test_l2_carries_agreement_record(client, auth):
    """합의 L2는 융합에 사용된 라벨러별 raw 결과를 구조화 기록한다 (논문 표 1)."""
    h = auth(Role.DATA_ENGINEER)
    for m, mv, c in [("llm", "llm-v1", 0.8), ("rule", "rule-v1", 0.7)]:
        client.post(
            "/api/v1/labels/l1",
            json=l1_payload(sample_id="s-agg", method=m, method_ver=mv, value="high_risk", confidence=c),
            headers=h,
        )
    # 기본 정책(알고리즘 1)으로 융합 — 값 일치 → L2 생성.
    client.post("/api/v1/fusion/run", json={"sample_ids": ["s-agg"]}, headers=h)

    l2 = client.get("/api/v1/labels/l2", params={"sample_id": "s-agg"}, headers=auth(Role.ML_ENGINEER)).json()
    assert l2["agreement"] is not None
    assert len(l2["agreement"]) == 2
    assert {r["method"] for r in l2["agreement"]} == {"llm", "rule"}
    assert all("value" in r and "confidence" in r for r in l2["agreement"])


# ------------------------------------------- §3.3 폐루프 (closed loop) 재투입
def test_closed_loop_feedback_recorded_on_l3(db_session):
    """L3 검수 완료 시 라벨러별 정답 일치 여부를 회귀 검증 신호로 audit에 재투입한다."""
    repo = LabelRepository(db_session)
    a = _l1(repo, sample_id="s-loop", method="llm", method_ver="llm-v1", value="low_risk", confidence=0.8)
    b = _l1(repo, sample_id="s-loop", method="rule", method_ver="rule-v1", value="high_risk", confidence=0.7)

    svc = ReviewService(db_session)
    created = svc.register(
        ReviewCreateRequest(sample_id="s-loop", reason="LABEL_DISAGREEMENT", l1_label_ids=[a.label_id, b.label_id])
    )
    svc.complete(created.review_id, ReviewCompleteRequest(value="high_risk", reviewer_id="rev-1"))

    l3 = repo.get_l3_by_sample("s-loop")
    audits = AuditRepository(db_session).by_entity("l3", l3.gold_label_id)
    feedback_entries = [x for x in audits if x.action == "closed_loop_feedback"]
    assert len(feedback_entries) == 1

    by_ver = {f["method_ver"]: f["agreed"] for f in feedback_entries[0].details["feedback"]}
    assert by_ver["rule-v1"] is True   # rule이 사람 정답(high_risk)과 일치
    assert by_ver["llm-v1"] is False   # llm은 불일치 → 회귀 검증 대상


# ----------------------------------- §3.4 feature 분위수 구간 조건 드리프트
def test_drift_conditions_on_feature_bin(db_session):
    """값 분포가 동일해도 feature 분위수 구간이 이동하면 드리프트로 감지된다."""
    def seed(value, fbin, when):
        db_session.add(
            LabelL1Candidate(
                label_id=new_id("l1"), sample_id="x", feature_id="f", feature_version="fv",
                value=value, task_type="classification", method="llm", method_ver="llm-bin",
                confidence=0.9, rationale=None, inputs_hash="sha256:x", labeled_at=when,
                run_id="r", agreement_group_id=None, status=L1Status.CREATED.value,
                extra_metadata={"feature_bin": fbin},
            )
        )

    base = datetime(2026, 1, 15, tzinfo=timezone.utc)
    cur = datetime(2026, 2, 15, tzinfo=timezone.utc)
    for _ in range(5):
        seed("high", "q1", base)   # baseline: 모두 q1 구간
    for _ in range(5):
        seed("high", "q4", cur)    # current: 값은 동일('high')하나 q4 구간으로 이동
    db_session.commit()

    resp = DriftService(db_session).run(
        DriftRunRequest(
            method=LabelMethod.LLM,
            method_ver="llm-bin",
            baseline_window="2026-01-01T00:00:00/2026-02-01T00:00:00",
            current_window="2026-02-01T00:00:00/2026-03-01T00:00:00",
            metrics=["psi"],
        )
    )
    # 값-only 분포라면 PSI≈0이지만, 구간 조건으로 q1|high → q4|high 이동이 감지된다.
    assert resp.psi is not None and resp.psi > 0
