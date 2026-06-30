// Typed API endpoint functions grouped by domain (frontend_design_prd api/*).
import { apiFetch } from '@/api/client'
import type {
  DashboardMetrics,
  DatasetBuildRequest,
  DatasetBuildResponse,
  DriftMetric,
  DriftRunRequest,
  FusionRunRequest,
  GoldRepublishRequest,
  L1ListResponse,
  L2Label,
  L3Label,
  LineageResponse,
  Review,
  RunAccepted,
  RunView,
  ReviewCompleteRequest,
  ReviewCompleteResponse,
  ReviewCreateRequest,
  ReviewCreateResponse,
  ReviewListResponse,
} from '@/types/api'

const q = (params: Record<string, string | undefined>) => {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') sp.set(k, v)
  const s = sp.toString()
  return s ? `?${s}` : ''
}

// ----------------------------------------------------------------- labels
export const labelsApi = {
  getL1: (sampleId: string) => apiFetch<L1ListResponse>(`/labels/l1${q({ sample_id: sampleId })}`),
  getL2: (sampleId: string) => apiFetch<L2Label>(`/labels/l2${q({ sample_id: sampleId })}`),
  getL3: (sampleId: string) => apiFetch<L3Label>(`/labels/l3${q({ sample_id: sampleId })}`),
}

// ----------------------------------------------------------------- fusion
export const fusionApi = {
  run: (body: FusionRunRequest) =>
    apiFetch<RunAccepted>('/fusion/run', { method: 'POST', body: JSON.stringify(body) }),
}

// ----------------------------------------------------------------- runs (폴링)
export const runsApi = {
  getRun: (runId: string) => apiFetch<RunView>(`/runs/${runId}`),
}

// ----------------------------------------------------------------- reviews
export const reviewsApi = {
  list: (status?: string) => apiFetch<ReviewListResponse>(`/reviews${q({ status })}`),
  create: (body: ReviewCreateRequest) =>
    apiFetch<ReviewCreateResponse>('/reviews', { method: 'POST', body: JSON.stringify(body) }),
  complete: (reviewId: string, body: ReviewCompleteRequest) =>
    apiFetch<ReviewCompleteResponse>(`/reviews/${reviewId}/complete`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
}

export type { Review }

// ----------------------------------------------------------------- drift
export const driftApi = {
  metrics: (method?: string) => apiFetch<DriftMetric[]>(`/drift/metrics${q({ method })}`),
  run: (body: DriftRunRequest) =>
    apiFetch<RunAccepted>('/drift/run', { method: 'POST', body: JSON.stringify(body) }),
}

// ----------------------------------------------------------------- datasets
export const datasetsApi = {
  build: (body: DatasetBuildRequest) =>
    apiFetch<DatasetBuildResponse>('/datasets/build', { method: 'POST', body: JSON.stringify(body) }),
}

// ----------------------------------------------------------------- gold
export const goldApi = {
  republish: (body: GoldRepublishRequest) =>
    apiFetch<RunAccepted>('/gold/republish', { method: 'POST', body: JSON.stringify(body) }),
}

// ----------------------------------------------------------------- audit
export const auditApi = {
  lineage: (entityId: string) => apiFetch<LineageResponse>(`/audit/lineage${q({ entity_id: entityId })}`),
}

// ----------------------------------------------------------------- dashboard
export const dashboardApi = {
  metrics: () => apiFetch<DashboardMetrics>('/dashboard/metrics'),
}
