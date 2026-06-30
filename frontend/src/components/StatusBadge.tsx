import type { StatusVariant } from '@/lib/enums'

// Color rules per frontend_design_prd 상태 배지 색상 규칙.
const variantStyles: Record<string, string> = {
  // L1Status
  CREATED: 'bg-green-100 text-green-800',
  FAILED: 'bg-red-100 text-red-800',
  SKIPPED: 'bg-gray-100 text-gray-600',
  INVALID: 'bg-orange-100 text-orange-800',
  SUPERSEDED: 'bg-slate-100 text-slate-600',
  // L2Flag
  agreed: 'bg-blue-100 text-blue-800',
  soft_disagreement: 'bg-yellow-100 text-yellow-800',
  human_required: 'bg-purple-100 text-purple-800',
  // ReviewStatus
  PENDING: 'bg-yellow-100 text-yellow-800',
  IN_PROGRESS: 'bg-blue-100 text-blue-800',
  COMPLETED: 'bg-green-100 text-green-800',
  REJECTED: 'bg-red-100 text-red-800',
  // DriftStatus
  NORMAL: 'bg-green-100 text-green-800',
  WARNING: 'bg-amber-100 text-amber-800',
  CRITICAL: 'bg-red-100 text-red-800',
  REPUBLISH_REQUIRED: 'bg-red-200 text-red-900 font-semibold',
  // L3Status
  active: 'bg-green-100 text-green-800',
}

export function StatusBadge({ status }: { status: StatusVariant | string }) {
  const cls = variantStyles[status] ?? 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  )
}
