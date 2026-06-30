"""Dataset manifest + gold version repositories (절차 7/9, FR-8/FR-9)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import DatasetManifest, GoldVersion
from app.util import new_id, now_utc


class DatasetRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_manifest(
        self,
        *,
        feature_version,
        label_version,
        label_level,
        sample_count,
        build_query,
        source_label_ids,
        created_by=None,
    ) -> DatasetManifest:
        dataset_id = new_id("dataset")
        row = DatasetManifest(
            dataset_id=dataset_id,
            feature_version=feature_version,
            label_version=label_version,
            label_level=label_level,
            sample_count=sample_count,
            build_query=build_query,
            source_label_ids=source_label_ids,
            manifest_uri=f"lake://gold/dataset_manifest/{dataset_id}",
            created_at=now_utc(),
            created_by=created_by,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get(self, dataset_id: str) -> Optional[DatasetManifest]:
        return self.session.get(DatasetManifest, dataset_id)

    def count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(DatasetManifest)) or 0


class GoldVersionRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, *, label_version, fusion_policy, trigger, scope, run_id, activate=True) -> GoldVersion:
        if activate:
            for v in self.session.scalars(select(GoldVersion).where(GoldVersion.is_active == 1)):
                v.is_active = 0
        row = GoldVersion(
            version_id=new_id("goldver"),
            label_version=label_version,
            fusion_policy=fusion_policy,
            trigger=trigger,
            scope=scope,
            run_id=run_id,
            is_active=1 if activate else 0,
            created_at=now_utc(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def active(self) -> Optional[GoldVersion]:
        return self.session.scalars(select(GoldVersion).where(GoldVersion.is_active == 1)).first()

    def get(self, version_id: str) -> Optional[GoldVersion]:
        return self.session.get(GoldVersion, version_id)

    def rollback_to(self, version_id: str) -> Optional[GoldVersion]:
        target = self.get(version_id)
        if target is None:
            return None
        for v in self.session.scalars(select(GoldVersion).where(GoldVersion.is_active == 1)):
            v.is_active = 0
        target.is_active = 1
        self.session.flush()
        return target
