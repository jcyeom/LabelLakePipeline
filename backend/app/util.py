"""Small shared helpers: id generation, hashing, time (README §7)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterator

# SQLite caps host parameters per statement (default 999); chunk IN clauses to stay
# well under it. PostgreSQL has no practical limit but chunking is harmless there.
IN_CHUNK = 500


def chunked(items: list, size: int = IN_CHUNK) -> Iterator[list]:
    """Yield successive ``size``-length chunks of ``items`` (for batched IN queries)."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def now_utc() -> datetime:
    """Timezone-aware UTC timestamp (README §7: all timestamps UTC)."""
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Generate a prefixed id, e.g. ``l1-<uuid4hex>`` (README §7 id prefixes)."""
    return f"{prefix}-{uuid.uuid4().hex}"


def sha256_hash(payload: Any) -> str:
    """Deterministic ``sha256:<hex>`` hash of an arbitrary JSON-serialisable payload.

    Used to compute ``inputs_hash`` for features (FR-1, NFR-3, §19.5).
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
