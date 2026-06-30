# LLP (Label Lake Pipeline) — 설계 문서 색인

> 본 디렉터리는 `pdf_llp.md`(개발용 PRD)를 구현 가능한 설계로 분해한 **design PRD** 모음입니다.
> 백엔드 / 프론트엔드 / 데이터베이스 세 도메인으로 분리하고, 각 도메인은 **절차(procedure) 단위**로 구성됩니다.

## 1. 문서 구성

| 문서 | 도메인 | 내용 |
| --- | --- | --- |
| [`README.md`](./README.md) | 공통 | 아키텍처 개요, 기술 스택 결정, **정식(canonical) 데이터 계약**, 네이밍 규칙 |
| [`db_design_prd.md`](./db_design_prd.md) | Database | 데이터 레이크 계층 / 테이블 스키마 / 파티셔닝 / 마이그레이션 / 보존 정책 절차 |
| [`backend_design_prd.md`](./backend_design_prd.md) | Backend | API / 라벨러 어댑터 / Fusion / Review / Drift / Dataset / Audit 절차 |
| [`frontend_design_prd.md`](./frontend_design_prd.md) | Frontend | Dashboard / Sample Detail / Human Review / Drift 모니터링 화면 절차 |

> **이 README는 세 도메인 문서의 단일 진실 공급원(SSOT)입니다.** 세 문서는 여기서 정의한
> Label Object 스키마, 상태값, API 경로, 네이밍을 그대로 따릅니다. 충돌 시 본 문서가 우선합니다.

## 2. 아키텍처 개요

```
┌────────────┐   ┌──────────────────────────────────────────────┐   ┌───────────────┐
│ Frontend   │   │ Backend (FastAPI)                            │   │ Storage       │
│ React+TS   │   │                                              │   │               │
│            │   │  API Gateway (REST /api/v1)                  │   │ PostgreSQL    │
│ Dashboard  │──▶│   ├ labels   ├ fusion   ├ reviews            │──▶│  (operational │
│ SampleView │   │   ├ drift    ├ datasets ├ audit              │   │   + metadata) │
│ ReviewView │   │                                              │   │               │
│ DriftView  │   │  Services                                    │   │ Object Store  │
└────────────┘   │   ├ LabelerAdapter(rule/llm/human)           │──▶│  (MinIO/S3)   │
                 │   ├ FusionEngine     ├ DriftMonitor          │   │  Parquet/     │
                 │   ├ ReviewService    ├ DatasetBuilder        │   │  Iceberg      │
                 │   └ AuditService     └ GoldRepublisher       │   │  lake://      │
                 │                                              │   └───────────────┘
                 │  Batch Workers (Fusion/Drift/Dataset jobs)   │
                 └──────────────────────────────────────────────┘
```

### 데이터 계층 매핑 (PRD §5.2 준수)

| 계층 | 저장 대상 | 물리 저장소 |
| --- | --- | --- |
| Bronze | 원천 데이터 | Object Store (`lake://bronze/...`) |
| Silver | 정제 feature, **L1 후보 라벨** (append-only) | Object Store Parquet/Iceberg (`lake://silver/...`) + Postgres 인덱스 |
| Gold | **L2 합의 라벨, L3 검증 라벨, 학습 데이터셋** | Object Store (`lake://gold/...`) + Postgres |

## 3. 기술 스택 결정 (Decision Record)

| 영역 | 선택 | 근거 |
| --- | --- | --- |
| Backend 언어/프레임워크 | **Python 3.11 + FastAPI + Pydantic v2** | PRD의 REST API 명세와 1:1 매핑, ML/LLM 라벨러 생태계, 비동기 배치 |
| 운영 DB | **PostgreSQL 15** | 큐/감사/실행 레지스트리/메타데이터의 트랜잭션·인덱스 조회 (NFR-6 sample_id 빠른 조회) |
| 라벨 저장(대용량 append) | **Object Store + Parquet (MVP) → Apache Iceberg (V1)** | L1 append-only 대용량·파티셔닝·계보(NFR-4, §19.2) |
| 레이크 쿼리 엔진 | **DuckDB (MVP) → Trino/Spark (V1)** | Dataset Builder의 feature-label join, 분포 집계 |
| ORM/마이그레이션 | **SQLAlchemy 2 + Alembic** | 스키마 버전 관리 |
| 배치 오케스트레이션 | **MVP: FastAPI BackgroundTasks/스크립트 → V1: Dagster** | Fusion/Drift/Republish 배치 (NFR-6) |
| Frontend | **React 18 + TypeScript + Vite** | SPA 관리 화면 |
| Frontend 상태/데이터 | **TanStack Query + Zustand** | 서버 상태 캐싱, 폴링 |
| Frontend UI/차트 | **Tailwind + shadcn/ui + Recharts** | Drift PSI/KL 시각화, 큐 테이블 |
| 인증/인가 | **OAuth2/JWT + RBAC 미들웨어** | PRD §12 역할 5종 (MVP는 단순 RBAC) |
| API 계약 | **OpenAPI 3.1 (FastAPI 자동생성)** | FE/BE 계약 동기화 |

## 4. 정식(Canonical) Label Object 스키마

> PRD §6 FR-1 + §8 데이터 모델을 통합한 **단일 정의**. 세 도메인 문서는 이 정의를 참조합니다.

```python
# 공통 Label Object (FR-1)
class LabelObject(BaseModel):
    label_id: str          # 필수 · UUIDv7 (시간정렬). 형식: "l1-<uuid>" / "l3-<uuid>"
    sample_id: str         # 필수
    feature_id: str        # 필수
    feature_version: str   # 필수
    value: dict | str | float  # 필수 · task_type별 해석, 저장은 JSON
    task_type: str         # 필수 · classification|regression|ranking|...
    method: str            # 필수 · rule|llm|human
    method_ver: str        # 필수 · 규칙ID|모델버전|프롬프트해시|검수자ID
    confidence: float | None       # 선택
    rationale: dict | str | None   # 선택
    inputs_hash: str       # 필수 · "sha256:..."  (누락 시 저장 거부 → 422)
    labeled_at: datetime   # 필수
    run_id: str            # 필수
    agreement_group_id: str | None # 선택 · 동일 샘플 라벨 그룹
    agreement: list[dict] | None   # 선택 · 다중 라벨러 raw 결과의 구조화 기록(논문 표 1). L2 합의 시 채워짐
    metadata: dict | None          # 선택
    status: str            # CREATED|FAILED|SKIPPED|INVALID|SUPERSEDED (L1 상태머신)
```

### 검증 불변식 (모든 도메인 공통)
- `inputs_hash` 또는 `method_ver` 누락 → 저장 거부 (HTTP 422, `status=INVALID` 로그).
- L1 row는 **수정 금지 (append-only)**. 정정은 새 `label_id` + 새 `run_id` + 이전 row `SUPERSEDED`.
- 동일 `sample_id`에 복수 Label Object 허용.

## 5. 상태값 사전 (Enums) — 전 도메인 공유

| Enum | 값 | 출처 |
| --- | --- | --- |
| `L1Status` | CREATED · FAILED · SKIPPED · INVALID · SUPERSEDED | FR-2 |
| `L2Flag` | agreed · soft_disagreement · human_required | §8.2 |
| `L3Status` | active · superseded | §8.3 |
| `ReviewStatus` | PENDING · IN_PROGRESS · COMPLETED · REJECTED | FR-5 |
| `DriftStatus` | NORMAL · WARNING · CRITICAL · REPUBLISH_REQUIRED | FR-7 |
| `FusionPolicy` | **confidence_gap(정본 기본 · 논문 알고리즘 1)** · majority_vote · confidence_weighted · rule_priority · human_priority · kappa_based · custom_policy | FR-4 |
| `LabelLevel` | L2 · L3 · L3_PRIORITY | FR-9 |
| `Role` | Admin · DataEngineer · MLEngineer · Reviewer · Viewer | §12 |

## 6. API 표면 (Canonical Routes) — FR-9 / §9

| Method | Path | 설명 | 권한 |
| --- | --- | --- | --- |
| POST | `/api/v1/labels/l1` | L1 라벨 저장 | DataEngineer+ |
| GET | `/api/v1/labels/l1?sample_id=` | sample 기준 L1 조회 | MLEngineer+ |
| GET | `/api/v1/labels/l2?sample_id=` | L2 조회 | MLEngineer+ |
| GET | `/api/v1/labels/l3?sample_id=` | L3 조회 | MLEngineer+ |
| POST | `/api/v1/fusion/run` | Fusion 배치 실행 | DataEngineer+ |
| POST | `/api/v1/reviews` | Human Review 등록 | DataEngineer+ |
| GET | `/api/v1/reviews?status=` | 검수 큐 조회 | Reviewer+ |
| POST | `/api/v1/reviews/{review_id}/complete` | 검수 완료 → L3 생성 | Reviewer+ |
| POST | `/api/v1/drift/run` | Drift 측정 | DataEngineer+ |
| GET | `/api/v1/drift/metrics` | Drift 지표 조회 | Viewer+ |
| POST | `/api/v1/datasets/build` | Dataset 생성 | MLEngineer+ |
| POST | `/api/v1/gold/republish` | Gold 재발행 | Admin |
| GET | `/api/v1/audit/lineage` | 계보 조회 | DataEngineer+ |
| GET | `/api/v1/dashboard/metrics` | 대시보드 집계 | Viewer+ |

## 7. 네이밍 / 식별자 규칙

- 테이블: `snake_case` 복수형 도메인 접두 (`labels_l1_candidate`, `human_review_queue`).
- ID 프리픽스: `l1-`, `l2-`, `l3-`, `run-`, `fusion-run-`, `review-`, `drift-`, `dataset-`.
- 시각: 모두 UTC `timestamptz`.
- 해시: `sha256:<hex>` 접두 명시.
- 레이크 경로: `lake://<layer>/<table>/<partition>/...`.

## 8. 구현 순서 (마일스톤 매핑, PRD §20)

1. **M1** DB 스키마 + 저장 API → `db_design_prd.md` 절차 1~4, `backend_design_prd.md` 절차 1~2
2. **M2** 라벨러 어댑터 → `backend` 절차 3
3. **M3** Fusion Engine + Review Queue 자동 등록 → `backend` 절차 4~5
4. **M4** Human Review + L3 → `backend` 절차 5~6, `frontend` 절차 3
5. **M5** Dataset Builder → `backend` 절차 7
6. **M6** Drift Monitor → `backend` 절차 8, `frontend` 절차 4
7. **M7** 운영 대시보드 → `frontend` 절차 1~2

각 도메인 문서의 절차는 위 마일스톤에 맞춰 **독립 구현·검증 가능**하도록 작성됩니다.
