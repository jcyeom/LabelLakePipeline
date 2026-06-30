import type { ReactNode } from 'react'

export interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
  className?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  isLoading?: boolean
  onRowClick?: (row: T) => void
  emptyMessage?: string
  rowKey: (row: T) => string
  // 행별 추가 클래스 (예: 상태 강조). 선택.
  rowClassName?: (row: T) => string | undefined
}

// Lightweight generic table (frontend_design_prd DataTable 시그니처, TanStack Table 대체).
export function DataTable<T>({
  columns,
  data,
  isLoading,
  onRowClick,
  emptyMessage = '데이터 없음',
  rowKey,
  rowClassName,
}: DataTableProps<T>) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-white">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={`px-4 py-2 text-left font-medium text-gray-500 ${c.className ?? ''}`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {isLoading ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-8 text-center text-gray-400">
                불러오는 중…
              </td>
            </tr>
          ) : data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-8 text-center text-gray-400">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            data.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={
                  [onRowClick ? 'cursor-pointer hover:bg-gray-50' : '', rowClassName?.(row) ?? '']
                    .filter(Boolean)
                    .join(' ') || undefined
                }
              >
                {columns.map((c) => (
                  <td key={c.key} className={`px-4 py-2 text-gray-700 ${c.className ?? ''}`}>
                    {c.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
