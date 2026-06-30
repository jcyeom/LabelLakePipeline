"""App meta + production-auth branch coverage (health endpoint, JWT bearer paths)."""
from __future__ import annotations

import jwt
import pytest
from fastapi import HTTPException

from app.api.deps import current_identity
from app.config import Settings


def test_health_endpoint_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_prod_auth_missing_bearer_is_401():
    s = Settings(auth_dev_mode=False, jwt_secret="secret")
    with pytest.raises(HTTPException) as exc:
        current_identity(x_role=None, x_user_id=None, authorization=None, settings=s)
    assert exc.value.status_code == 401


def test_prod_auth_non_bearer_scheme_is_401():
    s = Settings(auth_dev_mode=False, jwt_secret="secret")
    with pytest.raises(HTTPException) as exc:
        current_identity(x_role=None, x_user_id=None, authorization="Basic abc", settings=s)
    assert exc.value.status_code == 401


def test_prod_auth_invalid_role_claim_is_403():
    s = Settings(auth_dev_mode=False, jwt_secret="secret")
    token = jwt.encode({"sub": "u", "role": "NotARealRole"}, "secret", algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        current_identity(x_role=None, x_user_id=None, authorization=f"Bearer {token}", settings=s)
    assert exc.value.status_code == 403


def test_dev_auth_unknown_role_header_is_401():
    s = Settings(auth_dev_mode=True, jwt_secret="")
    with pytest.raises(HTTPException) as exc:
        current_identity(x_role="Wizard", x_user_id=None, authorization=None, settings=s)
    assert exc.value.status_code == 401
