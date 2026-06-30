import type { ReactNode } from 'react'

interface MetricCardProps {
  title: string
  value: string | number
  subtitle?: string
  status?: 'normal' | 'warning' | 'critical'
  icon?: ReactNode
}

export function MetricCard({ title, value, subtitle, status = 'normal', icon }: MetricCardProps) {
  const borderColor = {
    normal: 'border-l-green-500',
    warning: 'border-l-amber-500',
    critical: 'border-l-red-500',
  }[status]
  return (
    <div className={`rounded-lg border bg-white p-4 shadow-sm border-l-4 ${borderColor}`}>
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">{title}</p>
        {icon}
      </div>
      <p className="mt-1 text-2xl font-bold text-gray-900">{value}</p>
      {subtitle && <p className="mt-1 text-xs text-gray-400">{subtitle}</p>}
    </div>
  )
}
