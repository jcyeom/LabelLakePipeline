// API request/response types — match backend app/domain/schemas.py exactly.
import type {
  DriftStatus,
  FusionPolicy,
  L1Status,
  L2Flag,
  L3Status,
  LabelLevel,
  LabelMethod,
  ReviewStatus,
} from '@/lib/enums'

// value is dict | str | float | int in the backend.
export type LabelValue = string | number | boolean | Record<string, unknown>
export type Rationale = string | Record<string, unknown> | null

// ----------------------------------------------------------------- Labels
export interface L1Create {
  sample_id: string
  feature_id: string
  feature_version: string
  value: LabelValue
  task_type: string
  method: LabelMethod
  method_ver: string
  confidence?: number | null
  rationale?: Rationale
  inputs_hash: string
  run_id: string
  agreement_group_id?: string | null
  metadata?: Record<string, unknown> | null
}

export interface L1CreateResponse {
  label_id: string
  status: L1Status
}

export interface L1Label {
  label_id: string
  method: LabelMethod
  method_ver: string
  value: LabelValue
  confidence: number | null
  rationale: Rationale
  feature_id: string | null
  feature_version: string | null
  inputs_hash: string | null
  run_id: string | null
  status: L1Status
  labeled_at: string | null
}

export interface L1ListResponse {
  sample_id: string
  labels: L1Label[]
}

export interface L2Label {
  consensus_label_id: string
  sample_id: string
  value: LabelValue
  confidence: number | null
  fusion_policy: string
  flag: L2Flag
  agreement_score: number | null
  // 다중 라벨러 raw 결과의 구조화 기록 (논문 표 1 `agreement`).
  agreement: Array<Record<string, unknown>> | null
  source_l1_ids: string[]
  fusion_reason: string | null
  label_version: string
}

export interface L3Label {
  gold_label_id: string
  sample_id: string
  value: LabelValue
  reviewer_id: string
  review_reason: string | null
  status: L3Status
  label_version: string
}

// ----------------------------------------------------------------- Fusion
export interface FusionRunRequest {
  sample_ids: string[]
  fusion_policy: FusionPolicy
  confidence_gap_threshold: number
  disagreement_threshold: number
  // 저신뢰 임계값 (기본 0.5). 선택 필드.
  low_confidence_threshold?: number
}

export interface FusionRunResponse {
  run_id: string
  created_l2_count: number
  human_review_count: number
  failed_count: number
}

// ----------------------------------------------------------------- Async runs
// 비동기 배치 실행 시 HTTP 202 즉시 응답 (fusion/drift/gold republish 공통).
export interface RunAccepted {
  run_id: string
  status: 'accepted'
  poll_url: string
}

export type RunStatus = 'RUNNING' | 'COMPLETED' | 'FAILED'

// GET /runs/{run_id} 폴링 응답. result 는 완료 시 기존 동기 응답 본문을 담는다.
export interface RunView {
  run_id: string
  run_type: string
  method: string | null
  method_ver: string | null
  status: RunStatus
  created_count: number
  failed_count: number
  params: Record<string, unknown>
  // 완료 시: FusionRunResponse | DriftRunResponse | GoldRepublishResponse.
  result: Record<string, unknown> | null
  error: string | null
  started_at: string
  finished_at: string | null
}

// ----------------------------------------------------------------- Reviews
export interface ReviewCreateRequest {
  sample_id: string
  reason: string
  priority: number
  l1_label_ids: string[]
}

export interface ReviewCreateResponse {
  review_id: string
  status: ReviewStatus
}

export interface Review {
  review_id: string
  sample_id: string
  reason: string
  priority: number
  l1_label_ids: string[]
  status: ReviewStatus
  assigned_to: string | null
  created_at: string
  completed_at: string | null
}

export interface ReviewListResponse {
  reviews: Review[]
}

export interface ReviewCompleteRequest {
  value: LabelValue
  reviewer_id: string
  review_reason?: string | null
  regenerate_l2: boolean
}

export interface ReviewCompleteResponse {
  gold_label_id: string
  status: ReviewStatus
}

// ----------------------------------------------------------------- Drift
export interface DriftRunRequest {
  method: LabelMethod
  method_ver: string
  baseline_window: string
  current_window: string
  metrics: string[]
}

export interface DriftRunResponse {
  metric_id: string
  psi: number | null
  kl_divergence: number | null
  anchor_accuracy: number | null
  // 기준 대비 앵커 정확도 하락폭 (선택). 백엔드 drift result.
  anchor_accuracy_drop?: number | null
  status: DriftStatus
}

export interface DriftMetric {
  metric_id: string
  method: string
  method_ver: string
  baseline_window: string
  current_window: string
  psi: number | null
  kl_divergence: number | null
  anchor_accuracy: number | null
  status: DriftStatus
  measured_at: string
}

// ----------------------------------------------------------------- Datasets
export interface DatasetBuildRequest {
  feature_version: string
  label_version: string
  label_level: LabelLevel
  task_type?: string | null
  confidence_min?: number | null
  exclude_disagreement: boolean
  label_method_filter?: LabelMethod[] | null
  include_rationale: boolean
}

export interface DatasetBuildResponse {
  dataset_id: string
  sample_count: number
  manifest_uri: string
}

// ----------------------------------------------------------------- Gold
export interface GoldRepublishRequest {
  trigger: string
  fusion_policy?: FusionPolicy | null
  sample_ids?: string[] | null
}

export interface GoldRepublishResponse {
  version_id: string
  run_id: string
  label_version: string
  republished_count: number
}

// ----------------------------------------------------------------- Audit
export interface AuditRecord {
  audit_id: string
  entity_type: string
  entity_id: string
  action: string
  actor: string | null
  run_id: string | null
  details: Record<string, unknown> | null
  created_at: string | null
}

export interface LineageResponse {
  entity_type: string
  entity_id: string
  records: AuditRecord[]
}

// ----------------------------------------------------------------- Dashboard
export interface DashboardMetrics {
  total_l1: number
  l1_by_method: Record<string, number>
  failure_rate_by_method: Record<string, number>
  avg_confidence_by_method: Record<string, number>
  l2_agreement_rate: number
  human_review_queue_size: number
  l3_count: number
  drift_status_by_method: Record<string, string>
  gold_label_version: string | null
}
