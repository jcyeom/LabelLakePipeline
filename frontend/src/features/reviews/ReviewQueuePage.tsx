import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { reviewsApi } from '@/api/endpoints'
import type { Review } from '@/types/api'
import { REVIEW_STATUS } from '@/lib/enums'
import { DataTable } from '@/components/DataTable'
import type { Column } from '@/components/DataTable'
import { StatusBadge } from '@/components/StatusBadge'
import { ErrorState } from '@/components/LoadingSkeleton'
import { POLLING_INTERVALS } from '@/lib/constants'
import { formatDateTime } from '@/lib/formatters'

type Filter = (typeof REVIEW_STATUS)[number] | 'ALL'
const FILTERS: Filter[] = ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'ALL']

function priorityStars(p: number): string {
  const n = Math.max(0, Math.min(5, Math.round(p)))
  return '★'.repeat(n) + '☆'.repeat(5 - n)
}

const columns: Column<Review>[] = [
  {
    key: 'priority',
    header: '우선순위',
    render: (r) => (
      <span className="font-mono text-amber-500" title={`priority ${r.priority}`}>
        {priorityStars(r.priority)}
      </span>
    ),
  },
  {
    key: 'sample_id',
    header: 'sample_id',
    render: (r) => <code className="font-mono text-xs text-gray-700">{r.sample_id}</code>,
  },
  { key: 'reason', header: '사유', render: (r) => <span className="text-gray-700">{r.reason}</span> },
  {
    key: 'assigned_to',
    header: '담당자',
    render: (r) =>
      r.assigned_to ? (
        <span className="text-gray-700">{r.assigned_to}</span>
      ) : (
        <span className="text-xs text-gray-400">미배정</span>
      ),
  },
  { key: 'status', header: 'status', render: (r) => <StatusBadge status={r.status} /> },
  {
    key: 'l1_count',
    header: 'L1 후보',
    render: (r) => <span className="text-gray-600">{r.l1_label_ids.length}개</span>,
  },
  {
    key: 'created_at',
    header: 'created_at',
    render: (r) => <span className="text-xs text-gray-500">{formatDateTime(r.created_at)}</span>,
  },
]

type SortDir = 'desc' | 'asc'

export function ReviewQueuePage() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState<Filter>('PENDING')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const statusArg = filter === 'ALL' ? undefined : filter
  const query = useQuery({
    queryKey: ['reviews', filter],
    queryFn: () => reviewsApi.list(statusArg),
    refetchInterval: POLLING_INTERVALS.REVIEWS,
    staleTime: 15_000,
  })

  const reviews = [...(query.data?.reviews ?? [])].sort((a, b) =>
    sortDir === 'desc' ? b.priority - a.priority : a.priority - b.priority,
  )

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-gray-900">Human Review 큐</h1>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">대기: {reviews.length}건</span>
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-500">상태 필터</label>
            <select
              className="rounded-md border px-3 py-1.5 text-sm"
              value={filter}
              onChange={(e) => setFilter(e.target.value as Filter)}
            >
              {FILTERS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-500">정렬</label>
            <select
              className="rounded-md border px-3 py-1.5 text-sm"
              value={sortDir}
              onChange={(e) => setSortDir(e.target.value as SortDir)}
            >
              <option value="desc">우선순위 ↓ 높은 순</option>
              <option value="asc">우선순위 ↑ 낮은 순</option>
            </select>
          </div>
        </div>
      </div>

      {query.isError ? (
        <ErrorState message="검수 큐를 불러오지 못했습니다." />
      ) : (
        <DataTable<Review>
          columns={columns}
          data={reviews}
          isLoading={query.isLoading}
          onRowClick={(r) => navigate(`/reviews/${r.review_id}`)}
          rowKey={(r) => r.review_id}
          emptyMessage="대기 중인 검수 없음"
        />
      )}
    </div>
  )
}
