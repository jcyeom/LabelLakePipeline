"""Label routers (backend_design_prd 절차 2, FR-1/FR-2, §9.1/§9.2)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Identity, require_role
from app.api.pagination import PageParams, page_params
from app.db import get_session
from app.domain.enums import Role
from app.domain.schemas import (
    L1ListResponse,
    L1LabelView,
    L1RecordView,
    L1SearchResponse,
    L2View,
    L3View,
    LabelL1Out,
    LabelObjectIn,
)
from app.errors import NotFoundError, SchemaValidationError
from app.repositories.audit import AuditRepository
from app.repositories.labels import LabelRepository

router = APIRouter(prefix="/api/v1/labels", tags=["labels"])


@router.post("/l1", response_model=LabelL1Out, status_code=201)
def create_l1(
    payload: LabelObjectIn,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_role(Role.DATA_ENGINEER)),
) -> LabelL1Out:
    repo = LabelRepository(session)
    row = repo.create_l1(payload)  # raises SchemaValidationError (422) on missing required fields
    AuditRepository(session).record(
        entity_type="l1", entity_id=row.label_id, action="create", actor=identity.user_id, run_id=row.run_id
    )
    return LabelL1Out(label_id=row.label_id, status=row.status)


@router.get("/l1", response_model=L1ListResponse)
def list_l1(
    sample_id: str = Query(...),
    session: Session = Depends(get_session),
    _identity: Identity = Depends(require_role(Role.ML_ENGINEER)),
) -> L1ListResponse:
    repo = LabelRepository(session)
    rows = repo.get_l1_by_sample(sample_id, active_only=False)
    return L1ListResponse(sample_id=sample_id, labels=[L1LabelView.model_validate(r) for r in rows])


@router.get("/search", response_model=L1SearchResponse)
def search_l1(
    sample_id: Optional[str] = Query(default=None),
    run_id: Optional[str] = Query(default=None),
    method_ver: Optional[str] = Query(default=None),
    page: PageParams = Depends(page_params),
    session: Session = Depends(get_session),
    _identity: Identity = Depends(require_role(Role.ML_ENGINEER)),
) -> L1SearchResponse:
    """Lineage search for L1 labels by run_id (FR-2) or method_ver/prompt hash (FR-10).

    Paginated (limit/offset) so large lineage result sets can't return unbounded.
    """
    repo = LabelRepository(session)
    if run_id:
        rows = repo.get_l1_by_run(run_id, limit=page.limit, offset=page.offset)
    elif method_ver:
        rows = repo.get_l1_by_method_ver(method_ver, limit=page.limit, offset=page.offset)
    elif sample_id:
        rows = repo.get_l1_by_sample(sample_id, active_only=False)[page.offset : page.offset + page.limit]
    else:
        raise SchemaValidationError("one of sample_id / run_id / method_ver is required")
    return L1SearchResponse(count=len(rows), labels=[L1RecordView.model_validate(r) for r in rows])


@router.get("/l2", response_model=L2View)
def get_l2(
    sample_id: str = Query(...),
    session: Session = Depends(get_session),
    _identity: Identity = Depends(require_role(Role.ML_ENGINEER)),
) -> L2View:
    row = LabelRepository(session).get_l2_by_sample(sample_id)
    if row is None:
        raise NotFoundError(f"no L2 for sample {sample_id}")
    return L2View.model_validate(row)


@router.get("/l3", response_model=L3View)
def get_l3(
    sample_id: str = Query(...),
    session: Session = Depends(get_session),
    _identity: Identity = Depends(require_role(Role.ML_ENGINEER)),
) -> L3View:
    row = LabelRepository(session).get_l3_by_sample(sample_id)
    if row is None:
        raise NotFoundError(f"no L3 for sample {sample_id}")
    return L3View.model_validate(row)
