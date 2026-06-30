"""Tests for Dataset Builder (FR-9, AC-4, §19.5)."""
from __future__ import annotations

from app.domain.enums import L2Flag, Role
from app.repositories.datasets import DatasetRepository
from app.repositories.labels import LabelRepository
from tests.conftest import l1_payload

FEATURE_VERSION = "fv-2026-01"


# --------------------------------------------------------------------- helpers
def _seed_agreeing_l1(client, auth, sample_id: str, value="high_risk") -> None:
    """Post a single L1 for *sample_id* so majority-vote yields an agreed L2."""
    r = client.post(
        "/api/v1/labels/l1",
        json=l1_payload(sample_id=sample_id, value=value, confidence=0.9),
        headers=auth(Role.DATA_ENGINEER),
    )
    assert r.status_code == 201, r.text


def _run_fusion(client, auth, sample_ids: list[str]) -> dict:
    r = client.post(
        "/api/v1/fusion/run",
        json={"sample_ids": sample_ids, "fusion_policy": "majority_vote"},
        headers=auth(Role.DATA_ENGINEER),
    )
    assert r.status_code in (200, 202), r.text
    return r.json()


def _get_l2_label_version(client, auth, sample_id: str) -> str:
    r = client.get(
        "/api/v1/labels/l2", params={"sample_id": sample_id}, headers=auth(Role.ML_ENGINEER)
    )
    assert r.status_code == 200, r.text
    return r.json()["label_version"]


def _build_dataset(client, auth, *, label_version, label_level="L2", **extra):
    body = {
        "feature_version": FEATURE_VERSION,
        "label_version": label_version,
        "label_level": label_level,
    }
    body.update(extra)
    return client.post("/api/v1/datasets/build", json=body, headers=auth(Role.ML_ENGINEER))


# ----------------------------------------------------------------------- tests
def test_build_dataset_l2_returns_dataset_id_and_manifest_uri(client, auth):
    """Building an L2 dataset over 2 agreeing samples returns a valid dataset_id and manifest_uri."""
    _seed_agreeing_l1(client, auth, "sample-d01")
    _seed_agreeing_l1(client, auth, "sample-d02")
    _run_fusion(client, auth, ["sample-d01", "sample-d02"])
    lv = _get_l2_label_version(client, auth, "sample-d01")

    r = _build_dataset(client, auth, label_version=lv, label_level="L2")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["dataset_id"].startswith("dataset-")
    assert body["sample_count"] == 2
    assert body["manifest_uri"].startswith("lake://gold/dataset_manifest/")


def test_build_dataset_l3_priority_uses_l3_gold_label_id(client, auth, db_session):
    """L3_PRIORITY build uses the L3 gold_label_id for a sample that has an L3."""
    _seed_agreeing_l1(client, auth, "sample-p01")
    _seed_agreeing_l1(client, auth, "sample-p02")
    _run_fusion(client, auth, ["sample-p01", "sample-p02"])
    lv = _get_l2_label_version(client, auth, "sample-p01")

    l3 = LabelRepository(db_session).create_l3(
        sample_id="sample-p01",
        value="high_risk",
        reviewer_id="reviewer-1",
        review_reason="manual override",
        source_review_id="review-001",
        source_l1_ids=None,
        label_version=lv,
    )
    db_session.commit()

    r = _build_dataset(client, auth, label_version=lv, label_level="L3_PRIORITY")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["sample_count"] == 2

    manifest = DatasetRepository(db_session).get(body["dataset_id"])
    assert l3.gold_label_id in manifest.source_label_ids


def test_build_dataset_l3_strict_excludes_samples_without_l3(client, auth, db_session):
    """L3 (strict) mode only includes samples that have an active L3 label."""
    _seed_agreeing_l1(client, auth, "sample-s01")
    _seed_agreeing_l1(client, auth, "sample-s02")
    _run_fusion(client, auth, ["sample-s01", "sample-s02"])
    lv = _get_l2_label_version(client, auth, "sample-s01")

    LabelRepository(db_session).create_l3(
        sample_id="sample-s01",
        value="high_risk",
        reviewer_id="reviewer-1",
        review_reason="review done",
        source_review_id="review-002",
        source_l1_ids=None,
        label_version=lv,
    )
    db_session.commit()

    r = _build_dataset(client, auth, label_version=lv, label_level="L3")
    assert r.status_code == 201, r.text
    # Only sample-s01 has an L3 → strict L3 keeps just that one.
    assert r.json()["sample_count"] == 1


def test_build_dataset_confidence_min_excludes_low_confidence_l2(client, auth, db_session):
    """An L2 whose confidence is below confidence_min is excluded from the dataset."""
    _seed_agreeing_l1(client, auth, "sample-c01")
    _run_fusion(client, auth, ["sample-c01"])
    lv = _get_l2_label_version(client, auth, "sample-c01")  # sample-c01 L2 confidence 0.9

    # A second, low-confidence L2 under the same label_version.
    LabelRepository(db_session).create_l2(
        sample_id="sample-c02",
        value="low_risk",
        confidence=0.2,
        fusion_policy="majority_vote",
        fusion_version="fusion-v1",
        source_l1_ids=[],
        agreement_score=1.0,
        flag=L2Flag.AGREED.value,
        fusion_reason="single_labeler",
        label_version=lv,
    )
    db_session.commit()

    r = _build_dataset(client, auth, label_version=lv, label_level="L2", confidence_min=0.8)
    assert r.status_code == 201, r.text
    # Only sample-c01 (0.9) clears confidence_min=0.8; sample-c02 (0.2) is excluded.
    assert r.json()["sample_count"] == 1


def test_build_dataset_exclude_disagreement_removes_soft_disagreement_l2(client, auth, db_session):
    """exclude_disagreement=True removes L2 rows flagged as soft_disagreement."""
    _seed_agreeing_l1(client, auth, "sample-e01")
    _run_fusion(client, auth, ["sample-e01"])
    lv = _get_l2_label_version(client, auth, "sample-e01")  # agreed L2

    LabelRepository(db_session).create_l2(
        sample_id="sample-e02",
        value="medium_risk",
        confidence=0.75,
        fusion_policy="majority_vote",
        fusion_version="fusion-v1",
        source_l1_ids=[],
        agreement_score=0.6,
        flag=L2Flag.SOFT_DISAGREEMENT.value,
        fusion_reason="majority",
        label_version=lv,
    )
    db_session.commit()

    r = _build_dataset(client, auth, label_version=lv, label_level="L2", exclude_disagreement=True)
    assert r.status_code == 201, r.text
    # sample-e02 (soft_disagreement) is dropped; only the agreed sample-e01 remains.
    assert r.json()["sample_count"] == 1


def test_build_dataset_viewer_role_returns_403(client, auth):
    """A Viewer calling POST /datasets/build receives 403."""
    r = client.post(
        "/api/v1/datasets/build",
        json={"feature_version": FEATURE_VERSION, "label_version": "lv-any", "label_level": "L2"},
        headers=auth(Role.VIEWER),
    )
    assert r.status_code == 403
