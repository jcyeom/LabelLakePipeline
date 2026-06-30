import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { labelsApi, reviewsApi } from '@/api/endpoints'
import type { L1Label, ReviewCompleteRequest, ReviewListResponse } from '@/types/api'
import { DataTable } from '@/components/DataTable'
import type { Column } from '@/components/DataTable'
import { StatusBadge } from '@/components/StatusBadge'
import { ConfidenceBar } from '@/components/ConfidenceBar'
import { RationaleViewer } from '@/components/RationaleViewer'
import { AgreementList } from '@/components/AgreementList'
import { RoleGate } from '@/components/RoleGate'
import { LoadingSkeleton, ErrorState } from '@/components/LoadingSkeleton'
import { STALE_TIME } from '@/lib/constants'
import { formatDateTime, formatPercent, formatValue } from '@/lib/formatters'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'

const l1Columns: Column<L1Label>[] = [
  { key: 'method', header: 'method', render: (l) => <StatusBadge status={l.method} /> },
  {
    key: 'value',
    header: 'value',
    render: (l) => <span className="font-medium text-gray-900">{formatValue(l.value)}</span>,
  },
  { key: 'confidence', header: 'confidence', render: (l) => <ConfidenceBar value={l.confidence} /> },
  {
    key: 'rationale',
    header: 'rationale',
    render: (l) => <RationaleViewer rationale={l.rationale} />,
  },
  { key: 'status', header: 'status', render: (l) => <StatusBadge status={l.status} /> },
]

export function ReviewDetailPage() {
  const { reviewId = '' } = useParams<{ reviewId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()
  const { userId } = useAuth()

  // Form state
  const [value, setValue] = useState('')
  const [reviewerId, setReviewerId] = useState(userId ?? '')
  const [reviewReason, setReviewReason] = useState('')
  const [regenerateL2, setRegenerateL2] = useState(true)
  // L3 생성은 되돌리기 어려우므로 완료 전 확인 단계.
  const [confirming, setConfirming] = useState(false)

  // Resolve the review by listing all and finding the matching id.
  const reviewsQuery = useQuery({
    queryKey: ['reviews', 'all'],
    queryFn: () => reviewsApi.list(),
    staleTime: STALE_TIME,
  })
  const review = reviewsQuery.data?.reviews.find((r) => r.review_id === reviewId)

  // Left panel: the sample's L1 candidate labels.
  const l1Query = useQuery({
    queryKey: ['labels', 'l1', review?.sample_id],
    queryFn: () => labelsApi.getL1(review!.sample_id),
    enabled: !!review?.sample_id,
    staleTime: STALE_TIME,
  })

  // L2 합의 결과(검수 화면에 표시). 없을 수 있으므로 retry 비활성.
  const l2Query = useQuery({
    queryKey: ['labels', 'l2', review?.sample_id],
    queryFn: () => labelsApi.getL2(review!.sample_id),
    enabled: !!review?.sample_id,
    retry: false,
    staleTime: STALE_TIME,
  })
  const l2 = l2Query.data

  const completeMutation = useMutation({
    mutationFn: ({ reviewId: id, body }: { reviewId: string; body: ReviewCompleteRequest }) =>
      reviewsApi.complete(id, body),
    onMutate: async ({ reviewId: id }) => {
      await queryClient.cancelQueries({ queryKey: ['reviews'] })
      const prevPending = queryClient.getQueryData<ReviewListResponse>(['reviews', 'PENDING'])
      queryClient.setQueryData<ReviewListResponse>(['reviews', 'PENDING'], (old) =>
        old ? { reviews: old.reviews.filter((r) => r.review_id !== id) } : old,
      )
      return { prevPending }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prevPending) {
        queryClient.setQueryData(['reviews', 'PENDING'], ctx.prevPending)
      }
      toast.error('검수 완료 처리 실패. 다시 시도해주세요.')
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['reviews'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard', 'metrics'] })
    },
    onSuccess: (res) => {
      toast.success(`L3 생성: ${res.gold_label_id}`)
      navigate('/reviews')
    },
  })

  if (reviewsQuery.isLoading) {
    return (
      <div className="mx-auto max-w-6xl space-y-4 p-6">
        <LoadingSkeleton rows={6} />
      </div>
    )
  }

  if (reviewsQuery.isError) {
    return (
      <div className="mx-auto max-w-6xl p-6">
        <ErrorState message="검수 정보를 불러오지 못했습니다." />
      </div>
    )
  }

  if (!review) {
    return (
      <div className="mx-auto max-w-6xl space-y-4 p-6">
        <ErrorState message="검수 항목을 찾을 수 없습니다." />
        <Link to="/reviews" className="text-sm text-brand-600 hover:underline">
          ← 검수 큐로 돌아가기
        </Link>
      </div>
    )
  }

  const handleComplete = () => {
    const body: ReviewCompleteRequest = {
      value,
      reviewer_id: reviewerId.trim() || (userId ?? ''),
      review_reason: reviewReason.trim() || null,
      regenerate_l2: regenerateL2,
    }
    completeMutation.mutate({ reviewId, body })
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5 p-6">
      <div className="flex items-center gap-3">
        <Link
          to="/reviews"
          className="rounded-md border px-2.5 py-1 text-sm text-gray-600 hover:bg-gray-50"
        >
          ← 큐
        </Link>
        <h1 className="text-xl font-bold text-gray-900">검수 상세</h1>
        <code className="rounded bg-gray-100 px-2 py-1 font-mono text-sm text-gray-700">
          {reviewId}
        </code>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        {/* LEFT — 검수 정보 패널 (60%) */}
        <div className="space-y-5 lg:col-span-3">
          <section className="rounded-lg border bg-white p-5">
            <h2 className="text-base font-semibold text-gray-900">검수 정보</h2>
            <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Meta label="review_id" value={<code className="font-mono text-xs">{review.review_id}</code>} />
              <Meta
                label="sample_id"
                value={
                  <RoleGate
                    minRole="MLEngineer"
                    fallback={<code className="font-mono text-xs">{review.sample_id}</code>}
                  >
                    <Link
                      to={`/samples/${review.sample_id}`}
                      className="font-mono text-xs text-brand-600 hover:underline"
                    >
                      {review.sample_id} ↗
                    </Link>
                  </RoleGate>
                }
              />
              <Meta label="사유" value={review.reason} />
              <Meta label="status" value={<StatusBadge status={review.status} />} />
              <Meta label="created_at" value={formatDateTime(review.created_at)} />
              <Meta label="L1 후보" value={`${review.l1_label_ids.length}개`} />
            </dl>
          </section>

          <section className="space-y-3">
            <h2 className="text-base font-semibold text-gray-900">L1 후보 라벨 비교</h2>
            {l1Query.isLoading ? (
              <LoadingSkeleton rows={4} />
            ) : l1Query.isError ? (
              <ErrorState message="L1 라벨을 불러오지 못했습니다." />
            ) : (
              <DataTable<L1Label>
                columns={l1Columns}
                data={l1Query.data?.labels ?? []}
                rowKey={(l) => l.label_id}
                emptyMessage="L1 후보 라벨 없음"
              />
            )}
          </section>

          {/* L2 합의 패널 */}
          <section className="rounded-lg border bg-white p-5">
            <h2 className="text-base font-semibold text-gray-900">L2 합의 결과</h2>
            {l2Query.isLoading ? (
              <div className="mt-3">
                <LoadingSkeleton rows={3} />
              </div>
            ) : l2 ? (
              <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Meta label="flag" value={<StatusBadge status={l2.flag} />} />
                <Meta
                  label="value"
                  value={<span className="font-medium text-gray-900">{formatValue(l2.value)}</span>}
                />
                <Meta label="agreement_score" value={formatPercent(l2.agreement_score)} />
                <Meta label="fusion_policy" value={l2.fusion_policy} />
                <Meta
                  label="fusion_reason"
                  value={<span className="text-gray-600">{l2.fusion_reason ?? '—'}</span>}
                />
                <AgreementList agreement={l2.agreement} />
              </dl>
            ) : (
              <p className="mt-3 rounded-md border border-dashed border-gray-300 bg-gray-50 p-4 text-center text-sm text-gray-400">
                L2 합의 라벨이 없습니다. (Fusion 미실행 또는 Human Review 대기)
              </p>
            )}
          </section>
        </div>

        {/* RIGHT — L3 입력 패널 (40%) */}
        <div className="lg:col-span-2">
          <section className="sticky top-6 rounded-lg border bg-white p-5">
            <h2 className="text-base font-semibold text-gray-900">최종 L3 라벨 입력</h2>

            <label className="mt-4 block text-sm font-medium text-gray-700">value</label>
            <input
              className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="최종 라벨 값"
            />

            <label className="mt-3 block text-sm font-medium text-gray-700">reviewer_id</label>
            <input
              className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
              value={reviewerId}
              onChange={(e) => setReviewerId(e.target.value)}
            />

            <label className="mt-3 block text-sm font-medium text-gray-700">검수 코멘트</label>
            <textarea
              className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
              rows={4}
              value={reviewReason}
              onChange={(e) => setReviewReason(e.target.value)}
              placeholder="review_reason"
            />

            <label className="mt-3 flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={regenerateL2}
                onChange={(e) => setRegenerateL2(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-brand-600"
              />
              L2 재생성 (regenerate_l2)
            </label>
            <p className="mt-1 text-xs text-gray-400">
              체크 시 이 검수 결과를 반영해 해당 샘플의 L2 합의 라벨을 다시 생성합니다.
            </p>

            <RoleGate
              minRole="Reviewer"
              fallback={
                <p className="mt-5 rounded-md border border-dashed border-gray-300 bg-gray-50 p-3 text-center text-xs text-gray-400">
                  Reviewer 권한이 필요합니다.
                </p>
              }
            >
              {!confirming ? (
                <button
                  onClick={() => setConfirming(true)}
                  disabled={completeMutation.isPending || !value.trim()}
                  className="mt-5 w-full rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-900 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  검수 완료
                </button>
              ) : (
                <div className="mt-5 space-y-2 rounded-md border border-amber-200 bg-amber-50 p-3">
                  <p className="text-xs font-medium text-amber-800">
                    L3 Gold 라벨을 생성합니다. 이 작업은 되돌리기 어렵습니다. 계속하시겠습니까?
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setConfirming(false)}
                      className="flex-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                    >
                      취소
                    </button>
                    <button
                      type="button"
                      onClick={handleComplete}
                      disabled={completeMutation.isPending || !value.trim()}
                      className="flex-1 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-900 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {completeMutation.isPending ? '처리 중…' : '확인 후 생성'}
                    </button>
                  </div>
                </div>
              )}
            </RoleGate>
          </section>
        </div>
      </div>
    </div>
  )
}

function Meta({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-medium uppercase tracking-wide text-gray-400">{label}</dt>
      <dd className="text-sm text-gray-800">{value}</dd>
    </div>
  )
}
