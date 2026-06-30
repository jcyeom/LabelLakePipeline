"""Shared pagination dependency (OPTIMIZATION_PLAN / ARCHITECTURE_REVIEW P1).

Bounds unbounded list/search endpoints (audit lineage, label search, reviews, drift
metrics) with a limit+offset window so responses can't grow without bound.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


@dataclass
class PageParams:
    limit: int
    offset: int


def page_params(
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="페이지 크기"),
    offset: int = Query(default=0, ge=0, description="건너뛸 행 수"),
) -> PageParams:
    return PageParams(limit=limit, offset=offset)
