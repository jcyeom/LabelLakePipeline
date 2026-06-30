"""보안 강화 회귀 테스트.

- PyJWT 디코딩 경로 (python-jose 대체)
- fail-closed 인증 기본값 + 시크릿 필수 검증
- dataset build_query 구조화 JSON (비실행 lineage)
- 드리프트 검수 enqueue 상한 + 절단 alert
"""
from __future__ import annotations

import json

import jwt
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.deps import current_identity
from app.config import Settings
from app.domain.enums import Role
from app.domain.schemas import DatasetBuildRequest
from app.models.orm import LabelL3Gold
from app.repositories.audit import AuditRepository
from app.repositories.labels import LabelRepository
from app.services.dataset import DatasetBuilder
from app.services.drift import DriftService
from app.util import new_id, now_utc


# --------------------------------------------------------------- PyJWT auth path
def test_jwt_path_decodes_role_and_subject():
    s = Settings(auth_dev_mode=False, jwt_secret="topsecret")
    token = jwt.encode({"sub": "user-1", "role": "Admin"}, "topsecret", algorithm="HS256")
    ident = current_identity(x_role=None, x_user_id=None, authorization=f"Bearer {token}", settings=s)
    assert ident.role == Role.ADMIN
    assert ident.user_id == "user-1"


def test_jwt_invalid_token_is_401():
    s = Settings(auth_dev_mode=False, jwt_secret="topsecret")
    with pytest.raises(HTTPException) as exc:
        current_identity(x_role=None, x_user_id=None, authorization="Bearer not-a-jwt", settings=s)
    assert exc.value.status_code == 401


def test_jwt_wrong_secret_rejected():
    s = Settings(auth_dev_mode=False, jwt_secret="right-secret")
    forged = jwt.encode({"sub": "x", "role": "Admin"}, "wrong-secret", algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        current_identity(x_role=None, x_user_id=None, authorization=f"Bearer {forged}", settings=s)
    assert exc.value.status_code == 401


# --------------------------------------------------------- fail-closed config
def test_settings_reject_empty_secret_when_auth_enforced():
    with pytest.raises(ValidationError):
        Settings(auth_dev_mode=False, jwt_secret="")


def test_settings_reject_insecure_default_secret():
    with pytest.raises(ValidationError):
        Settings(auth_dev_mode=False, jwt_secret="dev-insecure-secret-change-me")


def test_settings_dev_mode_allows_empty_secret():
    s = Settings(auth_dev_mode=True, jwt_secret="")
    assert s.auth_dev_mode is True  # dev/test does not require a secret


# ----------------------------------------------- dataset build_query is JSON
def test_dataset_build_query_is_structured_json(db_session):
    repo = LabelRepository(db_session)
    repo.create_l2(
        sample_id="sec-s1", value="high_risk", confidence=0.9, fusion_policy="confidence_gap",
        fusion_version="fusion-v1", source_l1_ids=[], agreement_score=1.0, flag="agreed",
        fusion_reason="t", label_version="lv-sec-ds",
    )
    db_session.flush()

    resp = DatasetBuilder(db_session).build(
        DatasetBuildRequest(feature_version="fv1", label_version="lv-sec-ds")
    )
    from app.repositories.datasets import DatasetRepository

    manifest = DatasetRepository(db_session).get(resp.dataset_id)
    parsed = json.loads(manifest.build_query)  # must be valid JSON, not SQL text
    assert parsed["label_version"] == "lv-sec-ds"
    assert parsed["feature_version"] == "fv1"
    assert "SELECT" not in manifest.build_query  # no SQL-shaped string persisted


# ------------------------------------------- drift review enqueue is capped
def _seed_l3(session, sample_id: str) -> None:
    session.add(LabelL3Gold(
        gold_label_id=new_id("l3"), sample_id=sample_id, value="v", reviewer_id="r",
        review_reason=None, source_review_id=None, source_l1_ids=None, created_at=now_utc(),
        label_version="lv", status="active", superseded_by=None,
    ))


def test_drift_review_enqueue_is_capped_with_alert(db_session):
    for i in range(5):
        _seed_l3(db_session, f"cap-{i}")
    db_session.flush()

    svc = DriftService(db_session)
    svc.settings = Settings(drift_max_review_enqueue=2)  # env keeps auth_dev_mode=true

    enqueued = svc._route_anchors_to_review(run_id="run-cap", actor=None)
    assert enqueued == 2  # bounded, not 5

    alerts = AuditRepository(db_session).list_alerts()
    assert any("capped" in (a.details or {}).get("message", "") for a in alerts)
