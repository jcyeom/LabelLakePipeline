// Shared enums mirroring backend app/domain/enums.py (design/README.md §5 SSOT).

export const ROLES = ['Viewer', 'Reviewer', 'MLEngineer', 'DataEngineer', 'Admin'] as const
export type Role = (typeof ROLES)[number]

// Privilege order (low → high), matches backend ROLE_ORDER.
export const ROLE_ORDER: Role[] = ['Viewer', 'Reviewer', 'MLEngineer', 'DataEngineer', 'Admin']

export function roleAtLeast(actual: Role | null, required: Role): boolean {
  if (!actual) return false
  return ROLE_ORDER.indexOf(actual) >= ROLE_ORDER.indexOf(required)
}

export const L1_STATUS = ['CREATED', 'FAILED', 'SKIPPED', 'INVALID', 'SUPERSEDED'] as const
export type L1Status = (typeof L1_STATUS)[number]

export const L2_FLAG = ['agreed', 'soft_disagreement', 'human_required'] as const
export type L2Flag = (typeof L2_FLAG)[number]

export const L3_STATUS = ['active', 'superseded'] as const
export type L3Status = (typeof L3_STATUS)[number]

export const REVIEW_STATUS = ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'REJECTED'] as const
export type ReviewStatus = (typeof REVIEW_STATUS)[number]

export const DRIFT_STATUS = ['NORMAL', 'WARNING', 'CRITICAL', 'REPUBLISH_REQUIRED'] as const
export type DriftStatus = (typeof DRIFT_STATUS)[number]

export const FUSION_POLICY = [
  'confidence_gap', // 정본 기본값 — 논문 알고리즘 1
  'majority_vote',
  'confidence_weighted',
  'rule_priority',
  'human_priority',
  'kappa_based',
  'custom_policy',
] as const
export type FusionPolicy = (typeof FUSION_POLICY)[number]

export const LABEL_LEVEL = ['L2', 'L3', 'L3_PRIORITY'] as const
export type LabelLevel = (typeof LABEL_LEVEL)[number]

export const LABEL_METHOD = ['rule', 'llm', 'human'] as const
export type LabelMethod = (typeof LABEL_METHOD)[number]

export type StatusVariant =
  | L1Status
  | L2Flag
  | ReviewStatus
  | DriftStatus
  | L3Status
