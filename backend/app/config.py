"""Application configuration (design: backend_design_prd 절차 1, README §3)."""
from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT_SECRET = "dev-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLP_", env_file=".env", extra="ignore")

    app_name: str = "Label Lake Pipeline"
    # MVP uses SQLite for portability; production swaps in PostgreSQL 15 (README §3).
    database_url: str = "sqlite+pysqlite:///./llp.db"
    # CORS allowed origins for the browser SPA. Dev uses the Vite proxy (same-origin);
    # set explicitly when the frontend is served from a different origin.
    cors_allow_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Lake root for L1 Parquet / Gold artifacts (paths recorded, see db_design_prd 절차 2/7).
    lake_root: str = "lake://"
    # Auth (절차 12). HS256 shared secret; production swaps in OAuth2 IdP.
    # No shipped default secret — it MUST be provided via LLP_JWT_SECRET in production.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    # Fail-closed by default: real auth (JWT) is enforced unless dev mode is explicitly
    # enabled (LLP_AUTH_DEV_MODE=true), which trusts the X-Role header for tests/dev.
    auth_dev_mode: bool = False

    # Connection pool (PostgreSQL only; ignored for SQLite). OPTIMIZATION_PLAN C1.
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800  # seconds; recycle connections to dodge stale ones
    db_pool_timeout: int = 10  # seconds to wait for a connection before failing fast
    # Background batch jobs use a SEPARATE pool so a burst of long jobs can't exhaust
    # the request-serving pool, plus a hard cap on concurrent batch jobs.
    bg_pool_size: int = 4
    # Headroom above batch_max_concurrency so a failure-record session (fresh session)
    # can't contend with the job's own session at the pool ceiling.
    bg_max_overflow: int = 8
    batch_max_concurrency: int = 4

    # Fusion defaults (PRD §14.1). 정본 기본값 = 논문 알고리즘 1 (confidence_gap).
    fusion_default_policy: str = "confidence_gap"
    fusion_confidence_gap_threshold: float = 0.15
    fusion_min_labeler_count: int = 2
    # A surviving label below this confidence routes the sample to human review (§5).
    fusion_low_confidence_threshold: float = 0.5

    # Drift thresholds (PRD §14.2)
    drift_psi_warning_threshold: float = 0.1
    drift_psi_critical_threshold: float = 0.25
    drift_kl_warning_threshold: float = 0.05
    drift_kl_critical_threshold: float = 0.1
    drift_anchor_accuracy_drop_threshold: float = 0.05
    # Upper bound on review rows a single drift run may enqueue (bounds write amplification).
    drift_max_review_enqueue: int = 1000

    @model_validator(mode="after")
    def _require_secret_when_enforcing_auth(self) -> "Settings":
        """Fail fast at startup if JWT auth is enforced without a real secret, so the
        service never boots into a forgeable-token state (security: A02/A07)."""
        if not self.auth_dev_mode and (
            not self.jwt_secret or self.jwt_secret == _INSECURE_DEFAULT_SECRET
        ):
            raise ValueError(
                "LLP_JWT_SECRET must be set to a non-default value when auth_dev_mode is disabled "
                "(or set LLP_AUTH_DEV_MODE=true for local/dev only)."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
