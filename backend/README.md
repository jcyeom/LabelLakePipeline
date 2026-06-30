# LLP Backend (MVP)

FastAPI implementation of the Label Lake Pipeline, built from the design PRDs in
[`../design/`](../design/). Scope = PRD §15 MVP plus the core V1 services (Fusion
policies, Drift PSI/KL, Gold Republish). See `../design/backend_design_prd.md` for the
procedure-by-procedure design and `../design/README.md` for the canonical contract.

## Stack
- Python 3.11 · FastAPI · Pydantic v2 · SQLAlchemy 2
- Storage: SQLite (dev/test, portable) → PostgreSQL 15 (production, same models)
- Auth: dev-mode `X-Role` header (MVP) → OAuth2/JWT (production)

## Setup
```bash
cd backend
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

## Run
```bash
./.venv/bin/python -m uvicorn app.main:app --reload
# OpenAPI docs: http://127.0.0.1:8000/docs
```

Dev-mode auth: pass a role header, e.g. `-H "X-Role: DataEngineer"`. Roles:
`Admin · DataEngineer · MLEngineer · Reviewer · Viewer` (privilege order).

## Test
```bash
./.venv/bin/python -m pytest        # 191 tests
```

## Layout
```
app/
  config.py db.py util.py errors.py main.py
  domain/      enums.py schemas.py            # shared contract (README §4/§5)
  models/      orm.py                          # 9 tables (db_design_prd §8)
  repositories/ labels reviews runs audit datasets drift   # data access
  services/    labelers/{rule,llm,human}  fusion review dataset drift dashboard gold pipeline
  api/         deps.py  routers/{labels,fusion,reviews,drift,datasets,gold,audit,dashboard}
tests/         12 files, 191 tests
```

## Endpoints (canonical, README §6)
`POST /api/v1/labels/l1` · `GET /api/v1/labels/{l1,l2,l3}` · `POST /api/v1/fusion/run` ·
`POST/GET /api/v1/reviews` · `POST /api/v1/reviews/{id}/complete` · `POST /api/v1/drift/run` ·
`GET /api/v1/drift/metrics` · `POST /api/v1/datasets/build` · `POST /api/v1/gold/republish` ·
`GET /api/v1/audit/lineage` · `GET /api/v1/dashboard/metrics`

## FR coverage
FR-1/2 (L1 store/validate, append-only) · FR-3 (rule/llm/human adapters) ·
FR-4 (Fusion: 6 policies) · FR-5/6 (Review queue → L3) · FR-7 (Drift PSI/KL/anchor) ·
FR-8 (Gold Republish + rollback) · FR-9 (Dataset Builder, L3_PRIORITY) · FR-10 (Audit/Lineage).

## Production deltas (documented, not in MVP)
- Postgres partitioning + append-only triggers + JSONB/arrays (db_design_prd 절차 2/9).
- Alembic migrations instead of `init_db()` (db_design_prd 절차 11).
- DuckDB/Trino lake joins for Dataset Builder; Dagster batch orchestration.
- JWT/OAuth2 replacing the dev-mode `X-Role` header.
