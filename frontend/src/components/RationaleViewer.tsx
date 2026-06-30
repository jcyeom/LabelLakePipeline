import type { Rationale } from '@/types/api'

export function RationaleViewer({ rationale }: { rationale: Rationale }) {
  if (!rationale) return <span className="text-xs text-gray-400">근거 없음</span>
  const text = typeof rationale === 'string' ? rationale : JSON.stringify(rationale, null, 2)
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-blue-600 hover:underline">근거 보기</summary>
      <pre className="mt-2 whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs text-gray-700">{text}</pre>
    </details>
  )
}
