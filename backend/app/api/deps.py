"""Auth / RBAC dependencies (design: backend_design_prd 절차 12, PRD §12).

MVP dev-mode: identity comes from ``X-Role`` / ``X-User-Id`` headers so the API and
tests run without an IdP. Production swaps ``current_identity`` for JWT decoding
(README §3) while keeping ``require_role`` unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import InvalidTokenError

from app.config import Settings, get_settings
from app.domain.enums import Role, role_at_least


@dataclass
class Identity:
    user_id: str
    role: Role


def current_identity(
    x_role: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Identity:
    # Dev mode: trust X-Role header.
    if settings.auth_dev_mode:
        role_str = x_role or Role.VIEWER.value
        try:
            role = Role(role_str)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"unknown role: {role_str}")
        return Identity(user_id=x_user_id or "dev-user", role=role)

    # Production: decode JWT bearer token.
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        # PyJWT decodes the bearer token; algorithms is an explicit allowlist
        # (prevents alg-confusion). Signature/exp/format errors → InvalidTokenError.
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    try:
        role = Role(payload.get("role", ""))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid role claim")
    return Identity(user_id=payload.get("sub", "unknown"), role=role)


def require_role(minimum: Role):
    """Dependency factory enforcing a minimum role in the privilege order."""

    def _checker(identity: Identity = Depends(current_identity)) -> Identity:
        if not role_at_least(identity.role, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role {identity.role.value} lacks required {minimum.value}",
            )
        return identity

    return _checker


def require_exact_role(*allowed: Role):
    """Dependency factory enforcing membership in an explicit role set (non-linear gates)."""

    def _checker(identity: Identity = Depends(current_identity)) -> Identity:
        if identity.role not in allowed and identity.role != Role.ADMIN:
            allowed_str = ", ".join(r.value for r in allowed)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role {identity.role.value} not in [{allowed_str}]",
            )
        return identity

    return _checker
