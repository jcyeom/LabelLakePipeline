"""Shared pytest fixtures.

A single in-memory SQLite DB (StaticPool) backs each test; ``get_session`` is
dependency-overridden so API requests and direct service calls share that DB.
Auth runs in dev-mode: pass roles via the ``X-Role`` header helpers below.
"""
from __future__ import annotations

import os

# Tests run against the dev-mode auth (X-Role headers). Set this BEFORE importing any
# app module, since app.config defaults to fail-closed auth (auth_dev_mode=False) and
# get_settings() is evaluated at app.db import time.
os.environ.setdefault("LLP_AUTH_DEV_MODE", "true")

from contextlib import contextmanager
from typing import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session, get_session_factory
from app.domain.enums import Role
from app.main import create_app
from app.models import orm  # noqa: F401  (register models on Base.metadata)
from app.services.labelers.base import Sample


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture()
def db_session(session_factory) -> Session:
    """A session for direct service/repository tests."""
    s = session_factory()
    try:
        yield s
        s.commit()
    finally:
        s.close()


@pytest.fixture()
def app(session_factory):
    application = create_app()

    def _override():
        s = session_factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    application.dependency_overrides[get_session] = _override
    # Background jobs open their own session via the factory; bind it to the test engine.
    application.dependency_overrides[get_session_factory] = lambda: session_factory
    return application


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def auth() -> Callable[[Role], dict]:
    """Return headers carrying a given role (dev-mode auth)."""

    def _headers(role: Role, user_id: str = "tester") -> dict:
        return {"X-Role": role.value, "X-User-Id": user_id}

    return _headers


@pytest.fixture()
def query_counter(engine):
    """Count SQL statements executed on the shared engine.

    Usage::

        with query_counter() as count:
            svc.run(...)
        assert count.value <= LIMIT   # guards against N+1 regressions
    """

    class _Counter:
        value = 0   # all statements
        selects = 0  # SELECT statements only (read-side N+1 invariant)

    @contextmanager
    def _capture():
        counter = _Counter()

        def _on_exec(conn, cursor, statement, params, context, executemany):
            counter.value += 1
            if statement.lstrip()[:6].upper() == "SELECT":
                counter.selects += 1

        event.listen(engine, "before_cursor_execute", _on_exec)
        try:
            yield counter
        finally:
            event.remove(engine, "before_cursor_execute", _on_exec)

    return _capture


@pytest.fixture()
def make_sample() -> Callable[..., Sample]:
    def _make(sample_id="sample-001", features=None, **kw) -> Sample:
        return Sample(
            sample_id=sample_id,
            feature_id=kw.get("feature_id", "feature-001"),
            feature_version=kw.get("feature_version", "fv-2026-01"),
            features=features or {"risk_score": 0.9, "text": "위험 징후"},
            task_type=kw.get("task_type", "classification"),
        )

    return _make


def submit_and_wait(client, headers, path: str, body: dict) -> dict:
    """POST an async batch job (202 + run_id), then poll the run and return its JSON.

    Starlette's TestClient executes the BackgroundTask within the POST call, so the
    run is already finished by the time we poll. Returns the run record (with result).
    """
    r = client.post(path, json=body, headers=headers)
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    run = client.get(f"/api/v1/runs/{run_id}", headers=headers)
    assert run.status_code == 200, run.text
    return run.json()


def l1_payload(**overrides) -> dict:
    """Build a valid POST /api/v1/labels/l1 body; override any field."""
    body = {
        "sample_id": "sample-001",
        "feature_id": "feature-001",
        "feature_version": "fv-2026-01",
        "value": "high_risk",
        "task_type": "classification",
        "method": "llm",
        "method_ver": "llm-v2_prompt-v3",
        "confidence": 0.82,
        "inputs_hash": "sha256:abc",
        "run_id": "run-001",
    }
    body.update(overrides)
    return body
