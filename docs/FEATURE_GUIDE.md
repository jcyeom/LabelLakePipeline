# LLP 기능 설명 문서 (Feature Guide)

> Label Lake Pipeline — 약지도 학습 라벨 관리 파이프라인
> 대상 독자: Data/ML/MLOps 엔지니어, 도메인 검수자(Reviewer), 운영자
> 구성: 시스템 개요 → 핵심 개념 → 기능별 상세 → 데이터 흐름 → 화면 → 권한 → 운영 지표 → 사용 시나리오
> 구현 근거: `backend/`(FastAPI, 191 테스트), `frontend/`(React SPA). 원본 요구: `pdf_llp.md`.

---

## 1. 시스템 개요

LLP는 **rule / LLM / human 라벨러**가 생성한 라벨을 데이터 레이크 내에서 **일급 객체(Label Object)** 로 저장·합의·검증·추적하는 파이프라인이다. 최종 라벨뿐 아니라 **라벨러별 후보 라벨을 영구 보존**하여 재현성·추적성·드리프트 감지를 제공한다.

```
원천 데이터 → feature → [라벨러 N개] → L1 후보(Silver, append-only)
                                          │
                              Fusion Engine(합의 정책)
                              ┌───────────┴────────────┐
                         값 일치/정책 충족          불일치
                              │                        │
                         L2 합의 라벨(Gold)     Human Review Queue
                                                       │ 사람 검수
                                                  L3 검증 라벨(Gold)
                                                       │
         Dataset Builder ← (L2/L3/L3_PRIORITY) ────────┘
         Drift Monitor(PSI/KL/anchor) · Gold Republish · Audit/Lineage
```

**기술 스택**: 백엔드 Python 3.11 + FastAPI + SQLAlchemy(SQLite→PostgreSQL), 프론트 React 18 + TS + Vite + TanStack Query + Recharts. 인증은 MVP에서 역할 기반 dev 모드(`X-Role` 헤더), 운영은 OAuth2/JWT.

---

## 2. 핵심 개념 — 라벨 3계층

| 계층 | 의미 | 저장 | 생성 주체 |
| --- | --- | --- | --- |
| **L1 Candidate** | 라벨러별 원시 후보 라벨 | Silver, **append-only(삭제·수정 금지)** | rule/llm/human 어댑터 |
| **L2 Consensus** | L1을 합의 정책으로 통합한 결과 | Gold | Fusion Engine |
| **L3 Gold-Standard** | 사람 검수를 통과한 고신뢰 라벨 | Gold(버전 이력 보존) | Human Reviewer |

**Label Object 공통 스키마**(전 라벨러 동일): `label_id, sample_id, feature_id, feature_version, value, task_type, method, method_ver, confidence?, rationale?, inputs_hash, labeled_at, run_id, agreement_group_id?, metadata?, status`.
- **불변식**: `inputs_hash`·`method_ver` 누락 시 저장 거부(HTTP 422). L1은 수정 불가 — 정정은 새 `label_id`+새 `run_id`로 재생성하고 기존 row는 `SUPERSEDED`.

---

## 3. 기능별 상세

### 3.1 Label Object 저장 (FR-1/FR-2)
- **무엇**: 모든 라벨러 출력을 단일 스키마로 Silver 계층에 append-only 저장.
- **API**: `POST /api/v1/labels/l1`(생성), `GET /api/v1/labels/l1?sample_id=`(조회).
- **상태값**: `CREATED·FAILED·SKIPPED·INVALID·SUPERSEDED`. 라벨러 실패도 별도 상태로 기록되어 추적 가능.
- **검증**: 동일 sample에 rule·llm 라벨이 독립 저장됨. 필수필드 누락은 422로 거부.

### 3.2 Labeler Adapter (FR-3)
공통 인터페이스 `LabelerAdapter.run(sample) -> LabelResult`. 새 라벨러는 스키마 변경 없이 `method`/`method_ver`로 확장.
- **Rule Labeler**: 결정론적 규칙 평가. 규칙 ID/버전·매칭 규칙명을 rationale에 저장. 미매칭 시 `SKIPPED`.
- **LLM Labeler**: 모델·프롬프트 해시·seed·temperature·top_p를 `method_ver`/metadata에 저장. **프롬프트 변경 시 method_ver가 달라짐**. 파싱 실패는 `max_retries` 후 `FAILED`로 격리되어 **파이프라인 전체를 중단시키지 않음**. (테스트 가능하도록 모델 호출은 주입형 client.)
- **Human Labeler**: 검수자 ID·코멘트 저장. L3 생성에 사용.

### 3.3 Fusion Engine — L2 합의 (FR-4)
L1 후보들을 합의 정책으로 통합하거나 검수 큐로 라우팅.
- **정책 7종**: `confidence_gap`(정본 기본 · 논문 알고리즘 1), `majority_vote`, `confidence_weighted`, `rule_priority`, `human_priority`, `kappa_based`(V1, 현재 majority 폴백), `custom_policy`.
- **알고리즘 1(기본) 동작**: 값 일치 → `agreed` L2(`agreement_score=1.0`). 불일치 시 신뢰도 상위-차상위 격차 `> θ` → `argmax_conf` 값 채택(`soft_disagreement`). 격차 `≤ θ` → 검수 큐(`human_required`, L2=NULL).
- **저장**: L2에 `source_l1_ids`, `fusion_policy`, `agreement_score`, `agreement`(다중 라벨러 raw 결과 구조화 기록 · 논문 표 1), `flag`, `fusion_reason` 기록.
- **API**: `POST /api/v1/fusion/run`(배치) → `{run_id, created_l2_count, human_review_count, failed_count}`.

### 3.4 Human Review → L3 (FR-5/FR-6)
- **큐**: 불일치 샘플을 우선순위와 함께 관리. 상태 `PENDING→IN_PROGRESS→COMPLETED/REJECTED`.
- **완료**: 검수자가 최종 값을 입력하면 **L3 Gold 라벨 생성**(`reviewer_id`/`review_reason` 포함), 기존 활성 L3는 `superseded`로 버전 이력 보존. 옵션으로 **L2 재생성**(human_priority).
- **API**: `POST /api/v1/reviews`(등록), `GET /api/v1/reviews?status=`(목록), `POST /api/v1/reviews/{id}/complete` → `{gold_label_id, status:"COMPLETED"}`.

### 3.5 Dataset Builder (FR-9)
학습 데이터셋을 feature/label 버전 기준으로 결합.
- **레벨**: `L2`, `L3`, `L3_PRIORITY`(샘플에 L3 있으면 L3, 없으면 L2).
- **필터**: `confidence_min`, `exclude_disagreement`(agreed 아닌 L2 제외).
- **산출**: `dataset_manifest`(`source_label_ids`, `build_query`, `manifest_uri="lake://gold/dataset_manifest/..."`)로 재현성 확보.
- **API**: `POST /api/v1/datasets/build` → `{dataset_id, sample_count, manifest_uri}`.

### 3.6 Drift Monitor (FR-7)
시간에 따른 라벨러 출력 변화·정확도 변화 감지.
- **Distribution Drift**: 두 기간의 L1 값 분포로 **PSI**, **KL divergence** 계산.
- **Anchor Drift**: L3 앵커 집합 대비 현재 라벨러 정확도 측정.
- **상태**: `NORMAL/WARNING/CRITICAL`(임계값 §14.2: PSI 0.1/0.25, KL 0.05/0.1).
- **API**: `POST /api/v1/drift/run`, `GET /api/v1/drift/metrics`.

### 3.7 Gold Republish (FR-8)
정책·버전 변경, L3 반영, 드리프트 발생 시 Gold L2를 재생성.
- **동작**: 새 활성 Gold 버전을 만들고 범위(전체/부분)에 대해 fusion 재실행 → 새 `label_version`의 L2 생성. 이전 버전은 보존(프로그램적 rollback 지원).
- **API**: `POST /api/v1/gold/republish`(Admin) → `{version_id, run_id, label_version, republished_count}`.

### 3.8 Audit & Lineage (FR-10)
라벨 생성·합의·검수·재발행·데이터셋 생성 과정을 audit_log에 기록.
- **API**: `GET /api/v1/audit/lineage?entity_id=` → 해당 label/run/dataset의 감사 레코드.

### 3.9 Dashboard 집계 (§11.1)
- **API**: `GET /api/v1/dashboard/metrics` → 전체 L1 수, 라벨러별 L1 수/실패율/평균 confidence, L2 합의율, 검수 대기 수, L3 수, 라벨러별 드리프트 상태, Gold 버전.

---

## 4. 데이터 흐름 (파이프라인)

1. **L1 생성**(§10.1): feature 생성 → `inputs_hash` 계산 → 라벨러 실행 → Label Object 변환 → `labels_l1_candidate` 저장(실패는 FAILED).
2. **L2 생성**(§10.2): sample별 L1 조회 → 정책 적용 → 합의 시 L2 저장 / 불일치 시 검수 큐 등록.
3. **L3 생성**(§10.3): 검수자가 큐에서 선택 → L1·rationale 확인 → 최종 라벨 입력 → L3 저장 → (옵션) L2 재생성.
4. **Drift 감지**(§10.4): 기간별 L1 분포 집계 → PSI/KL → L3 앵커 정확도 → 상태 기록 → 필요 시 Republish 트리거.

---

## 5. 화면 (프론트엔드 §11)

| 경로 | 화면 | 핵심 기능 |
| --- | --- | --- |
| `/dashboard` | Dashboard | 운영 지표 카드 + 라벨러 비교 차트 + 드리프트 요약(60초 폴링) |
| `/samples/:sampleId` | Sample Detail | L1 후보 비교 테이블 + L2/L3 결과 + 계보 |
| `/reviews`, `/reviews/:id` | Human Review | 검수 큐(30초 폴링) + 분할 검수 패널 → L3 입력 |
| `/drift` | Drift Monitoring | PSI/KL/anchor 차트(임계선) + Drift 실행 + Gold Republish |
| `/datasets/build` | Dataset Builder | 버전·레벨·필터 폼 → manifest |
| `/fusion/run` | Fusion 실행 | 정책·임계값 폼 → 합의 결과 카운트 |

상태 배지 색상: NORMAL/agreed/active=초록, WARNING/PENDING=황색, CRITICAL/FAILED=빨강, human_required=보라, SKIPPED/SUPERSEDED=회색.

---

## 6. 권한 (§12)

| 역할 | 권한 범위 | 접근 화면/액션 |
| --- | --- | --- |
| **Admin** | 전체 설정·재발행·정책 | 전 화면 + Gold Republish |
| **DataEngineer** | 파이프라인 실행·데이터셋·로그 | Fusion 실행, Drift 실행, Dataset, 조회 |
| **MLEngineer** | L1/L2/L3 조회·데이터셋 | Sample Detail, Dataset Builder |
| **Reviewer** | Human Review·L3 생성 | 검수 큐·검수 패널 |
| **Viewer** | 대시보드·라벨 조회 | Dashboard, 라벨 조회 |

게이팅: 라우트 `ProtectedRoute(minRole)`, 메뉴/버튼 `RoleGate(minRole)`. 백엔드 `require_role`/`require_exact_role`로 이중 시행(예: 검수 완료는 Reviewer/Admin 전용).

---

## 7. 운영 지표 & 알림 (§13)

- **지표**: 라벨러 성공/실패율, L2 합의율, 검수 큐 대기 수, 평균 검수 시간, drift PSI/KL, anchor 정확도, Gold 재발행 수, dataset 생성 수.
- **알림 조건(설계)**: 라벨러 실패율·드리프트 임계 초과, 합의율 급락, 큐 적체 등. (MVP는 지표 집계까지, 알림 채널은 V1.)

---

## 8. 사용 시나리오 예시

**시나리오: 신고 콘텐츠 위험도 라벨링**
1. Rule + LLM 라벨러가 sample-001에 각각 L1 생성(`medium_risk`, `high_risk`).
2. Fusion(majority_vote): 값 불일치 → Human Review Queue 등록.
3. Reviewer가 검수 패널에서 L1 후보·rationale 비교 → `high_risk` 확정 → L3 생성, L2 재생성.
4. ML Engineer가 `L3_PRIORITY`로 Dataset Build → manifest로 재현 가능한 학습셋 확보.
5. MLOps가 월 단위 Drift 실행 → LLM 라벨러 PSI 상승 감지 → 필요 시 Gold Republish.

---

## 9. 실행 방법 (요약)

```bash
# 백엔드
cd backend && python3.11 -m venv .venv && ./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m pytest                       # 191 passed
./.venv/bin/python -m uvicorn app.main:app         # http://localhost:8000/docs

# 프론트엔드
cd frontend && npm install && cp .env.example .env
npm run dev                                        # http://localhost:5173
```

---

## 10. 범위 및 한계

- **MVP 포함**(§15.1): Label Object, L1 저장, Rule/LLM 어댑터, majority_vote fusion, confidence_gap 검수 등록, L3 저장, Dataset Builder, Audit Log, Dashboard — 전부 구현.
- **초과 구현(V1 선반영)**: Drift PSI/KL, confidence_weighted/priority fusion, Gold Republish, Label Version.
- **1·2순위 갭 해결됨**(2026-06-22): Human Review 자동 라우팅(LLM 파싱실패·저신뢰·불일치), `agreement_group_id` 그룹 합의, Sample Detail feature 요약, **Gold rollback API**, **Dataset 옵션(task_type/method_filter/include_rationale) 적용**, **Drift 앵커 정확도 하락폭**, `/drift` 라우트 명시 가드 — 테스트 검증 완료(`test_gap_fixes.py`, `test_gap_fixes2.py`, `test_drift.py`).
- **잔여 보완 갭(3순위)**(상세 `VERIFICATION_REPORT.md` §4): 라벨러별 지표 상단 카드(F-G2), 검수 정렬 컨트롤(F-G3), drift-트리거 검수 라우팅, 임계 초과 알림 발행, run_id/method_ver 라벨 조회 API, manifest 재현 실증 테스트.
- **프로덕션 델타**(설계 문서화): Postgres 파티셔닝·append-only 트리거, Alembic 마이그레이션, DuckDB/Trino 레이크 조인, Dagster 배치, OAuth2/JWT.
