# LLP 최적화 계획 (프로그램 + DB 쿼리)

> 백엔드(`backend/app`) 전수 검토 기반. 우선순위 P0(고효과·저위험) → P2.
> MVP는 SQLite, 프로덕션은 PostgreSQL 15(동일 ORM). 각 항목에 SQLite/PG 적용 범위를 표기.
> **모든 변경은 기존 197 테스트 무회귀 + 쿼리 카운트 회귀 테스트로 검증한다.**

---

## 요약 — 핵심 병목

| ID | 위치 | 문제 | 영향 |
| --- | --- | --- | --- |
| A1 | `services/fusion.py` `FusionService.run` | 샘플마다 `get_l1_by_sample` 1쿼리 (N+1) | 융합/재발행 배치 핵심 경로 |
| A2 | `services/dataset.py` `build` | L2마다 `get_l1_by_ids`+`get_l3_by_sample` (최대 2N+1) | 데이터셋 생성 |
| A3 | `services/drift.py` `_anchor_accuracy` | 앵커마다 L1 조회 1쿼리 (N+1) | 드리프트 측정 |
| A4 | `services/drift.py` `_route_anchors_to_review` | 앵커마다 pending 체크 (N+1) | CRITICAL 드리프트 |
| A5 | `repositories/datasets.py` `count` | 전체 row 로드 후 `len()` | 대시보드/집계 |
| A6 | `repositories/drift.py` `latest_status_by_method` | 전체 메트릭 테이블 로드 | 대시보드(60초 폴링) |
| B  | ORM 전반 | 복합 인덱스 부재 (단일 컬럼만) | 모든 필터/정렬 쿼리 |
| C  | `db.py` | 커넥션 풀 설정 부재, 대시보드 캐시 없음 | 프로덕션 동시성 |

---

## A. DB 쿼리 최적화 (N+1 제거)

### A1. `FusionService.run` 의 샘플별 L1 조회 배치화  **[P0 · SQLite+PG]**
**현재** (`fusion.py`): `for sample_id in sample_ids: get_l1_by_sample(sample_id, active_only=False)` → M 샘플 = M 쿼리.

**개선**: 단일 `WHERE sample_id IN (:ids)` 로 전부 로드 후 파이썬에서 `sample_id`별로 그룹핑.
```python
# LabelRepository에 추가
def get_l1_by_samples(self, sample_ids: list[str], *, active_only=False) -> dict[str, list]:
    stmt = select(LabelL1Candidate).where(LabelL1Candidate.sample_id.in_(sample_ids))
    if active_only:
        stmt = stmt.where(LabelL1Candidate.status == L1Status.CREATED.value)
    out: dict[str, list] = defaultdict(list)
    for row in self.session.scalars(stmt.order_by(LabelL1Candidate.labeled_at)):
        out[row.sample_id].append(row)
    return out
```
`run()`은 루프 진입 전 1회 호출. 대량 `sample_ids`는 1000개 단위 청크로 `IN` 분할(파라미터 한계 회피).
**기대효과**: 쿼리 수 O(M) → O(1)(+청크). 재발행(`gold.republish`)이 전체 샘플을 융합하므로 복리 효과.

### A2. `DatasetBuilder.build` 의 L2별 조회 배치화  **[P0 · SQLite+PG]**
**현재**: L2마다 `get_l1_by_ids(source_l1_ids)` + (L3 레벨 시) `get_l3_by_sample`.

**개선**:
1. 모든 L2의 `source_l1_ids`를 평탄화 → 단일 `IN` 조회 → `{label_id: row}` 맵.
2. 모든 `sample_id` → 단일 조회로 활성 L3 맵 `{sample_id: l3}` 구성:
   ```python
   def get_active_l3_by_samples(self, sample_ids) -> dict[str, LabelL3Gold]:
       stmt = select(LabelL3Gold).where(
           LabelL3Gold.sample_id.in_(sample_ids),
           LabelL3Gold.status == L3Status.ACTIVE.value)
       return {r.sample_id: r for r in self.session.scalars(stmt)}
   ```
3. 루프는 맵 룩업만 수행.
**기대효과**: 최대 2N+1 → 3쿼리.

### A3. `DriftService._anchor_accuracy` 단일 쿼리화  **[P0 · SQLite+PG]**
**현재**: 활성 앵커마다 `(sample_id, method, window)` L1 조회. N 앵커 = N 쿼리. 또한 `value`만 필요한데 전체 ORM 객체 로드.

**개선**: 앵커 `sample_id` 목록으로 윈도우 내 L1을 한 번에 조회하고, 컬럼만 로드.
```python
anchor_vals = {a.sample_id: a.value for a in anchors}
rows = self.session.execute(
    select(LabelL1Candidate.sample_id, LabelL1Candidate.value, LabelL1Candidate.labeled_at)
    .where(LabelL1Candidate.sample_id.in_(anchor_vals),
           LabelL1Candidate.method == method,
           LabelL1Candidate.labeled_at >= start, LabelL1Candidate.labeled_at < end)
    .order_by(LabelL1Candidate.labeled_at))
# 파이썬에서 sample_id별 "마지막" 값 채택 후 anchor와 비교
```
**기대효과**: N+1 → 1쿼리 + 컬럼-only 로드(메모리↓).

### A4. 드리프트 앵커 재검수 pending 체크 배치화  **[P1 · SQLite+PG]**
**현재** `_route_anchors_to_review`: 앵커마다 `pending_for_sample`.
**개선**: 활성 앵커 `sample_id` 전체에 대해 PENDING/IN_PROGRESS 리뷰를 1쿼리로 조회 → `set`으로 보유. 신규만 생성. 생성은 `add_all`로 일괄.

### A5. `DatasetRepository.count` 집계 쿼리화  **[P0 · SQLite+PG]**
**현재**: `len(list(scalars(select(DatasetManifest))))` — 전체 로드.
**개선**: `select(func.count()).select_from(DatasetManifest)`.

### A6. `DriftRepository.latest_status_by_method` 윈도우/그룹 집계  **[P1]**
**현재**: 전체 `label_drift_metrics`를 measured_at desc로 로드 후 메서드별 첫 행만 사용.
**개선**:
- **PG**: `DISTINCT ON (method) ... ORDER BY method, measured_at DESC`.
- **SQLite**: 메서드별 `MAX(measured_at)` 서브쿼리 조인, 또는 메서드 목록(소수)별 `limit(1)` 조회.
- 공통: `(method, measured_at)` 인덱스(B) 전제.

---

## B. 인덱스 설계 (복합/부분)

현재 ORM은 **단일 컬럼 인덱스**만 있음(`sample_id`, `method`, `inputs_hash`, `run_id` 등). 실제 쿼리는 복합 조건/정렬이라 복합 인덱스가 필요. **PG는 Alembic 마이그레이션, SQLite는 `Index()` 선언**으로 동시 적용.

| 테이블 | 쿼리 패턴(출처) | 추가 인덱스 |
| --- | --- | --- |
| `labels_l1_candidate` | 드리프트 `(method, method_ver, labeled_at)` | `ix_l1_method_ver_time (method, method_ver, labeled_at)` |
| `labels_l1_candidate` | `get_l1_by_sample(active_only)` `(sample_id, status)` | `ix_l1_sample_status (sample_id, status)` |
| `labels_l2_consensus` | `get_l2_by_sample` `(sample_id, created_at DESC)` | `ix_l2_sample_created (sample_id, created_at)` |
| `labels_l3_gold` | `get_l3_by_sample` `(sample_id, status)` | `ix_l3_sample_status (sample_id, status)` |
| `human_review_queue` | `pending_for_sample` `(sample_id, status)`, `list` 정렬 `(priority DESC, created_at)` | `ix_review_sample_status`, `ix_review_priority_created` |
| `label_drift_metrics` | `list`/`latest` `(method, measured_at DESC)` | `ix_drift_method_time` |
| `gold_versions` | `active()` `WHERE is_active=1` | **PG 부분 인덱스** `WHERE is_active = true` |
| `audit_log` | `by_entity (entity_type, entity_id)` 정렬 created_at | `ix_audit_entity (entity_type, entity_id, created_at)` |

**PG 전용 추가**
- **JSONB + GIN**: `value`/`rationale`/`agreement`를 `JSONB`로 두고, 라벨 값/근거 검색이 생기면 GIN 인덱스. (현재 generic `JSON` → PG에서 `JSONB`로 매핑하도록 타입 분기.)
- **부분 인덱스**: `labels_l3_gold (sample_id) WHERE status='active'`, `gold_versions WHERE is_active`.
- **파티셔닝**: `labels_l1_candidate`는 `labeled_at` RANGE 파티션(이미 `db_design_prd`에 설계됨) — 드리프트 윈도우 쿼리가 파티션 프루닝 수혜.

> ⚠️ 인덱스는 append 비용을 약간 올림. L1은 append-only 대량 테이블이므로 **드리프트에 실제 쓰이는 복합 인덱스만** 추가(과인덱싱 금지).

---

## C. 엔진 / 인프라 / 캐싱

### C1. 커넥션 풀 설정 (PG)  **[P1 · PG]**
`db.py`의 `create_engine`에 풀 파라미터 부재 → 프로덕션 동시성에서 기본값 한계.
```python
engine = create_engine(url, pool_size=10, max_overflow=20,
                       pool_pre_ping=True, pool_recycle=1800, future=True)
```
SQLite는 무시(단일 파일). 환경변수(`LLP_DB_POOL_SIZE` 등)로 노출.

### C2. 대시보드 집계 캐싱/통합  **[P1]**
`DashboardService.metrics`는 요청당 ~8개 집계 쿼리, 프론트가 60초 폴링. 
- 단기: 인덱스(B)로 각 집계 비용 최소화 + `count_l1_by_method`/`failed_by_method`를 **1쿼리로 통합**(`GROUP BY method` + 조건부 집계 `SUM(CASE WHEN status='FAILED' ...)`).
- 중기: 짧은 TTL(예: 15초) 인메모리 캐시 또는 머티리얼라이즈드 뷰(PG)로 폴링 부하 흡수.

### C3. L1 append 경로 일괄 삽입  **[P2]**
`pipeline.run_sample`은 어댑터마다 `create_l1` + audit `record`(flush 2회). 대량 적재 시 `add_all` + 단일 flush, audit는 배치 기록으로 라운드트립 절감.

---

## D. 프로그램 마이크로 최적화

- **D1** `fusion._key`/드리프트의 JSON 직렬화: 라벨당 1회 계산해 재사용(드리프트 앵커 비교 루프에서 anchor.value 반복 직렬화 제거). **[P2]**
- **D2** 값/카운트만 필요한 경로는 `select(col, ...)`로 **컬럼-only 로드**(전체 ORM 인스턴스화 회피): 드리프트 분포 집계(`value`만), 앵커 비교. **[P1, A3와 함께]**
- **D3** `expire_on_commit=False`는 이미 설정됨(재조회 방지) — 유지. `selectinload`는 관계 매핑이 없어 비해당(배열은 JSON). 배치는 위 IN-쿼리 패턴으로 수동 처리.

---

## E. 검증 전략 (필수)

1. **쿼리 카운트 회귀 테스트**: SQLAlchemy `event.listen(engine, "before_cursor_execute", ...)`로 쿼리 수 카운트하는 fixture 추가. A1~A4에 대해 "N 샘플 융합 시 쿼리 수가 상수에 가까움"을 단언(N+1 재발 방지).
2. **무회귀**: 기존 197 + 신규 테스트 그린.
3. **마이크로 벤치**: 시드 스크립트로 L1 50k/L2 10k/앵커 500 규모 생성 후 융합·드리프트·데이터셋·대시보드 wall-clock 측정(전후 비교 표).
4. **PG 실측**: 복합 인덱스 적용 전후 `EXPLAIN (ANALYZE, BUFFERS)`로 시퀀셜 스캔 → 인덱스 스캔 확인.

---

## 권장 실행 순서 (반복 단위)

1. **반복 1 (P0, 위험 낮음·효과 큼)**: A1·A2·A3·A5 + E1 쿼리 카운트 fixture. (코드만, 스키마 무변경)
2. **반복 2 (인덱스)**: B 복합 인덱스(SQLite `Index()` + PG Alembic) + A6·D2. EXPLAIN 검증.
3. **반복 3 (인프라)**: C1 풀 설정, C2 대시보드 집계 통합/캐시, A4.
4. **반복 4 (정리)**: C3·D1 마이크로 + 벤치 리포트(`docs/`)로 전후 수치 기록.

각 반복은 독립 PR로 분리하고, **반복 1~2만으로 배치 경로의 쿼리 수가 자릿수 단위로 감소**하는 것이 목표.

---

## 구현 현황 (autopilot 실행 결과)

| 항목 | 상태 | 비고 |
| --- | --- | --- |
| A1 융합 N+1 | ✅ | `get_l1_by_samples` 배치, `FusionService.run` 1회 로드 |
| A2 데이터셋 N+1 | ✅ | source L1 flatten IN + `get_active_l3_by_samples` 배치 prefetch |
| A3 드리프트 앵커 N+1 | ✅ | 단일 IN + 컬럼-only(last-wins) |
| A4 앵커 재검수 배치 | ✅ | `pending_sample_ids` 배치 체크 |
| A5 `count` 집계화 | ✅ | `func.count()` |
| A6 `latest_status_by_method` | ✅ | MAX 서브쿼리 조인 + 결정적 tie-break |
| B 복합 인덱스 | ✅ | `__table_args__` 7테이블(SQLite+PG `create_all`). PG 부분/JSONB/파티션은 Alembic 델타 |
| C1 커넥션 풀 | ✅ | `pool_size/max_overflow/pre_ping/recycle/timeout`(PG only) |
| C2 대시보드 집계 통합 | ✅ | 단일 GROUP BY로 total/failed/total_l1 |
| C3 append 일괄 삽입 | ⏸ 보류 | P2, 후속 |
| D1 `_key` 재사용 | 부분 | drift `import json` 모듈화, 앵커 비교 1회 직렬화 |
| E 검증 | ✅ | 쿼리 카운트 회귀 테스트 7건, 전체 204 passed |

검증: architect APPROVE(동작 동치 보존), code-reviewer APPROVE. 정리 반영(dead `count_l1*` 제거, import 정렬, tie-break 결정성, `pool_timeout`).

## 보안 후속 처리 완료 (security-reviewer 발견 → 반영)

> 최적화 변경 자체는 보안상 clean(파라미터 바인딩 정상, SQL 인젝션 없음). 추가로 검토에서 드러난 **기존 코드**의 이슈를 후속 반영했다.

| 이슈 | 상태 | 반영 |
| --- | --- | --- |
| **[High] `python-jose==3.3.0`** (CVE-2024-33663/33664) | ✅ | `PyJWT[crypto]==2.10.1`로 마이그레이션(`requirements.txt`, `app/api/deps.py`). alg 명시 allowlist 유지 |
| **[High] fail-open 기본 인증** | ✅ | `auth_dev_mode` 기본 **False**, `jwt_secret` 기본 제거, 비-dev에서 시크릿 미설정 시 부팅 거부 validator(`app/config.py`). 테스트는 `LLP_AUTH_DEV_MODE=true` 강제(`conftest.py`) |
| **[Medium] `dataset.build_query` SQL형 문자열** | ✅ | 구조화 JSON(`sort_keys`, 비실행) 저장(`app/services/dataset.py`) |
| **[Medium] 무제한 검수 enqueue 증폭** | ✅ | `drift_max_review_enqueue` 상한 + 초과 시 alert(무음 절단 금지)(`app/services/drift.py`) |

검증: 보안 회귀 테스트 8건 추가(`tests/test_security.py`) — PyJWT 디코딩/위조 거부, fail-closed validator, JSON build_query, enqueue 상한+alert. 전체 **212 passed**.

남은 후속(선택): drift `_anchor_accuracy`/dataset 읽기 루프의 상한·페이지네이션은 데이터 규모 정책에 따라 별도 결정.
