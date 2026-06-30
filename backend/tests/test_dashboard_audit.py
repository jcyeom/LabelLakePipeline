"""Tests for §11.1 dashboard metrics and FR-10 audit/lineage endpoints."""
from __future__ import annotations

from app.domain.enums import Role
from tests.conftest import l1_payload, submit_and_wait


# ---------------------------------------------------------------------------
# Dashboard metrics — GET /api/v1/dashboard/metrics
# ---------------------------------------------------------------------------

def test_dashboard_metrics_empty_db_returns_200_with_zeros(client, auth):
    """Empty DB → 200, all counts zero, agreement rate 0.0."""
    r = client.get("/api/v1/dashboard/metrics", headers=auth(Role.VIEWER))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_l1"] == 0
    assert body["l2_agreement_rate"] == 0.0
    assert body["human_review_queue_size"] == 0
    assert body["l3_count"] == 0


def test_dashboard_metrics_shape_has_all_required_keys(client, auth):
    """Response must contain every DashboardMetrics key with correct types."""
    r = client.get("/api/v1/dashboard/metrics", headers=auth(Role.VIEWER))
    assert r.status_code == 200, r.text
    body = r.json()
    required_keys = {
        "total_l1",
        "l1_by_method",
        "failure_rate_by_method",
        "avg_confidence_by_method",
        "l2_agreement_rate",
        "human_review_queue_size",
        "l3_count",
        "drift_status_by_method",
        "gold_label_version",
    }
    assert required_keys.issubset(body.keys()), f"missing keys: {required_keys - body.keys()}"
    assert isinstance(body["total_l1"], int)
    assert isinstance(body["l1_by_method"], dict)
    assert isinstance(body["failure_rate_by_method"], dict)
    assert isinstance(body["avg_confidence_by_method"], dict)
    assert isinstance(body["l2_agreement_rate"], float)
    assert isinstance(body["human_review_queue_size"], int)
    assert isinstance(body["l3_count"], int)
    assert isinstance(body["drift_status_by_method"], dict)
    # gold_label_version may be null or a string
    assert body["gold_label_version"] is None or isinstance(body["gold_label_version"], str)


def test_dashboard_metrics_reflects_seeded_l1_count(client, auth):
    """After seeding rule + llm L1 labels, total_l1 and l1_by_method are populated."""
    h_de = auth(Role.DATA_ENGINEER)
    client.post("/api/v1/labels/l1", json=l1_payload(method="rule", method_ver="rule-v1", value="medium_risk", confidence=0.7), headers=h_de)
    client.post("/api/v1/labels/l1", json=l1_payload(method="llm",  method_ver="llm-v2",  value="high_risk",   confidence=0.82), headers=h_de)

    r = client.get("/api/v1/dashboard/metrics", headers=auth(Role.VIEWER))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_l1"] == 2
    assert "rule" in body["l1_by_method"]
    assert "llm" in body["l1_by_method"]
    assert body["l1_by_method"]["rule"] == 1
    assert body["l1_by_method"]["llm"] == 1


def test_dashboard_metrics_agreed_l2_raises_agreement_rate(client, auth):
    """After fusion that produces an AGREED L2, l2_agreement_rate > 0."""
    h_de = auth(Role.DATA_ENGINEER)
    # Seed two labels for the same sample with the same value so fusion agrees
    client.post("/api/v1/labels/l1", json=l1_payload(method="rule", method_ver="rule-v1", value="high_risk", confidence=0.9), headers=h_de)
    client.post("/api/v1/labels/l1", json=l1_payload(method="llm",  method_ver="llm-v2",  value="high_risk", confidence=0.85), headers=h_de)

    # Run fusion (async → poll the run for its result)
    fusion_run = submit_and_wait(
        client, h_de, "/api/v1/fusion/run",
        {"sample_ids": ["sample-001"], "fusion_policy": "majority_vote"},
    )
    assert fusion_run["result"]["created_l2_count"] >= 1, "expected at least 1 agreed L2"

    metrics_r = client.get("/api/v1/dashboard/metrics", headers=auth(Role.VIEWER))
    assert metrics_r.status_code == 200, metrics_r.text
    body = metrics_r.json()
    assert body["l2_agreement_rate"] > 0.0, "agreement rate should be > 0 after an agreed fusion"
    # gold_label_version may be null or a string (both are valid)
    assert body["gold_label_version"] is None or isinstance(body["gold_label_version"], str)


def test_dashboard_metrics_disagreement_increments_review_queue(client, auth):
    """Disagreeing labels that trigger a review → human_review_queue_size >= 1."""
    h_de = auth(Role.DATA_ENGINEER)
    # Use very different values so fusion produces HUMAN_REQUIRED
    client.post("/api/v1/labels/l1", json=l1_payload(method="rule", method_ver="rule-v1", value="low_risk",  confidence=0.9), headers=h_de)
    client.post("/api/v1/labels/l1", json=l1_payload(method="llm",  method_ver="llm-v2",  value="high_risk", confidence=0.9), headers=h_de)

    submit_and_wait(
        client, h_de, "/api/v1/fusion/run",
        {
            "sample_ids": ["sample-001"],
            "fusion_policy": "majority_vote",
            "confidence_gap_threshold": 0.01,
            "disagreement_threshold": 0.01,
        },
    )

    metrics_r = client.get("/api/v1/dashboard/metrics", headers=auth(Role.VIEWER))
    assert metrics_r.status_code == 200, metrics_r.text
    body = metrics_r.json()
    assert body["human_review_queue_size"] >= 1, (
        "expected at least one pending review after strong disagreement"
    )


# ---------------------------------------------------------------------------
# Audit / lineage — GET /api/v1/audit/lineage
# ---------------------------------------------------------------------------

def test_audit_lineage_l1_create_records_audit_row(client, auth):
    """Creating an L1 label via API records an audit entry; lineage returns it."""
    h_de = auth(Role.DATA_ENGINEER)
    create_r = client.post("/api/v1/labels/l1", json=l1_payload(), headers=h_de)
    assert create_r.status_code == 201, create_r.text
    label_id = create_r.json()["label_id"]

    lineage_r = client.get(
        "/api/v1/audit/lineage",
        params={"entity_id": label_id},
        headers=h_de,
    )
    assert lineage_r.status_code == 200, lineage_r.text
    body = lineage_r.json()
    assert body["entity_id"] == label_id
    records = body["records"]
    assert len(records) >= 1, "expected at least one audit record after L1 creation"


def test_audit_lineage_record_has_required_fields(client, auth):
    """Each audit record must have audit_id, entity_type, entity_id, action, created_at."""
    h_de = auth(Role.DATA_ENGINEER)
    create_r = client.post("/api/v1/labels/l1", json=l1_payload(), headers=h_de)
    label_id = create_r.json()["label_id"]

    lineage_r = client.get(
        "/api/v1/audit/lineage",
        params={"entity_id": label_id},
        headers=h_de,
    )
    records = lineage_r.json()["records"]
    for record in records:
        assert "audit_id" in record, f"missing audit_id in {record}"
        assert "entity_type" in record, f"missing entity_type in {record}"
        assert "entity_id" in record, f"missing entity_id in {record}"
        assert "action" in record, f"missing action in {record}"
        assert "created_at" in record, f"missing created_at in {record}"


def test_audit_lineage_unknown_id_returns_empty_records(client, auth):
    """Querying lineage for an unknown entity_id returns records == []."""
    h_de = auth(Role.DATA_ENGINEER)
    r = client.get(
        "/api/v1/audit/lineage",
        params={"entity_id": "nonexistent-id-xyz"},
        headers=h_de,
    )
    assert r.status_code == 200, r.text
    assert r.json()["records"] == []


def test_audit_lineage_viewer_gets_403(client, auth):
    """Viewer role is below DataEngineer; lineage endpoint must return 403."""
    r = client.get(
        "/api/v1/audit/lineage",
        params={"entity_id": "any-id"},
        headers=auth(Role.VIEWER),
    )
    assert r.status_code == 403, r.text


def test_audit_lineage_reviewer_gets_403(client, auth):
    """Reviewer role is below DataEngineer; lineage endpoint must return 403."""
    r = client.get(
        "/api/v1/audit/lineage",
        params={"entity_id": "any-id"},
        headers=auth(Role.REVIEWER),
    )
    assert r.status_code == 403, r.text


def test_audit_lineage_ml_engineer_gets_403(client, auth):
    """MLEngineer role is below DataEngineer; lineage endpoint must return 403."""
    r = client.get(
        "/api/v1/audit/lineage",
        params={"entity_id": "any-id"},
        headers=auth(Role.ML_ENGINEER),
    )
    assert r.status_code == 403, r.text


def test_audit_lineage_data_engineer_succeeds(client, auth):
    """DataEngineer meets the minimum role; lineage should not return 403."""
    r = client.get(
        "/api/v1/audit/lineage",
        params={"entity_id": "any-id"},
        headers=auth(Role.DATA_ENGINEER),
    )
    assert r.status_code != 403, r.text
