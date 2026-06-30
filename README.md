# LLP — Label Lake Pipeline

[![Repo](https://img.shields.io/badge/GitHub-jcyeom%2FLabelLakePipeline-181717?logo=github&logoColor=white)](https://github.com/jcyeom/LabelLakePipeline)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Pydantic%20v2-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18%20%2B%20TypeScript-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-build-646CFF?logo=vite&logoColor=white)](https://vitejs.dev/)
[![Tests](https://img.shields.io/badge/tests-212%20passing-brightgreen)](backend/tests)

저장소: https://github.com/jcyeom/LabelLakePipeline

약지도 학습(weak supervision) 라벨을 데이터 레이크 안에서 일급 객체(Label Object)로
저장, 합의, 검증, 추적하는 라벨 관리 파이프라인이다.

rule / LLM / human 라벨러가 만든 라벨을 최종 결과만 남기지 않고 라벨러별 후보 라벨까지
영구 보존하여 재현성, 추적성, 드리프트 감지를 제공한다. FastAPI 백엔드와 React SPA로
구성된 풀스택 구현이다.

설계 기준 문서는 논문 "Label-as-First-Class-Citizen: Design of a Data Pipeline for Weak
Supervision Learning"(KCC 2026)이며, 코드는 이 논문의 설계를 정본으로 따른다.

---

## 핵심 개념

기존 파이프라인에서 라벨은 단일 스칼라 컬럼으로 저장되어 "누가, 언제, 어떤 방식으로 이
라벨을 생성했는가"에 대한 정보가 유실된다. LLP는 라벨을 데이터 레이크의 일급 객체로
승격시켜 feature 데이터와 동일한 저장, 계층, 계보 인프라 위에서 관리한다.

### 라벨 3계층

| 계층 | 의미 | 저장 | 생성 주체 |
| --- | --- | --- | --- |
| L1 Candidate | 라벨러별 원시 후보 라벨 | Silver, append-only(수정/삭제 금지) | rule / llm / human 어댑터 |
| L2 Consensus | L1을 합의 정책으로 통합한 결과 | Gold | Fusion Engine |
| L3 Gold-Standard | 사람 검수를 통과한 고신뢰 라벨 | Gold(버전 이력 보존) | Human Reviewer |

여러 라벨러가 병렬로 실행되어 동일 샘플에 대해 복수의 L1이 생성되고 Silver 계층에 독립적으로
append된다. L2는 학습 데이터의 기본 라벨이며, L3는 라벨러 정확도 평가와 드리프트 감지의
앵커(anchor)로 활용된다.

### Label Object 스키마

모든 라벨러의 출력을 단일 스키마로 흡수한다. 이종 라벨러의 차이는 method와 method_ver
필드로 메타에 담긴다.

| 필드 | 설명 |
| --- | --- |
| value | 라벨 값(분류는 클래스, 회귀는 실수) |
| method | 라벨러 종류(rule / llm / human) |
| method_ver | 라벨러 버전 식별자(규칙 ID, 모델+프롬프트 해시, 검수자 ID) |
| confidence | 라벨러 신뢰도 [0, 1] |
| rationale | 라벨 근거(규칙명, LLM 설명 텍스트) |
| inputs_hash | 라벨 생성에 사용된 feature의 해시 |
| labeled_at | 라벨 생성 시각 |
| agreement | 다중 라벨러 raw 결과의 구조화 기록(L2 합의 시점에 채워짐) |

---

## 데이터 흐름

```
원천 데이터 -> feature -> 라벨러 N개 -> L1 후보(Silver, append-only)
                                          |
                              Fusion Engine(합의 정책)
                              +-----------+-----------+
                         값 일치 / 정책 충족        불일치
                              |                       |
                         L2 합의 라벨(Gold)    Human Review Queue
                                                      | 사람 검수
                                                 L3 검증 라벨(Gold)
                                                      |
         Dataset Builder <- (L2 / L3 / L3_PRIORITY) --+
         Drift Monitor(PSI / KL / anchor) · Gold Republish · Audit / Lineage
```

### Label Fusion Engine

정본 기본 정책은 confidence_gap(논문 알고리즘 1)이다.

- 값 일치(agree) 시 합의 라벨을 생성하고 flag를 agreed로 둔다.
- 불일치이면서 신뢰도 상위-차상위 격차가 임계값 θ를 초과하면 최고 신뢰도 라벨의 값을
  채택하고 flag를 soft_disagreement로 둔다.
- 격차가 θ 이하인 불일치는 Human Review Queue로 라우팅하고 L2를 생성하지 않는다.

추가로 majority_vote, confidence_weighted, rule_priority, human_priority, kappa_based,
custom_policy 정책을 선택할 수 있다. 검수 결과(L3)는 라벨러별 회귀 검증 신호로 audit에
재투입되어 라벨러가 점진적으로 개선되는 폐루프(closed loop)를 이룬다.

### Drift Monitor

- 동일 feature 분위수 구간 조건에서 L1 분포의 PSI와 KL 발산을 계산하여 상대적 변화를
  관찰한다. feature 분위수 식별자가 없으면 값 분포로 폴백한다.
- 소규모 L3 앵커 집합을 재점수하여 절대 정확도를 추적한다.
- 드리프트 지표가 임계값을 초과하면 상태가 단계적으로 상승하며(NORMAL, WARNING, CRITICAL,
  REPUBLISH_REQUIRED) 앵커 샘플을 재검수 큐로 지정한다.

---

## 기능 요약

- Label Object 저장: 모든 라벨러 출력을 단일 스키마로 append-only 저장. inputs_hash 또는
  method_ver 누락 시 422로 거부.
- Labeler Adapter: rule / llm / human 공통 인터페이스. LLM 파싱 실패는 격리되어
  파이프라인을 중단시키지 않는다.
- Fusion Engine: 합의 정책 7종. 불일치 시 검수 큐로 라우팅.
- Human Review에서 L3 생성: 검수 큐(PENDING, IN_PROGRESS, COMPLETED, REJECTED)를 거쳐
  L3 Gold 생성, 이전 활성 L3는 superseded 처리.
- Dataset Builder: L2 / L3 / L3_PRIORITY 레벨과 필터로 학습셋을 결합하고 재현 가능한
  manifest를 산출.
- Drift Monitor: 기간별 L1 분포 PSI / KL과 L3 앵커 정확도.
- Gold Republish: 정책 또는 버전 변경 시 Gold L2 재발행, 이전 버전 보존(rollback 지원).
- Audit 및 Lineage: 생성, 합의, 검수, 재발행, 데이터셋 과정을 audit_log에 기록.
- Dashboard: 라벨러별 지표, L2 합의율, 검수 대기 수, 드리프트 상태, Gold 버전 집계.

---

## 아키텍처

```
+------------+   +----------------------------------------------+   +---------------+
| Frontend   |   | Backend (FastAPI)                            |   | Storage       |
| React + TS |   |  API Gateway (REST /api/v1)                  |   | PostgreSQL    |
|            |-->|   labels · fusion · reviews · drift          |-->| (operational  |
| Dashboard  |   |   datasets · gold · audit · dashboard        |   |  + metadata)  |
| SampleView |   |  Services                                    |   |               |
| ReviewView |   |   LabelerAdapter(rule/llm/human)             |-->| Object Store  |
| DriftView  |   |   FusionEngine · DriftMonitor · ReviewSvc    |   | (MinIO/S3)    |
+------------+   |   DatasetBuilder · GoldRepublisher · Audit   |   | lake://       |
                 +----------------------------------------------+   +---------------+
```

### 기술 스택

| 영역 | 선택 |
| --- | --- |
| Backend | Python 3.11 · FastAPI · Pydantic v2 · SQLAlchemy 2 |
| 저장소 | SQLite(dev/test) -> PostgreSQL 15(production, 동일 모델) |
| 레이크 쿼리 | DuckDB(MVP) -> Trino/Spark(V1) |
| Frontend | React 18 · TypeScript · Vite · TanStack Query · Zustand · Tailwind · Recharts |
| 인증 | PyJWT(HS256), 비-프로덕션은 dev-mode X-Role 헤더 |

---

## 빠른 시작

### 백엔드

```bash
cd backend
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
LLP_AUTH_DEV_MODE=true ./.venv/bin/python -m pytest          # 212 tests
LLP_AUTH_DEV_MODE=true ./.venv/bin/python -m uvicorn app.main:app --reload
# http://127.0.0.1:8000/docs
```

인증은 기본적으로 fail-closed이다. 로컬 개발과 테스트에서는 `LLP_AUTH_DEV_MODE=true`로
실행하면 역할 헤더(예: `-H "X-Role: DataEngineer"`)로 동작한다. 프로덕션에서는
`LLP_AUTH_DEV_MODE`를 끄고 `LLP_JWT_SECRET`에 비-기본 시크릿을 반드시 설정해야 하며,
설정하지 않으면 부팅 시점에 실패한다.

### 프론트엔드

```bash
cd frontend
npm install
cp .env.example .env          # 백엔드가 다른 곳이면 VITE_PROXY_TARGET 조정
npm run dev                   # http://localhost:5173 (/api -> backend :8000 프록시)
```

---

## 데이터 레이크

> 구현 현황: MVP는 영구 데이터를 단일 SQLite(`backend/llp.db`)에 저장하고, 레이크 경로
> `lake://<layer>/...`는 재현용 URI 문자열로 DB 컬럼에만 기록한다(`docs/STORAGE.md`).
> 아래는 그 `lake://` URI를 실제 객체 스토어로 해석하는 **프로덕션 레이크 구성**으로,
> Object Store(MinIO/S3) + Apache Iceberg + DuckDB를 정본으로 한다. 표의 각 항목은
> [구현]과 [설계]로 구분한다.

### 설치 및 구성

MVP는 별도 레이크 설치 없이 동작한다(SQLite만 사용). 객체 스토어를 붙일 때는 MinIO를
S3 호환 엔드포인트로 띄우고 환경변수로 연결한다.

```bash
# 1) MinIO(S3 호환) 기동 — 로컬 단일 노드
docker run -d --name llp-lake -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=llp -e MINIO_ROOT_PASSWORD=llp-secret \
  -v llp-lake-data:/data quay.io/minio/minio server /data --console-address ":9001"

# 2) 계층별 버킷 생성 (mc = MinIO client)
mc alias set lake http://127.0.0.1:9000 llp llp-secret
mc mb lake/llp-bronze lake/llp-silver lake/llp-gold

# 3) DuckDB는 backend/requirements.txt 에 포함 — 레이크 조인 쿼리 엔진(httpfs+parquet)
```

레이크 연결 환경변수(`backend/.env` 또는 셸 export, prefix `LLP_`):

| 환경변수 | 예시 | 의미 |
| --- | --- | --- |
| `LLP_LAKE_ROOT` | `s3://llp` | 레이크 루트. `<root>-<layer>` 또는 `<root>/<layer>` 규칙으로 계층 버킷 매핑 |
| `LLP_LAKE_ENDPOINT` | `http://127.0.0.1:9000` | S3 호환 엔드포인트(MinIO) |
| `LLP_LAKE_ACCESS_KEY` | `llp` | 액세스 키 |
| `LLP_LAKE_SECRET_KEY` | `llp-secret` | 시크릿 키 |
| `LLP_LAKE_REGION` | `us-east-1` | 리전(S3 SDK 요구값) |
| `LLP_LAKE_FORMAT` | `iceberg` | 적재 포맷(`parquet` 또는 `iceberg`) |

> 현재 코드에서 사용하는 레이크 설정은 `LLP_LAKE_ROOT` 하나이며(`backend/app/config.py`의
> `Settings.lake_root`, 기본 `lake://`), 나머지 키는 객체 스토어 적재를 켤 때 추가되는
> [설계] 항목이다.

### 배치(계층 레이아웃)

레이크 경로 규칙은 `lake://<layer>/<table>/<partition>/...`이다.

```
s3://llp-bronze/                              [설계] 원천/수집 데이터(불변 랜딩 존)
  raw/{source}/dt=YYYY-MM-DD/part-*.parquet

s3://llp-silver/                              L1 후보 + 정제 feature
  labels_l1_candidate/dt=YYYY-MM-DD/method={rule|llm|human}/part-*.parquet
  features/{dataset}/dt=YYYY-MM-DD/part-*.parquet

s3://llp-gold/                                L2/L3 + dataset manifest
  labels_l2_consensus/version={gold_ver}/part-*.parquet
  labels_l3_gold/version={gold_ver}/part-*.parquet
  dataset_manifest/{dataset_id}/manifest.json
```

파티션 키는 수집일(`dt`)과 라벨러(`method`), Gold는 재발행 버전(`version`)이다. 이는
DB 테이블의 레이크 계층 매핑(`docs/STORAGE.md` §2.2)과 1:1로 대응한다.

### Bronze / Silver / Gold 격리

계층은 단순 디렉터리 prefix가 아니라 **버킷·권한·불변식 수준에서 격리**한다.

| 계층 | 버킷 | 쓰기 주체 | 접근 정책 | 불변식 |
| --- | --- | --- | --- | --- |
| Bronze | `llp-bronze` | 수집기(ingest)만 | 파이프라인 외부 read 차단 | 랜딩 후 불변(overwrite 금지) |
| Silver | `llp-silver` | LabelerAdapter / pipeline | DataEngineer write, MLEngineer read | **append-only**(수정·삭제 금지, 정정은 새 `run_id`로 재append 후 기존 row `SUPERSEDED`) |
| Gold | `llp-gold` | FusionEngine / ReviewSvc / GoldRepublisher | Admin write, Viewer read | **버전 보존**(L2/L3 재발행 시 이전 버전 유지, rollback 가능) |

격리 시행 방법:

- 버킷 분리 + IAM/버킷 정책으로 계층 간 교차 쓰기를 원천 차단(Bronze는 ingest 역할만,
  Gold는 Admin 역할만 write).
- Silver append-only는 객체 버전관리(S3 Versioning) + Iceberg `append` 전용 트랜잭션으로
  강제하고, Postgres에서는 트리거로 보강한다(MVP는 애플리케이션 계층에서 보장,
  `docs/STORAGE.md` §2.3).
- API 권한(`require_role`)과 레이크 정책을 이중으로 맞춰 코드 경로와 스토리지 경로가
  같은 RBAC를 따르게 한다.

### 데이터 이동 방법 및 함수

계층 간 이동은 임의 복사가 아니라 **승격(promotion) 트랜잭션**으로만 일어난다. 각 승격은
audit_log에 기록되고 lineage로 추적된다. 레이크 어댑터(`app/services/lake.py`, [설계])가
다음 함수를 노출한다.

| 이동 | 함수 | 트리거 | 동작 |
| --- | --- | --- | --- |
| Bronze→Silver | `ingest_features(source, dt) -> run_id` | 수집 배치 | 원천을 정제 feature로 적재, `inputs_hash` 산출 |
| →Silver(L1) | `write_l1_candidate(label_obj) -> label_id` | LabelerAdapter | L1 후보 append-only 적재(method 파티션) |
| Silver→Gold(L2) | `promote_l2(sample_ids, policy) -> gold_ver` | `POST /api/v1/fusion/run` | 합의 통과분만 Gold L2로 승격, 불일치는 검수 큐로 |
| Gold(L3) | `promote_l3(review_id) -> label_id` | `POST /api/v1/reviews/{id}/complete` | 검수 통과 L3 발행, 이전 활성 L3 `superseded` |
| Gold republish | `republish_gold(reason) -> gold_ver` | `POST /api/v1/gold/republish` | 정책/버전 변경 시 L2 재발행, 이전 버전 보존 |
| Gold→Dataset | `build_dataset(level, filters) -> manifest_uri` | `POST /api/v1/datasets/build` | L2/L3/L3_PRIORITY를 결합해 재현 가능한 manifest 산출 |

이동 규약:

- 모든 승격은 단방향(Bronze→Silver→Gold)이며 하위 계층을 역방향으로 수정하지 않는다.
- 승격은 멱등(idempotent)하게 설계한다 — 같은 `run_id`/입력 해시면 중복 적재하지 않는다.
- feature↔label 조인은 DuckDB(MVP) → Trino/Spark(V1)로 수행하며, 결과만 Gold에 쓴다.
- 현재 MVP에서 위 함수들의 효과는 SQLite 테이블 쓰기 + `lake://` URI 기록으로 구현되어
  있고, 객체 스토어 실제 입출력은 위 환경변수를 설정하면 활성화되는 [설계] 델타다.

---

## API 표면

권한 순서는 Admin, DataEngineer, MLEngineer, Reviewer, Viewer이다. 백엔드(require_role)와
프론트(ProtectedRoute / RoleGate)에서 이중으로 시행된다.

| Method | Path | 설명 | 최소 권한 |
| --- | --- | --- | --- |
| POST | /api/v1/labels/l1 | L1 라벨 저장 | DataEngineer |
| GET | /api/v1/labels/{l1,l2,l3}?sample_id= | 라벨 조회 | MLEngineer |
| POST | /api/v1/fusion/run | Fusion 배치 실행 | DataEngineer |
| POST, GET | /api/v1/reviews | 검수 등록 / 큐 조회 | DataEngineer / Reviewer |
| POST | /api/v1/reviews/{id}/complete | 검수 완료에서 L3 생성 | Reviewer |
| POST, GET | /api/v1/drift/run, /api/v1/drift/metrics | Drift 측정 / 조회 | DataEngineer / Viewer |
| POST | /api/v1/datasets/build | Dataset 생성 | MLEngineer |
| POST | /api/v1/gold/republish | Gold 재발행 | Admin |
| GET | /api/v1/audit/lineage?entity_id= | 계보 조회 | DataEngineer |
| GET | /api/v1/dashboard/metrics | 대시보드 집계 | Viewer |

---

## 화면

| 경로 | 화면 | 핵심 기능 |
| --- | --- | --- |
| /dashboard | Dashboard | 운영 지표 카드, 라벨러 비교, 드리프트 요약 |
| /samples/:sampleId | Sample Detail | L1 후보 비교, L2/L3 결과, 계보 |
| /reviews, /reviews/:id | Human Review | 검수 큐, 분할 검수 패널에서 L3 생성 |
| /drift | Drift Monitoring | PSI/KL/앵커 차트, Drift 실행, Gold Republish |
| /datasets/build | Dataset Builder | 버전/레벨/필터 폼에서 manifest 산출 |
| /fusion/run | Fusion 실행 | 정책/임계값 폼에서 합의 결과 카운트 |

---

## 성능과 보안

성능 최적화와 후속 보안 강화의 상세 내역은 docs/OPTIMIZATION_PLAN.md에 기록되어 있다.

성능

- 융합, 데이터셋, 드리프트 앵커 조회의 N+1을 배치 IN 쿼리로 제거했다. 읽기 쿼리 수가
  샘플 또는 앵커 수에 비례하지 않음을 회귀 테스트로 고정한다.
- 핵심 조회 경로에 복합 인덱스를 추가했다.
- 대시보드 집계를 단일 GROUP BY로 통합했다.
- 프로덕션 DB에 커넥션 풀(pool_size, max_overflow, pre_ping, recycle, timeout)을 설정했다.

보안

- JWT 처리를 PyJWT로 마이그레이션하고 알고리즘 allowlist를 명시한다.
- 인증 기본값을 fail-closed로 두고, 비-dev 환경에서 JWT 시크릿이 없으면 부팅을 거부한다.
- dataset 빌드 파라미터를 실행 가능한 SQL 문자열이 아닌 구조화 JSON으로 저장한다.
- 드리프트 검수 enqueue에 상한을 두고, 초과 시 무음 절단 대신 alert를 발생시킨다.

---

## 프로젝트 구조

```
llp/
  backend/      FastAPI 구현 (app/, tests/ 212 tests) — backend/README.md
  frontend/     React SPA (src/) — frontend/README.md
  design/       설계 PRD(백엔드/프론트/DB)와 정식 데이터 계약 — design/README.md
  docs/         FEATURE_GUIDE.md · VERIFICATION_REPORT.md · OPTIMIZATION_PLAN.md
  pdf_llp.md    원본 요구사항(PRD)
```

문서 안내

- design/README.md: 아키텍처, 기술 스택 결정, 정식 Label Object 스키마와 Enum의 단일
  진실 공급원(SSOT).
- docs/FEATURE_GUIDE.md: 기능별 상세 설명, 데이터 흐름, 사용 시나리오.
- docs/OPTIMIZATION_PLAN.md: 쿼리/프로그램 최적화 계획과 보안 후속 처리 내역.
- docs/VERIFICATION_REPORT.md: 구현 검증 및 잔여 갭.

---

## 범위와 한계

- 구현 완료: Label Object, L1 저장, rule/llm/human 어댑터, confidence_gap 기본 fusion과
  정책 7종, 검수 큐에서 L3 생성, Dataset Builder, Drift Monitor(PSI/KL/앵커), Gold
  Republish와 rollback, Audit Log, Dashboard.
- 프로덕션 델타(설계 문서화, 현재 구현 외): PostgreSQL 파티셔닝과 append-only 트리거,
  Alembic 마이그레이션, DuckDB/Trino 레이크 조인, Dagster 배치 오케스트레이션, OAuth2/JWT
  IdP 연동, JSONB GIN 인덱스.
