"""Tests for the Human Review queue & completion (FR-5/FR-6, AC-3, §10.3)."""
from __future__ import annotations

from app.domain.enums import Role


def _create_review(client, auth, *, sample_id="sample-001", reason="LABEL_DISAGREEMENT", priority=0):
    return client.post(
        "/api/v1/reviews",
        json={"sample_id": sample_id, "reason": reason, "priority": priority, "l1_label_ids": ["l1-x"]},
        headers=auth(Role.DATA_ENGINEER),
    )


def test_create_review_returns_pending(client, auth):
    r = _create_review(client, auth)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "PENDING"
    assert body["review_id"].startswith("review-")


def test_list_reviews_orders_by_priority(client, auth):
    _create_review(client, auth, sample_id="sample-low", priority=1)
    _create_review(client, auth, sample_id="sample-high", priority=9)

    r = client.get("/api/v1/reviews", params={"status": "PENDING"}, headers=auth(Role.REVIEWER))
    assert r.status_code == 200, r.text
    reviews = r.json()["reviews"]
    assert len(reviews) == 2
    assert reviews[0]["sample_id"] == "sample-high"  # higher priority first
    assert reviews[1]["sample_id"] == "sample-low"


def test_complete_review_creates_l3_and_regenerates_l2(client, auth):
    created = _create_review(client, auth, sample_id="sample-rev")
    review_id = created.json()["review_id"]

    r = client.post(
        f"/api/v1/reviews/{review_id}/complete",
        json={"value": "high_risk", "reviewer_id": "rev-7", "review_reason": "manual adjudication"},
        headers=auth(Role.REVIEWER),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "COMPLETED"
    assert body["gold_label_id"].startswith("l3-")

    # AC-3: L3 carries reviewer_id and review_reason.
    l3 = client.get("/api/v1/labels/l3", params={"sample_id": "sample-rev"}, headers=auth(Role.ML_ENGINEER))
    assert l3.status_code == 200, l3.text
    l3_body = l3.json()
    assert l3_body["reviewer_id"] == "rev-7"
    assert l3_body["review_reason"] == "manual adjudication"

    # L2 regenerated from the human decision with human_priority policy.
    l2 = client.get("/api/v1/labels/l2", params={"sample_id": "sample-rev"}, headers=auth(Role.ML_ENGINEER))
    assert l2.status_code == 200, l2.text
    assert l2.json()["fusion_policy"] == "human_priority"


def test_complete_review_twice_conflicts(client, auth):
    review_id = _create_review(client, auth, sample_id="sample-twice").json()["review_id"]
    payload = {"value": "high_risk", "reviewer_id": "rev-7", "review_reason": "first"}

    first = client.post(f"/api/v1/reviews/{review_id}/complete", json=payload, headers=auth(Role.REVIEWER))
    assert first.status_code == 200, first.text

    second = client.post(f"/api/v1/reviews/{review_id}/complete", json=payload, headers=auth(Role.REVIEWER))
    assert second.status_code == 409


def test_complete_review_rbac_ml_engineer_forbidden(client, auth):
    review_id = _create_review(client, auth, sample_id="sample-rbac").json()["review_id"]

    r = client.post(
        f"/api/v1/reviews/{review_id}/complete",
        json={"value": "high_risk", "reviewer_id": "rev-7"},
        headers=auth(Role.ML_ENGINEER),
    )
    assert r.status_code == 403


def test_complete_review_admin_allowed(client, auth):
    review_id = _create_review(client, auth, sample_id="sample-admin").json()["review_id"]

    r = client.post(
        f"/api/v1/reviews/{review_id}/complete",
        json={"value": "high_risk", "reviewer_id": "admin-1"},
        headers=auth(Role.ADMIN),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "COMPLETED"


def test_complete_nonexistent_review_returns_404(client, auth):
    r = client.post(
        "/api/v1/reviews/review-does-not-exist/complete",
        json={"value": "high_risk", "reviewer_id": "rev-7"},
        headers=auth(Role.REVIEWER),
    )
    assert r.status_code == 404
