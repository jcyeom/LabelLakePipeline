# LLP 아키텍처 리뷰 — 백엔드 구조, FastAPI/REST 정합, 프론트 적합성

4개 차원(백엔드 구조/효율, FastAPI/REST 정합, 프론트-백엔드 계약, 프론트 UI 적합성)을
독립 분석한 종합이다. 결론부터: 구조는 견고하고 계약 동기화도 양호하다. 남은 핵심 과제는
운영 확장성(페이지네이션, 장기 배치의 동기 실행), 표면 완성도(CORS, 에러 응답 통일),
그리고 프론트 UI의 정보 표현 갭이다.

---

## 1. 종합 결론

잘 되어 있는 점

- router -> service -> repository 레이어링이 거의 모범적이다. 비즈니스 로직의 라우터 누수
  사실상 없음.
- N+1, 복합 인덱스, 대시보드 집계는 이전 최적화에서 이미 해소됨.
- 동기 def 라우터 + 동기 SQLAlchemy 세션 조합은 정합적이다(async 안티패턴 없음).
- 프론트-백엔드 enum 9종 전부 동기화, 호출되는 엔드포인트 전부 경로/메서드 일치.
- confidence_gap 정본 기본값과 L2 agreement 필드가 프론트 타입/enum/폼까지 반영됨.
- 상태코드-도메인예외 매핑(422/409/404/401/403)이 errors.py에 중앙화되어 정확.

핵심 과제(교차 확인된 항목)

- 페이지네이션 전무: audit/lineage, labels/search 등 단조 증가 컬렉션이 무제한 반환.
- 장기 배치(fusion/drift/republish)를 요청 스레드에서 동기 실행 -> 워커 점유/타임아웃.
- CORS 미설정 -> 다른 오리진 프론트의 브라우저 호출 차단.
- 에러 응답 이원화: 인증/검증(401/403/422)이 ErrorResponse 스키마를 따르지 않아 프론트가
  배열 detail(422) 파싱에 실패.
- 인증 기본값이 fail-closed로 바뀌어 프론트 dev 흐름(X-Role)이 백엔드 dev 모드에 의존.
- 프론트 UI가 일부 백엔드 정보(L2 agreement, label_method_filter 등)를 표현하지 못함.

---

## 2. 백엔드 구조와 효율

레이어링

- 분리는 모범적. 다만 Drift/Gold 서비스가 select(...) raw SQLAlchemy를 인라인 작성하여
  "서비스에 SQL" 누수(drift.py:84-154, gold.py:30). 레포 메서드로 이전 권장.
- audit/alerts 라우터가 ORM row를 수동 dict 변환(약한 책임 누수, Low).

FastAPI 관용구

- Depends DI, require_role 팩토리, 커스텀 LLPError 핸들러, Pydantic v2 모두 정석.
- 생성 POST의 status_code 불일치: labels/reviews는 201, fusion/drift/datasets/gold는
  기본 200. 생성은 201, 비동기 잡 트리거는 202로 통일 권장(Medium).
- on_event("startup")은 deprecated -> lifespan 컨텍스트로 교체(Low).

동기 vs 비동기

- 모든 라우터 동기 def + 동기 세션. 이벤트루프 블로킹은 없음.
- 그러나 장기 배치를 동기 실행하면 threadpool 워커를 점유 -> 동시 fusion/republish가
  워커풀을 고갈시켜 전체 API 지연(High).

효율적 수정 여지

- High: 페이지네이션 도입. 특히 무제한 get_l1_by_method_ver(labels.py:93).
- High: fusion/drift/gold republish를 잡 등록(202 + run_id)으로 전환. 이미 LabelerRun
  레지스트리가 있으므로 폴링 API만 추가하면 됨. BackgroundTasks(MVP) 또는 워커 큐.
- Medium: 트랜잭션 경계. get_session이 요청 단위 단일 트랜잭션이라 republish/fusion 전체가
  거대 트랜잭션 -> 락 보유 시간 김. 청크 커밋 고려.
- Medium: _previous_anchor_accuracy가 100행 로드 후 파이썬 필터 -> method_ver 필터 +
  LIMIT 1 레포 쿼리로.
- Low: 캐노니컬 키 직렬화(json.dumps sort_keys) 중복 -> util 헬퍼로 통합.

부트스트랩

- High: CORS 미들웨어 부재. 설정 가능한 allow_origins 추가 필요.
- create_app 팩토리, lru_cache 설정, fail-closed validator는 우수.

---

## 3. REST 정의 정합성

준수

- 컬렉션 복수형 일관. reviews 라우터(POST/GET 컬렉션/GET 단건)는 교과서적 REST.
- GET 전부 안전(상태변경 없음), append-only 설계라 PUT/DELETE 부재가 도메인과 정합.
- complete_review 재호출을 409로 방어 -> POST 재호출 안전성 모범.
- 상태코드 매핑 정확(422 검증, 409 충돌, 404 미존재, 401/403 분리).

개선 대상

- 반드시: 페이지네이션. audit/lineage, labels/search 우선(시간에 따라 단조 증가).
- 선택: 컬렉션 응답 봉투 불일치 통일. drift/metrics는 bare list라 향후 메타 추가 불가
  -> {items, count, page} 봉투화.
- 선택: 201 + Location 헤더(reviews는 저비용), datasets/build/gold/republish는 201 고려.
- 선택: gold/rollback을 PUT .../activate로 재모델링하여 재시도 안전성 계약화.
- 선택: gold/republish에 Idempotency-Key로 네트워크 재시도 중복 publish 차단.
- 선택: 에러 스키마 완전 일관화(전역 HTTPException/RequestValidationError 핸들러).
- 동사형 run/republish 경로는 동기 controller로서 정당 -> 과도한 순수주의 지양.

---

## 4. 프론트-백엔드 계약 적합성

정합 확인

- enum 9종 전부 일치(FusionPolicy의 confidence_gap 포함, 순서까지 동일).
- 호출되는 엔드포인트 13개 전부 경로/메서드/쿼리파라미터 일치.
- L2 agreement 필드 타입 정합, 응답 봉투(L1List/ReviewList/Dashboard) 정합.

불일치

- High: 인증 모드. 백엔드 기본 auth_dev_mode=False(fail-closed)인데 프론트 dev 로그인은
  X-Role만 보내고 토큰 미발급 -> 기본 설정에서 전부 401 후 로그인 리다이렉트 루프 가능.
  프론트 동작에 백엔드 LLP_AUTH_DEV_MODE=true 필요(호환성 메모/문서화 필요).
- High: 에러 봉투. 도메인 에러는 {error_code,message,details}로 정합하나, 인증(401/403)은
  {detail:string}, 검증(422)은 {detail:[...]} 배열 -> 프론트 client.ts가 배열 detail
  파싱 실패(일반 메시지 폴백).
- Medium: 프론트 타입 누락 — DriftRunResponse.anchor_accuracy_drop, FusionRunRequest의
  low_confidence_threshold, L1Create의 labeled_at.
- Low: 백엔드 노출 but 프론트 미사용 — POST /labels/l1, GET /labels/search,
  GET /reviews/{id}, POST /gold/rollback, GET /alerts.

---

## 5. 프론트 UI 기능 적합성

기능 커버리지는 약 85%. 전 기능에 화면이 존재하나 다음 표현 갭이 있다.

High

- L2 agreement 미표시: SampleDetailPage L2 섹션에서 agreement(다중 라벨러 raw 기록)를
  렌더링하지 않음. 타입/API는 이미 연결됨 -> 표시만 추가하면 됨.
- ReviewDetail에 L2 합의 맥락 없음: 검수자가 L1 후보만 보고 L3를 결정. L2 flag/value/
  agreement_score/fusion_reason 패널 추가 필요.
- DatasetBuilder의 label_method_filter가 항상 undefined로 하드코딩 -> 라벨러별 분리
  데이터셋 생성 불가.
- Drift 시계열 차트의 Line별 data 필터 방식이 X축 정렬을 깨뜨릴 수 있음(다중 method).
- REPUBLISH_REQUIRED 상태와 Gold Republish 행동 간 UI 연결 단절.
- Review value 입력이 자유 텍스트 -> 분류 태스크에서 오탈자 L3 생성 위험.

Medium/Low

- 샘플 목록 화면 없음(직접 URL/딥링크로만 도달). 사이드바 진입점 없음.
- ReviewQueue에 assigned_to 컬럼 없음 -> 다중 검수자 충돌 위험.
- ConfidenceBar/대시보드 임계값이 컴포넌트에 하드코딩(constants와 이원화).
- StatusBadge가 LabelMethod에는 색상 매핑이 없어 회색 고정.
- Fusion 결과에 agreed/soft_disagreement 분포 없음, 임계값 설명 없음.

Quick win(설계자 권고)

- SampleDetail에 L2 agreement 표시.
- ReviewDetail에 L2 합의 패널 추가.
- DatasetBuilder에 label_method_filter 체크박스.
- ReviewQueue에 assigned_to 컬럼.
- Drift 테이블에 REPUBLISH_REQUIRED 인라인 행동 CTA.

---

## 6. 우선순위 실행 묶음

P0 — 표면 완성도(저비용, 프론트 연동 즉시 효과, 무위험)

- CORS 미들웨어 추가(config 기반 allow_origins).
- 에러 응답 통일: 전역 HTTPException/RequestValidationError 핸들러로 401/403/422를
  ErrorResponse(error_code/message/details)로 정규화. 프론트 client.ts의 배열 detail 처리.
- 인증 호환성: dev 실행 안내(LLP_AUTH_DEV_MODE=true) 문서화. 선택적으로 프론트가
  토큰 흐름을 갖추거나 dev 헤더 흐름을 명시.
- 프론트 타입 보강: anchor_accuracy_drop, low_confidence_threshold 등 누락 필드.

P1 — 운영 확장성(중비용, 고임팩트)

- 페이지네이션: 공통 PageParams(limit/offset 또는 cursor) -> audit/lineage, labels/search,
  reviews, drift/metrics. 응답 봉투 통일(count/next_cursor).
- 장기 배치 비동기화: fusion/drift/gold republish를 202 + run_id 잡 등록으로 전환,
  LabelerRun 폴링 API 추가. BackgroundTasks(MVP) 또는 워커 큐.
- Drift/Gold 서비스의 인라인 select를 레포로 이전, 생성 POST status_code 정합(201/202).

P2 — UI 정보 표현/UX(프론트)

- L2 agreement 표시, ReviewDetail L2 패널, DatasetBuilder method 필터.
- ReviewQueue assigned_to, REPUBLISH_REQUIRED 인라인 CTA.
- Drift 시계열 차트 데이터 구조 정정, 임계값 상수화.
- 위험 작업(L3 생성/ republish) 확인 모달, Fusion 임계값 인라인 가이드.

---

## 6.5 구현 현황 (autopilot 실행)

P0 (백엔드 표면)

- CORS 미들웨어 + config.cors_allow_origins 추가, on_event startup → lifespan 전환.
- 에러 응답 통일: HTTPException(401/403)·RequestValidationError(422)를 ErrorResponse
  (error_code/message/details)로 정규화하는 전역 핸들러. 프론트 client.ts의 422 배열
  details 처리 보강. 회귀 테스트 4건(test_error_envelope).

P1 (백엔드 확장성)

- 페이지네이션: 공통 PageParams(limit/offset)로 audit/lineage·labels/search·reviews·
  drift/metrics 적용. 레포 메서드에 limit/offset 전파.
- 인라인 select 이전: Drift/Gold 서비스의 raw select를 DriftRepository/LabelRepository
  메서드로 이전. datasets/build status 201.
- 장기 배치 비동기화(BackgroundTasks): fusion/drift/gold republish가 202 + run_id 반환,
  GET /api/v1/runs/{run_id} 폴링. 결과는 run.result에 저장. 회귀 테스트 6건(test_async_runs).
- 프로덕션 정확성 보강(리뷰 반영): 배치 전용 커넥션 풀 분리(background_engine), 동시 배치
  상한(BoundedSemaphore), 실패는 fresh 세션 기록으로 stuck-RUNNING 방지, phantom
  republish run 제거(record_run 플래그), 폴링 엔드포인트 run_type별 권한 게이트.

P2 (프론트 UI)

- 타입/계약: RunAccepted·RunView 타입, 배치 API 반환 타입 교체, runsApi.getRun, 폴링
  훅(useRunJob). 누락 필드(anchor_accuracy_drop, low_confidence_threshold) 보강.
- 배치 페이지 폴링 UX(Fusion/Drift/GoldRepublish): 접수→처리 중→결과.
- UI 갭: SampleDetail L2 agreement 표시, ReviewDetail L2 합의 패널 + 완료 확인, Dataset
  Builder method 필터, ReviewQueue assigned_to, Drift REPUBLISH_REQUIRED 인라인 CTA +
  시계열 차트 정렬 정정.

검증: 백엔드 221 + 신규(error_envelope 4, async_runs 7, security/query 등) 통과, 프론트
tsc 0 에러 + vite build 성공.

남은 한계(문서화): BackgroundTasks는 동일 프로세스 실행이라 진정한 수평 확장·내구성에는
외부 워커 큐(Celery/RQ/arq)가 필요. 현재는 전용 풀 분리 + 동시성 상한으로 MVP 수준의
요청-경로 보호를 제공한다.

## 7. 한 줄 답변

"효율적 수정은 가능하다." 구조 변경 없이도 P0(CORS/에러통일/타입보강)는 즉시,
P1(페이지네이션/배치 비동기화)은 기존 LabelerRun 레지스트리와 레포 패턴을 재활용해
중간 비용으로, P2(UI 표현)는 이미 연결된 타입을 화면에 노출하는 수준의 quick win으로
달성된다.
