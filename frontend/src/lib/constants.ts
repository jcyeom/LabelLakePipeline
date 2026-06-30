// Polling intervals (ms) — frontend_design_prd 폴링 전략.
export const POLLING_INTERVALS = {
  DASHBOARD: 60_000, // 60s
  REVIEWS: 30_000, // 30s
  DRIFT: 300_000, // 5min
} as const

// Drift thresholds (PRD §14.2) — for client-side reference lines on charts.
export const THRESHOLDS = {
  PSI_WARNING: 0.1,
  PSI_CRITICAL: 0.25,
  KL_WARNING: 0.05,
  KL_CRITICAL: 0.1,
} as const

export const STALE_TIME = 30_000
