"""Label Drift Monitor (backend_design_prd 절차 8, FR-7, §10.4, §14.2).

Implements Distribution Drift (PSI + KL over L1 value distributions across two time
windows) and Anchor Drift (accuracy of a labeler's current-window labels against the
L3 anchor set). Status is derived from the §14.2 thresholds. PRD §15.2 lists Drift
automation as V1; this provides the V1 computation usable on demand.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.enums import DriftStatus
from app.domain.schemas import DriftRunRequest, DriftRunResponse
from app.repositories.audit import AuditRepository
from app.repositories.drift import DriftRepository
from app.repositories.reviews import ReviewRepository
from app.repositories.runs import RunRepository

_EPS = 1e-6


def _normalise(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in counts.items()}


def population_stability_index(baseline: dict[str, float], current: dict[str, float]) -> float:
    """PSI = Σ (cur - base) * ln(cur / base) over the union of categories."""
    psi = 0.0
    for key in set(baseline) | set(current):
        b = max(baseline.get(key, 0.0), _EPS)
        c = max(current.get(key, 0.0), _EPS)
        psi += (c - b) * math.log(c / b)
    return psi


def kl_divergence(baseline: dict[str, float], current: dict[str, float]) -> float:
    """KL(current || baseline) = Σ cur * ln(cur / base)."""
    kl = 0.0
    for key in set(baseline) | set(current):
        b = max(baseline.get(key, 0.0), _EPS)
        c = max(current.get(key, 0.0), _EPS)
        kl += c * math.log(c / b)
    return kl


def _parse_window(window: str) -> tuple[datetime, datetime]:
    """Parse 'YYYY-MM-DD/YYYY-MM-DD' into an inclusive-start, exclusive-end pair."""
    start_s, end_s = window.split("/")
    start = datetime.fromisoformat(start_s)
    end = datetime.fromisoformat(end_s)
    return start, end


class DriftService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = DriftRepository(session)
        self.runs = RunRepository(session)
        self.audit = AuditRepository(session)
        self.reviews = ReviewRepository(session)
        self.settings = get_settings()

    def _value_counts(self, method: str, method_ver: str, window: str) -> dict[str, int]:
        """L1 값 분포를 **동일 feature 분위수 구간**(논문 §3.4) 조건에서 집계한다.

        라벨러 L1 레코드의 ``metadata.feature_bin``(feature 분위수 구간 식별자)을 값과
        함께 키로 묶어 ``"<bin>|<value>"`` 분포를 만든다. feature 드리프트가 라벨 드리프트로
        혼입되지 않도록 구간별로 조건화한다. bin이 기록되지 않은 경우 ``_all`` 단일 구간으로
        폴백하여 값-only 분포와 동일하게 동작한다.
        """
        start, end = _parse_window(window)
        counts: dict[str, int] = {}
        for value, metadata in self.repo.l1_value_meta_in_window(method, method_ver, start, end):
            meta = metadata if isinstance(metadata, dict) else {}
            fbin = meta.get("feature_bin", "_all")
            key = f"{fbin}|" + json.dumps(value, sort_keys=True, default=str)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _anchor_accuracy(self, method: str, window: str) -> Optional[float]:
        anchor_values = self.repo.active_anchor_values()
        if not anchor_values:
            return None
        start, end = _parse_window(window)

        # Single column-only IN query over all anchor samples (OPTIMIZATION_PLAN A3/D2).
        # Keep the latest prediction per sample (rows come ordered by labeled_at).
        latest_pred: dict[str, object] = {}
        for sample_id, value in self.repo.l1_values_for_samples_in_window(
            list(anchor_values), method, start, end
        ):
            latest_pred[sample_id] = value  # later rows overwrite → last wins

        matched = total = 0
        for sample_id, pred_value in latest_pred.items():
            total += 1
            if json.dumps(pred_value, sort_keys=True, default=str) == json.dumps(
                anchor_values[sample_id], sort_keys=True, default=str
            ):
                matched += 1
        return (matched / total) if total else None

    def _previous_anchor_accuracy(self, method: str, method_ver: str) -> Optional[float]:
        """Most recent prior anchor_accuracy for the same labeler (B-G4)."""
        for m in self.repo.list(method=method):
            if m.method_ver == method_ver and m.anchor_accuracy is not None:
                return m.anchor_accuracy
        return None

    def _route_anchors_to_review(self, run_id: str, actor: Optional[str]) -> int:
        """Enqueue active L3 anchor samples for re-review (PRD §5: drift designates samples).

        Loads anchor sample ids and their already-open reviews in two batch queries
        instead of one pending check per anchor (OPTIMIZATION_PLAN A4).
        """
        anchor_sample_ids = self.repo.active_anchor_sample_ids()
        already_open = self.reviews.pending_sample_ids(anchor_sample_ids)
        cap = self.settings.drift_max_review_enqueue
        enqueued = 0
        for sample_id in anchor_sample_ids:
            if sample_id in already_open:
                continue
            if enqueued >= cap:
                # Bound write amplification; surface the truncation rather than silently
                # dropping the rest (security A04, no-silent-caps).
                self.audit.record_alert(
                    severity="WARNING",
                    source="drift_monitor",
                    message=f"drift review enqueue capped at {cap}",
                    details={"run_id": run_id, "candidate_anchors": len(anchor_sample_ids)},
                )
                break
            already_open.add(sample_id)  # dedupe if an anchor sample appears twice
            review = self.reviews.create(
                sample_id=sample_id, reason="DRIFT_REVIEW", priority=8, l1_label_ids=[]
            )
            self.audit.record(
                entity_type="review",
                entity_id=review.review_id,
                action="enqueue",
                actor=actor,
                run_id=run_id,
                details={"reason": "DRIFT_REVIEW"},
            )
            enqueued += 1
        return enqueued

    def _status(
        self,
        psi: Optional[float],
        kl: Optional[float],
        anchor_drop: Optional[float] = None,
    ) -> DriftStatus:
        s = self.settings
        # Severe anchor regression (≥ 3× threshold) mandates a Gold republish (FR-7/FR-8).
        if anchor_drop is not None and anchor_drop >= 3 * s.drift_anchor_accuracy_drop_threshold:
            return DriftStatus.REPUBLISH_REQUIRED
        if psi is not None and psi >= s.drift_psi_critical_threshold:
            return DriftStatus.CRITICAL
        if kl is not None and kl >= s.drift_kl_critical_threshold:
            return DriftStatus.CRITICAL
        # Anchor accuracy dropping ≥ 2× threshold is critical (§7 회귀, §13.2 앵커 하락).
        if anchor_drop is not None and anchor_drop >= 2 * s.drift_anchor_accuracy_drop_threshold:
            return DriftStatus.CRITICAL
        if psi is not None and psi >= s.drift_psi_warning_threshold:
            return DriftStatus.WARNING
        if kl is not None and kl >= s.drift_kl_warning_threshold:
            return DriftStatus.WARNING
        if anchor_drop is not None and anchor_drop >= s.drift_anchor_accuracy_drop_threshold:
            return DriftStatus.WARNING
        return DriftStatus.NORMAL

    def run(
        self, req: DriftRunRequest, *, actor: Optional[str] = None, run_id: Optional[str] = None
    ) -> DriftRunResponse:
        run = self.runs.get(run_id) if run_id else None
        if run is None:
            run = self.runs.start("drift", method=req.method.value, method_ver=req.method_ver)
        psi = kl = anchor_acc = None

        if "psi" in req.metrics or "kl_divergence" in req.metrics:
            base = _normalise(self._value_counts(req.method.value, req.method_ver, req.baseline_window))
            cur = _normalise(self._value_counts(req.method.value, req.method_ver, req.current_window))
            if base and cur:
                if "psi" in req.metrics:
                    psi = population_stability_index(base, cur)
                if "kl_divergence" in req.metrics:
                    kl = kl_divergence(base, cur)
        anchor_drop = None
        if "anchor_accuracy" in req.metrics:
            anchor_acc = self._anchor_accuracy(req.method.value, req.current_window)
            prev = self._previous_anchor_accuracy(req.method.value, req.method_ver)
            if anchor_acc is not None and prev is not None:
                anchor_drop = prev - anchor_acc

        status = self._status(psi, kl, anchor_drop)
        metric = self.repo.create(
            method=req.method.value,
            method_ver=req.method_ver,
            baseline_window=req.baseline_window,
            current_window=req.current_window,
            psi=psi,
            kl_divergence=kl,
            anchor_accuracy=anchor_acc,
            status=status.value,
        )
        self.runs.finish(run.run_id, created_count=1)
        self.audit.record(
            entity_type="drift",
            entity_id=metric.metric_id,
            action="measure",
            actor=actor,
            run_id=run.run_id,
            details={"status": status.value, "psi": psi, "kl": kl},
        )

        # Emit an alert event on elevated drift (FR-7 수용기준, §13.2).
        if status in (DriftStatus.WARNING, DriftStatus.CRITICAL, DriftStatus.REPUBLISH_REQUIRED):
            self.audit.record_alert(
                severity=status.value,
                source="drift_monitor",
                message=f"{req.method.value}/{req.method_ver} drift {status.value}",
                details={"metric_id": metric.metric_id, "psi": psi, "kl": kl, "anchor_drop": anchor_drop},
            )
        # Drift designates anchor samples for re-review (§5 Queue 등록 조건).
        if status in (DriftStatus.CRITICAL, DriftStatus.REPUBLISH_REQUIRED):
            self._route_anchors_to_review(run.run_id, actor)

        return DriftRunResponse(
            metric_id=metric.metric_id,
            psi=psi,
            kl_divergence=kl,
            anchor_accuracy=anchor_acc,
            anchor_accuracy_drop=anchor_drop,
            status=status,
        )
