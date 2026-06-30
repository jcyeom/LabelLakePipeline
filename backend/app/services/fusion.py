"""Label Fusion Engine (backend_design_prd 절차 4, FR-4, §10.2).

The engine is a pure decision function (strategy pattern over the 6 policies); the
service persists the decision as an L2 row or routes the sample to the review queue.
MVP default policy is ``majority_vote`` (PRD §15.1).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.domain.enums import FusionPolicy, L1Status, L2Flag, LabelMethod
from app.domain.schemas import FusionRunResponse
from app.errors import FusionError
from app.models.orm import LabelL1Candidate
from app.repositories.audit import AuditRepository
from app.repositories.datasets import GoldVersionRepository
from app.repositories.labels import LabelRepository
from app.repositories.reviews import ReviewRepository
from app.repositories.runs import RunRepository
from app.util import new_id

FUSION_VERSION = "fusion-v1"


def _key(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def build_agreement_record(labels) -> list[dict]:
    """논문 표 1 ``agreement`` — 다중 라벨러 raw 결과의 구조화 기록.

    각 라벨러의 원시 출력(method/method_ver/value/confidence)을 보존하여 L2 합의
    라벨에 부착한다. 합의가 어떤 raw 결과들로부터 도출됐는지 추적 가능하게 한다.
    """
    return [
        {
            "label_id": l.label_id,
            "method": l.method,
            "method_ver": l.method_ver,
            "value": l.value,
            "confidence": l.confidence,
        }
        for l in labels
    ]


@dataclass
class FusionDecision:
    human_review_required: bool
    reason: str
    flag: L2Flag
    value: Optional[object] = None
    confidence: Optional[float] = None
    agreement_score: Optional[float] = None
    source_l1_ids: list[str] = field(default_factory=list)


class FusionEngine:
    """Pure fusion decision over a sample's L1 candidate labels."""

    def decide(
        self,
        labels: Sequence[LabelL1Candidate],
        *,
        policy: FusionPolicy = FusionPolicy.CONFIDENCE_GAP,
        confidence_gap_threshold: float = 0.15,
        disagreement_threshold: float = 0.4,
    ) -> FusionDecision:
        labels = [l for l in labels if l is not None]
        if not labels:
            raise FusionError("no L1 labels to fuse")

        ids = [l.label_id for l in labels]

        # Single labeler: trivially agreed (FR-4: 값 일치 → L2).
        if len(labels) == 1:
            l = labels[0]
            return FusionDecision(
                human_review_required=False,
                reason="single_labeler",
                flag=L2Flag.AGREED,
                value=l.value,
                confidence=l.confidence,
                agreement_score=1.0,
                source_l1_ids=ids,
            )

        dispatch = {
            FusionPolicy.CONFIDENCE_GAP: self._algorithm1,
            FusionPolicy.MAJORITY_VOTE: self._majority_vote,
            FusionPolicy.CONFIDENCE_WEIGHTED: self._confidence_weighted,
            FusionPolicy.RULE_PRIORITY: lambda ls, **kw: self._priority(ls, LabelMethod.RULE, ids),
            FusionPolicy.HUMAN_PRIORITY: lambda ls, **kw: self._priority(ls, LabelMethod.HUMAN, ids),
            FusionPolicy.KAPPA_BASED: self._majority_vote,  # MVP: behaves like majority (V1: Cohen's κ)
            FusionPolicy.CUSTOM_POLICY: self._majority_vote,
        }
        strategy = dispatch.get(policy, self._algorithm1)
        return strategy(
            labels,
            ids=ids,
            confidence_gap_threshold=confidence_gap_threshold,
            disagreement_threshold=disagreement_threshold,
        )

    def _algorithm1(self, labels, *, ids, confidence_gap_threshold=0.15, **_) -> FusionDecision:
        """Paper Algorithm 1 — canonical Label Fusion Engine (논문 §3.3, 알고리즘 1).

            if agree(L1):                  L2 ← consensus,        flag = "agreed"
            elif confidence_gap(L1) > θ:   L2 ← argmax_conf(L1),  flag = "soft_disagreement"
            else:                          enqueue(human),        L2 ← NULL
        """
        # agree(L1): 모든 후보 값이 동일.
        if len({_key(l.value) for l in labels}) == 1:
            return FusionDecision(False, "unanimous", L2Flag.AGREED, labels[0].value, self._avg_conf(labels), 1.0, ids)
        # confidence_gap(L1): 신뢰도 상위 두 라벨 간 격차.
        ranked = sorted(labels, key=lambda l: (l.confidence if l.confidence is not None else 0.0), reverse=True)
        top, second = ranked[0], ranked[1]
        gap = (top.confidence or 0.0) - (second.confidence or 0.0)
        if gap > confidence_gap_threshold:
            # argmax_conf(L1): 가장 신뢰도 높은 단일 라벨러의 값을 채택.
            agreement = sum(1 for l in labels if _key(l.value) == _key(top.value)) / len(labels)
            return FusionDecision(False, "confidence_gap", L2Flag.SOFT_DISAGREEMENT, top.value, top.confidence, agreement, ids)
        # 격차가 θ 이하인 불일치 → 사람 검수 라우팅, L2 = NULL.
        return FusionDecision(True, "confidence_gap_below_threshold", L2Flag.HUMAN_REQUIRED, source_l1_ids=ids)

    def _majority_vote(self, labels, *, ids, disagreement_threshold=0.4, **_) -> FusionDecision:
        counts = Counter(_key(l.value) for l in labels)
        total = len(labels)
        top_key, top_count = counts.most_common(1)[0]
        agreement = top_count / total
        tie = sum(1 for _k, c in counts.items() if c == top_count) > 1

        if agreement == 1.0:
            value = next(l.value for l in labels if _key(l.value) == top_key)
            avg_conf = self._avg_conf(labels)
            return FusionDecision(False, "unanimous", L2Flag.AGREED, value, avg_conf, 1.0, ids)
        if tie or agreement < (1 - disagreement_threshold):
            return FusionDecision(True, "majority_disagreement", L2Flag.HUMAN_REQUIRED, source_l1_ids=ids)
        value = next(l.value for l in labels if _key(l.value) == top_key)
        winners = [l for l in labels if _key(l.value) == top_key]
        return FusionDecision(False, "majority", L2Flag.SOFT_DISAGREEMENT, value, self._avg_conf(winners), agreement, ids)

    def _confidence_weighted(self, labels, *, ids, confidence_gap_threshold=0.15, **_) -> FusionDecision:
        weights: dict[str, float] = defaultdict(float)
        rep: dict[str, object] = {}
        for l in labels:
            k = _key(l.value)
            weights[k] += l.confidence if l.confidence is not None else 0.0
            rep[k] = l.value
        ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
        top_key, top_w = ranked[0]
        second_w = ranked[1][1] if len(ranked) > 1 else 0.0
        total_w = sum(weights.values()) or 1.0
        gap = (top_w - second_w) / total_w
        agreement = top_w / total_w
        if gap < confidence_gap_threshold:
            return FusionDecision(True, "confidence_gap_below_threshold", L2Flag.HUMAN_REQUIRED, source_l1_ids=ids)
        flag = L2Flag.AGREED if len(ranked) == 1 else L2Flag.SOFT_DISAGREEMENT
        return FusionDecision(False, "confidence_weighted", flag, rep[top_key], top_w / max(1, len(labels)), agreement, ids)

    def _priority(self, labels, method: LabelMethod, ids) -> FusionDecision:
        preferred = [l for l in labels if l.method == method.value]
        if not preferred:
            return self._majority_vote(labels, ids=ids)
        best = max(preferred, key=lambda l: (l.confidence or 0.0))
        return FusionDecision(False, f"{method.value}_priority", L2Flag.AGREED, best.value, best.confidence, 1.0, ids)

    @staticmethod
    def _avg_conf(labels) -> Optional[float]:
        confs = [l.confidence for l in labels if l.confidence is not None]
        return sum(confs) / len(confs) if confs else None


class FusionService:
    """Orchestrates fusion over many samples (절차 4, §10.2 flow)."""

    def __init__(self, session: Session):
        self.session = session
        self.labels = LabelRepository(session)
        self.reviews = ReviewRepository(session)
        self.runs = RunRepository(session)
        self.audit = AuditRepository(session)
        self.gold = GoldVersionRepository(session)
        self.engine = FusionEngine()

    def run(
        self,
        sample_ids: list[str],
        *,
        policy: FusionPolicy = FusionPolicy.CONFIDENCE_GAP,
        confidence_gap_threshold: float = 0.15,
        disagreement_threshold: float = 0.4,
        low_confidence_threshold: float = 0.5,
        actor: Optional[str] = None,
        run_id: Optional[str] = None,
        record_run: bool = True,
    ) -> FusionRunResponse:
        # record_run=False: nested call (e.g. gold republish) — do not create/finish a
        # separate 'fusion' run; just stamp rows with the caller's run id.
        if record_run:
            run = self.runs.get(run_id) if run_id else None
            if run is None:
                run = self.runs.start("fusion", params={"policy": policy.value, "sample_ids": sample_ids})
            rid = run.run_id
        else:
            rid = run_id or new_id("fusion-run")
        active_gold = self.gold.active()
        label_version = active_gold.label_version if active_gold else f"lv-{rid}"

        # Batch-load every sample's L1 candidates up front (single IN query per chunk)
        # instead of one query per sample — eliminates the fusion N+1 (OPTIMIZATION_PLAN A1).
        l1_by_sample = self.labels.get_l1_by_samples(sample_ids, active_only=False)

        created = review_count = failed = 0
        for sample_id in sample_ids:
            all_l1 = l1_by_sample.get(sample_id, [])
            active = [l for l in all_l1 if l.status == L1Status.CREATED.value]
            failures = [l for l in all_l1 if l.status == L1Status.FAILED.value]
            if not active and not failures:
                failed += 1
                continue

            # Partition by agreement_group_id; ungrouped labels share a sample-level group (B-G2).
            active_groups = self._group(active)
            failed_groups = self._group(failures)
            for gkey in set(active_groups) | set(failed_groups):
                c, r, f = self._fuse_group(
                    sample_id,
                    active_groups.get(gkey, []),
                    failed_groups.get(gkey, []),
                    policy=policy,
                    confidence_gap_threshold=confidence_gap_threshold,
                    disagreement_threshold=disagreement_threshold,
                    low_confidence_threshold=low_confidence_threshold,
                    label_version=label_version,
                    run_id=rid,
                    actor=actor,
                )
                created += c
                review_count += r
                failed += f

        if record_run:
            self.runs.finish(rid, created_count=created, failed_count=failed)
        return FusionRunResponse(
            run_id=rid,
            created_l2_count=created,
            human_review_count=review_count,
            failed_count=failed,
        )

    @staticmethod
    def _group(labels) -> dict:
        """Group labels by agreement_group_id, falling back to a per-sample group."""
        groups: dict[str, list] = defaultdict(list)
        for l in labels:
            groups[l.agreement_group_id or f"sample:{l.sample_id}"].append(l)
        return groups

    @staticmethod
    def _queue_reasons(decision, g_active, g_failed, low_confidence_threshold) -> list[str]:
        """Human Review Queue 등록 조건 (§5): 불일치 / LLM 파싱 실패 / 저신뢰."""
        reasons: list[str] = []
        if decision is not None and decision.human_review_required:
            reasons.append("LABEL_DISAGREEMENT")
        if any(l.method == LabelMethod.LLM.value for l in g_failed):
            reasons.append("LLM_PARSE_FAILURE")
        if any(l.confidence is not None and l.confidence < low_confidence_threshold for l in g_active):
            reasons.append("LOW_CONFIDENCE")
        return reasons

    def _fuse_group(
        self,
        sample_id,
        g_active,
        g_failed,
        *,
        policy,
        confidence_gap_threshold,
        disagreement_threshold,
        low_confidence_threshold,
        label_version,
        run_id,
        actor,
    ):
        """Fuse a single agreement group → (created, review, failed) counts."""
        decision = None
        if g_active:
            try:
                decision = self.engine.decide(
                    g_active,
                    policy=policy,
                    confidence_gap_threshold=confidence_gap_threshold,
                    disagreement_threshold=disagreement_threshold,
                )
            except FusionError:
                decision = None

        reasons = self._queue_reasons(decision, g_active, g_failed, low_confidence_threshold)

        # Nothing to fuse and no queue-worthy reason → count as failed.
        if decision is None and not reasons:
            return (0, 0, 1)

        # Any queue condition (disagreement / parse failure / low confidence) → route to review.
        if reasons:
            l1_ids = [l.label_id for l in g_active] + [l.label_id for l in g_failed]
            reason = "+".join(reasons)
            priority = 7 if "LLM_PARSE_FAILURE" in reasons else 5
            if self.reviews.pending_for_sample(sample_id) is None:
                review = self.reviews.create(
                    sample_id=sample_id, reason=reason, priority=priority, l1_label_ids=l1_ids
                )
                self.audit.record(
                    entity_type="review",
                    entity_id=review.review_id,
                    action="enqueue",
                    actor=actor,
                    run_id=run_id,
                    details={"reason": reason},
                )
            return (0, 1, 0)

        # Consensus reached → create L2. Attach the structured raw multi-labeler
        # record (논문 표 1 `agreement`) of the L1 candidates that were fused.
        l2 = self.labels.create_l2(
            sample_id=sample_id,
            value=decision.value,
            confidence=decision.confidence,
            fusion_policy=policy.value,
            fusion_version=FUSION_VERSION,
            source_l1_ids=decision.source_l1_ids,
            agreement_score=decision.agreement_score,
            agreement=build_agreement_record(g_active),
            flag=decision.flag.value,
            fusion_reason=decision.reason,
            label_version=label_version,
            run_id=run_id,
        )
        self.audit.record(
            entity_type="l2",
            entity_id=l2.consensus_label_id,
            action="create",
            actor=actor,
            run_id=run_id,
            details={"flag": decision.flag.value, "policy": policy.value},
        )
        return (1, 0, 0)
