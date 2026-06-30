"""모든 에러 응답이 ErrorResponse 봉투(error_code/message/details)를 따르는지 검증.

P0: 인증/인가(401/403)와 검증(422)이 FastAPI 기본 {"detail": ...} 대신 통일된
봉투를 반환해야 프론트가 단일 파서로 처리할 수 있다.
"""
from __future__ import annotations

from app.domain.enums import Role
from tests.conftest import l1_payload


def test_forbidden_uses_error_envelope(client, auth):
    # Viewer는 fusion 실행 권한 없음 → 403.
    r = client.post(
        "/api/v1/fusion/run",
        json={"sample_ids": ["s1"]},
        headers=auth(Role.VIEWER),
    )
    assert r.status_code == 403
    body = r.json()
    assert body["error_code"] == "FORBIDDEN"
    assert "message" in body
    assert "detail" not in body  # FastAPI 기본 포맷이 아니어야 함


def test_unauthorized_uses_error_envelope(client):
    # 알 수 없는 역할 헤더 → 401 (dev-mode).
    r = client.post(
        "/api/v1/fusion/run",
        json={"sample_ids": ["s1"]},
        headers={"X-Role": "NotARealRole"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["error_code"] == "UNAUTHORIZED"
    assert "detail" not in body


def test_validation_error_uses_error_envelope_with_details_list(client, auth):
    # method_ver 누락 등 스키마 검증 실패 → 422, details는 오류 목록.
    bad = l1_payload()
    del bad["method_ver"]
    r = client.post("/api/v1/labels/l1", json=bad, headers=auth(Role.DATA_ENGINEER))
    assert r.status_code == 422
    body = r.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert isinstance(body["details"], list)
    assert "detail" not in body


def test_not_found_uses_error_envelope(client, auth):
    r = client.get("/api/v1/runs/run-does-not-exist", headers=auth(Role.VIEWER))
    assert r.status_code == 404
    body = r.json()
    assert body["error_code"] == "NOT_FOUND"
