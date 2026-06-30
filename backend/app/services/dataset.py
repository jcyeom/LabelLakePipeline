"""Dataset Builder (backend_design_prd 절차 7, FR-9, §19.5).

MVP joins labels by version in-process (production uses DuckDB/Trino over the lake,
README §3). L3_PRIORITY prefers an active L3 over the L2 for each sample.
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from app.domain.enums import L2Flag, LabelLevel
from app.domain.schemas import DatasetBuildRequest, DatasetBuildResponse
from app.repositories.audit import AuditRepository
from app.repositories.datasets import DatasetRepository
from app.repositories.labels import LabelRepository


class DatasetBuilder:
    def __init__(self, session: Session):
        self.session = session
        self.labels = LabelRepository(session)
        self.datasets = DatasetRepository(session)
        self.audit = AuditRepository(session)

    def build(self, req: DatasetBuildRequest, *, actor: Optional[str] = None) -> DatasetBuildResponse:
        l2_rows = self.labels.list_l2_by_version(req.label_version)
        method_filter = {m.value for m in req.label_method_filter} if req.label_method_filter else None

        # Batch-prefetch to avoid per-L2 N+1 (OPTIMIZATION_PLAN A2):
        #   1) contributing L1 labels for every L2 in a single IN query,
        #   2) active L3 gold labels for all candidate samples in one query (L3 levels only).
        all_src_ids = {lid for l2 in l2_rows for lid in (l2.source_l1_ids or [])}
        l1_by_id = {l.label_id: l for l in self.labels.get_l1_by_ids(list(all_src_ids))}
        l3_by_sample: dict = {}
        if req.label_level in (LabelLevel.L3, LabelLevel.L3_PRIORITY):
            l3_by_sample = self.labels.get_active_l3_by_samples([l2.sample_id for l2 in l2_rows])

        selected_ids: list[str] = []
        sample_ids: set[str] = set()
        rationales: list = []

        for l2 in l2_rows:
            if req.confidence_min is not None and (l2.confidence or 0.0) < req.confidence_min:
                continue
            if req.exclude_disagreement and l2.flag != L2Flag.AGREED.value:
                continue

            # task_type / label_method_filter operate on the contributing L1 labels (FR-9, B-G3).
            source_l1 = [l1_by_id[i] for i in (l2.source_l1_ids or []) if i in l1_by_id]
            if req.task_type is not None and not any(l.task_type == req.task_type for l in source_l1):
                continue
            if method_filter is not None and not any(l.method in method_filter for l in source_l1):
                continue

            chosen_id = l2.consensus_label_id
            # L3 / L3_PRIORITY: prefer the active gold label for the sample.
            if req.label_level in (LabelLevel.L3, LabelLevel.L3_PRIORITY):
                l3 = l3_by_sample.get(l2.sample_id)
                if l3 is not None:
                    chosen_id = l3.gold_label_id
                elif req.label_level == LabelLevel.L3:
                    # Strict L3: skip samples without a gold label.
                    continue

            selected_ids.append(chosen_id)
            sample_ids.add(l2.sample_id)
            if req.include_rationale:
                rationales.extend(l.rationale for l in source_l1 if l.rationale is not None)

        # Store the build parameters as structured JSON for lineage/reproducibility
        # (deterministic via sort_keys) — never as an executable SQL string, so the
        # manifest can't become an injection vector if later read back (security A03).
        build_query = json.dumps(
            {
                "label_version": req.label_version,
                "feature_version": req.feature_version,
                "level": req.label_level.value,
                "confidence_min": req.confidence_min,
                "exclude_disagreement": req.exclude_disagreement,
                "task_type": req.task_type,
                "method_filter": sorted(method_filter) if method_filter else None,
                "include_rationale": req.include_rationale,
            },
            sort_keys=True,
        )
        manifest = self.datasets.create_manifest(
            feature_version=req.feature_version,
            label_version=req.label_version,
            label_level=req.label_level.value,
            sample_count=len(sample_ids),
            build_query=build_query,
            source_label_ids=selected_ids,
            created_by=actor,
        )
        details = {"label_version": req.label_version, "level": req.label_level.value}
        if req.include_rationale:
            details["rationale_count"] = len(rationales)
        self.audit.record(
            entity_type="dataset",
            entity_id=manifest.dataset_id,
            action="build",
            actor=actor,
            details=details,
        )
        return DatasetBuildResponse(
            dataset_id=manifest.dataset_id,
            sample_count=manifest.sample_count,
            manifest_uri=manifest.manifest_uri,
        )
