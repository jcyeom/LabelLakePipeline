"""Human Review routers (backend_design_prd 절차 5/6, FR-5/FR-6, §9.4/§9.5)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Identity, require_exact_role, require_role
from app.api.pagination import PageParams, page_params
from app.db import get_session
from app.domain.enums import Role
from app.domain.schemas import (
    ReviewCompleteRequest,
    ReviewCompleteResponse,
    ReviewCreateRequest,
    ReviewCreateResponse,
    ReviewListResponse,
    ReviewView,
)
from app.services.review import ReviewService

router = APIRouter(prefix="/api/v1/reviews", tags=["reviews"])


@router.post("", response_model=ReviewCreateResponse, status_code=201)
def create_review(
    req: ReviewCreateRequest,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_role(Role.DATA_ENGINEER)),
) -> ReviewCreateResponse:
    return ReviewService(session).register(req, actor=identity.user_id)


@router.get("", response_model=ReviewListResponse)
def list_reviews(
    status: Optional[str] = Query(default=None),
    page: PageParams = Depends(page_params),
    session: Session = Depends(get_session),
    _identity: Identity = Depends(require_role(Role.REVIEWER)),
) -> ReviewListResponse:
    return ReviewService(session).list(status=status, limit=page.limit, offset=page.offset)


@router.get("/{review_id}", response_model=ReviewView)
def get_review(
    review_id: str,
    session: Session = Depends(get_session),
    _identity: Identity = Depends(require_role(Role.REVIEWER)),
) -> ReviewView:
    return ReviewService(session).get_one(review_id)


@router.post("/{review_id}/complete", response_model=ReviewCompleteResponse)
def complete_review(
    review_id: str,
    req: ReviewCompleteRequest,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_exact_role(Role.REVIEWER)),
) -> ReviewCompleteResponse:
    return ReviewService(session).complete(review_id, req, actor=identity.user_id)
