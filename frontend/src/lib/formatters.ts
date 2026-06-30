// Korean-locale formatters (frontend_design_prd i18n: ko 기본).
import type { LabelValue } from '@/types/api'

const dateFmt = new Intl.DateTimeFormat('ko-KR', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '-' : dateFmt.format(d)
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '-'
  return `${(value * 100).toFixed(digits)}%`
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return new Intl.NumberFormat('ko-KR').format(value)
}

export function formatFloat(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined) return '-'
  return value.toFixed(digits)
}

export function formatValue(value: LabelValue | null | undefined): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
