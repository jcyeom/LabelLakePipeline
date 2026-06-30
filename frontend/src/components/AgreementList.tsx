// L2 `agreement` (다중 라벨러 raw 기록) 표시 컴포넌트.
// 항목: { label_id, method, method_ver, value, confidence }. null/빈 배열이면 렌더하지 않는다.
import { StatusBadge } from '@/components/StatusBadge'
import { ConfidenceBar } from '@/components/ConfidenceBar'
import { formatValue } from '@/lib/formatters'
import type { LabelValue } from '@/types/api'

interface AgreementEntry {
  label_id?: string
  method?: string
  method_ver?: string
  value?: LabelValue
  confidence?: number | null
}

export function AgreementList({ agreement }: { agreement: Array<Record<string, unknown>> | null }) {
  if (!agreement || agreement.length === 0) return null
  const entries = agreement as AgreementEntry[]

  return (
    <div className="sm:col-span-2">
      <dt className="text-xs font-medium uppercase tracking-wide text-gray-400">
        agreement (라벨러별 raw)
      </dt>
      <dd className="mt-1.5 overflow-x-auto rounded-md border">
        <table className="min-w-full divide-y divide-gray-100 text-xs">
          <thead className="bg-gray-50 text-gray-500">
            <tr>
              <th className="px-2 py-1 text-left font-medium">method</th>
              <th className="px-2 py-1 text-left font-medium">method_ver</th>
              <th className="px-2 py-1 text-left font-medium">value</th>
              <th className="px-2 py-1 text-left font-medium">confidence</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {entries.map((e, i) => (
              <tr key={e.label_id ?? i}>
                <td className="px-2 py-1">
                  {e.method ? <StatusBadge status={e.method} /> : '—'}
                </td>
                <td className="px-2 py-1 font-mono text-gray-500">{e.method_ver ?? '—'}</td>
                <td className="px-2 py-1 font-medium text-gray-800">{formatValue(e.value)}</td>
                <td className="px-2 py-1">
                  <ConfidenceBar value={e.confidence ?? null} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </dd>
    </div>
  )
}
