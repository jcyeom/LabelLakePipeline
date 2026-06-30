# LLP 저장소(DB / FS) 정리

> 백엔드 각 모듈이 사용하는 **데이터베이스(DB)** 와 **파일/레이크 저장소(FS)** 를 정리한 문서.
> 근거: `backend/app/config.py`, `backend/app/db.py`, `backend/app/models/orm.py`,
> `backend/app/services/*`, `backend/app/repositories/*`.

---

## 1. 한눈에 보기

| 구분 | MVP(현재 구현) | Production(설계, 미구현) |
| --- | --- | --- |
| **DB** | SQLite 파일 `backend/llp.db` (단일 파일) | PostgreSQL 15 (동일 SQLAlchemy 모델) |
| **FS / Lake** | **실체 파일 없음** — `lake://...` URI 문자열을 DB 컬럼에 **메타데이터로만 기록** | Object Store(MinIO/S3) + Parquet/Iceberg 실제 적재 |

> **핵심**: MVP에서 영구 데이터는 전부 **단일 SQLite DB**에 들어갑니다.
> Bronze/Silver/Gold "레이크 계층"은 **논리적 개념**이며, 레이크 경로(`lake://...`)는
> 실제 객체 스토어에 쓰이지 않고 **재현용 URI 문자열로 DB에 저장**됩니다.

---

## 2. 데이터베이스 (DB)

### 2.1 연결 / 수명주기

- 설정: `Settings.database_url` (기본 `sqlite+pysqlite:///./llp.db`).
  - 환경변수 `LLP_DATABASE_URL` 또는 `backend/.env` 로 재정의 (예: PostgreSQL DSN).
- 엔진/세션: `app/db.py` — SQLAlchemy 2 `engine` + `SessionLocal`.
  - SQLite일 때만 `check_same_thread=False` (TestClient 멀티스레드 공유용).
- 스키마 생성: 앱 startup 훅에서 `init_db()` → `Base.metadata.create_all()`.
  - 첫 서버 기동 시 `backend/llp.db` 파일과 9개 테이블이 자동 생성됨.
  - Production은 `create_all` 대신 **Alembic 마이그레이션**(db_design_prd 절차 11).
- 세션 주입: `get_session()` FastAPI 의존성 — 요청 단위 커밋/롤백/클로즈.

### 2.2 테이블 9종 (`app/models/orm.py`) — 레이크 계층 매핑

| 테이블 | 레이크 계층 | 역할 |
| --- | --- | --- |
| `labels_l1_candidate` | Silver | 라벨러별 L1 후보 라벨 (append-only) |
| `labels_l2_consensus` | Gold | Fusion 합의 결과 L2 |
| `labels_l3_gold` | Gold | 사람 검수 통과 L3 (버전 이력 보존) |
| `human_review_queue` | 운영/메타 | 불일치 샘플 검수 큐 |
| `label_drift_metrics` | 운영/메타 | PSI/KL/anchor 드리프트 측정 결과 |
| `dataset_manifest` | Gold | 학습 데이터셋 manifest (재현용 `manifest_uri` 포함) |
| `labeler_runs` | 운영/메타 | 라벨러/배치 실행 레지스트리 (`run_id`) |
| `audit_log` | 운영/메타 | 생성·합의·검수·재발행 감사 로그 |
| `gold_versions` | Gold | Gold 라벨 버전(재발행/rollback) |

### 2.3 append-only 불변식

- `labels_l1_candidate` 는 **수정·삭제 금지**. 정정은 새 `label_id`+새 `run_id`로
  재생성하고 기존 row 는 `SUPERSEDED`. (Postgres에서는 트리거로 강제, MVP는 애플리케이션 계층에서 보장.)

---

## 3. 파일/레이크 저장소 (FS)

### 3.1 현재 동작 (MVP)

- `Settings.lake_root` 기본값 `"lake://"` (환경변수 `LLP_LAKE_ROOT`).
- **실제 파일 입출력 없음.** 코드 전체에서 `open()`/`Path()`/`.parquet` 쓰기가 없으며,
  레이크 경로는 오직 **문자열로 DB에 기록**됩니다:
  - `app/repositories/datasets.py` → `manifest_uri = "lake://gold/dataset_manifest/{dataset_id}"`
  - `dataset_manifest.manifest_uri` 컬럼에 저장 → Dataset Build 응답으로 반환.
- 따라서 MVP에서 **디스크에 남는 유일한 산출물은 `backend/llp.db`** 입니다.

### 3.2 레이크 경로 규칙 (설계상 의미)

```
lake://<layer>/<table>/<partition>/...
  bronze/ ...   원천 데이터            (Object Store)
  silver/ ...   정제 feature + L1 후보  (Parquet/Iceberg)
  gold/   ...   L2/L3 + dataset_manifest
```

### 3.3 Production 델타 (미구현, 설계 문서화)

- L1 대용량 append → Object Store Parquet → Apache Iceberg (NFR-4).
- Dataset Builder 의 feature↔label 조인 → DuckDB(MVP 의존성 포함) → Trino/Spark.
- 위가 도입되면 `lake://` URI 가 실제 객체 스토어 경로로 해석됨.

---

## 4. 모듈(서비스)별 사용 저장소

> service → repository → table(DB) / lake(FS) 매핑. 모든 서비스는 SQLite DB만 사용하며,
> Dataset 만 추가로 `lake://` URI(메타데이터)를 기록합니다.

| 서비스 (`app/services/`) | 읽기/쓰기 테이블 | FS(lake) |
| --- | --- | --- |
| `pipeline.py` (L1 생성) | `labels_l1_candidate`, `audit_log` | — |
| `fusion.py` (L2 합의) | `labels_l1_candidate`, `labels_l2_consensus`, `human_review_queue`, `labeler_runs`, `gold_versions`, `audit_log` | — |
| `review.py` (검수→L3) | `human_review_queue`, `labels_l3_gold`, `labels_l2_consensus`, `labeler_runs`, `gold_versions`, `audit_log` | — |
| `dataset.py` (Dataset Builder) | `dataset_manifest`, `labels_l2_consensus`, `labels_l3_gold`, `audit_log` | `lake://gold/dataset_manifest/{id}` **(URI 기록만)** |
| `drift.py` (Drift Monitor) | `label_drift_metrics`, `labels_l1_candidate`, `labels_l3_gold`, `human_review_queue`, `labeler_runs`, `audit_log` | — |
| `gold.py` (Gold Republish) | `gold_versions`, `labels_l2_consensus`, `labeler_runs`, `audit_log` | — |
| `dashboard.py` (집계) | `labels_l1/l2/l3`, `human_review_queue`, `label_drift_metrics`, `gold_versions` (읽기 전용) | — |
| `labelers/{rule,llm,human}` | (DB 직접 접근 없음 — 결과를 pipeline 이 저장) | — |

저장소 계층(`app/repositories/`): `labels`, `reviews`, `runs`, `datasets`(+GoldVersion), `drift`, `audit`.

---

## 5. 초기화 / 정리

| 작업 | 방법 |
| --- | --- |
| DB·테이블 생성 | 서버 첫 기동 시 자동 (`init_db()`) |
| DB 초기화(리셋) | `backend/llp.db` 파일 삭제 후 재기동 (`*.db` 는 `.gitignore` 처리) |
| 다른 DB 사용 | `LLP_DATABASE_URL` 환경변수 또는 `backend/.env` 설정 |
| 레이크 루트 변경 | `LLP_LAKE_ROOT` (현재는 URI 문자열 prefix 로만 사용) |
