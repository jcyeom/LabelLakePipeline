import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { fusionApi } from '@/api/endpoints'
import type { FusionRunRequest, FusionRunResponse, RunAccepted } from '@/types/api'
import { FUSION_POLICY } from '@/lib/enums'
import type { FusionPolicy } from '@/lib/enums'
import { StatusBadge } from '@/components/StatusBadge'
import { ErrorState } from '@/components/LoadingSkeleton'
import { useToast } from '@/hooks/useToast'
import { formatNumber } from '@/lib/formatters'
import { useRunJob } from '@/hooks/useRunJob'

interface FormState {
  sample_ids_raw: string
  fusion_policy: FusionPolicy
  confidence_gap_threshold: number
  disagreement_threshold: number
  low_confidence_threshold: number
}

const INITIAL: FormState = {
  sample_ids_raw: '',
  fusion_policy: 'confidence_gap',
  confidence_gap_threshold: 0.15,
  disagreement_threshold: 0.4,
  low_confidence_threshold: 0.5,
}

function parseSampleIds(raw: string): string[] {
  return raw
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
}

const POLICY_LABELS: Record<FusionPolicy, string> = {
  confidence_gap: 'confidence_gap — 알고리즘 1 (정본 기본)',
  majority_vote: 'majority_vote — 다수결',
  confidence_weighted: 'confidence_weighted — 신뢰도 가중',
  rule_priority: 'rule_priority — 규칙 우선',
  human_priority: 'human_priority — 인간 우선',
  kappa_based: 'kappa_based — Kappa 기반',
  custom_policy: 'custom_policy — 커스텀',
}

export function FusionRunPage() {
  const toast = useToast()
  const [form, setForm] = useState<FormState>(INITIAL)
  const [runId, setRunId] = useState<string | null>(null)

  const job = useRunJob(runId)

  const mutation = useMutation<RunAccepted, Error, FusionRunRequest>({
    mutationFn: (body) => fusionApi.run(body),
    onSuccess: (data) => {
      setRunId(data.run_id)
      toast.success('Fusion 실행이 접수되었습니다. 처리 중...')
    },
    onError: (err) => {
      toast.error(err.message)
    },
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()

    const ids = parseSampleIds(form.sample_ids_raw)

    if (ids.length === 0) {
      toast.error('sample_ids를 입력해주세요.')
      return
    }

    if (ids.length > 50) {
      const confirmed = window.confirm(
        `${formatNumber(ids.length)}개의 sample_id에 Fusion을 실행합니다. 계속하시겠습니까?`,
      )
      if (!confirmed) return
    }

    setRunId(null)
    const body: FusionRunRequest = {
      sample_ids: ids,
      fusion_policy: form.fusion_policy,
      confidence_gap_threshold: form.confidence_gap_threshold,
      disagreement_threshold: form.disagreement_threshold,
      low_confidence_threshold: form.low_confidence_threshold,
    }
    mutation.mutate(body)
  }

  // 접수 직후~폴링 중 모두 "처리 중" 으로 표시.
  const isLoading = mutation.isPending || job.isPolling
  // 완료된 run 의 result 를 기존 결과 카드가 읽도록 매핑.
  const result =
    job.isCompleted && job.run?.result
      ? (job.run.result as unknown as FusionRunResponse)
      : undefined
  const showResult = job.isCompleted && !!result
  const runError = mutation.isError
    ? mutation.error.message
    : job.isFailed
      ? (job.run?.error ?? '실행 중 오류가 발생했습니다.')
      : job.isError
        ? (job.error?.message ?? '폴링 중 오류가 발생했습니다.')
        : null

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">Fusion 실행</h1>
        <p className="mt-1 text-sm text-gray-500">
          Label Fusion Engine을 수동으로 트리거합니다. (FR-4)
        </p>
      </div>

      <div className="space-y-6 max-w-2xl">
        {/* Fusion Config Form */}
        <div className="rounded-lg border bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-sm font-semibold text-gray-700">Fusion 실행 설정</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* sample_ids */}
            <div>
              <label className="block text-sm font-medium text-gray-700">
                sample_ids <span className="text-red-500">*</span>{' '}
                <span className="text-xs text-gray-400">(콤마 또는 줄바꿈으로 구분)</span>
              </label>
              <textarea
                className="mt-1 w-full rounded border px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 resize-y"
                rows={4}
                placeholder={'sample-001, sample-002\nsample-003'}
                value={form.sample_ids_raw}
                onChange={(e) => setForm((f) => ({ ...f, sample_ids_raw: e.target.value }))}
                disabled={isLoading}
              />
              {form.sample_ids_raw.trim() !== '' && (
                <p className="mt-1 text-xs text-gray-500">
                  {parseSampleIds(form.sample_ids_raw).length}개 입력됨
                </p>
              )}
            </div>

            {/* fusion_policy */}
            <div>
              <label className="block text-sm font-medium text-gray-700">fusion_policy</label>
              <select
                className="mt-1 w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                value={form.fusion_policy}
                onChange={(e) =>
                  setForm((f) => ({ ...f, fusion_policy: e.target.value as FusionPolicy }))
                }
                disabled={isLoading}
              >
                {FUSION_POLICY.map((p) => (
                  <option key={p} value={p}>
                    {POLICY_LABELS[p]}
                  </option>
                ))}
              </select>
            </div>

            {/* confidence_gap_threshold */}
            <div>
              <label className="block text-sm font-medium text-gray-700">
                confidence_gap_threshold
              </label>
              <p className="mt-0.5 text-xs text-gray-400">
                상위 두 후보의 신뢰도 차이가 이 값보다 작으면 합의가 모호한 것으로 보고 검수 대상으로 분류합니다.
              </p>
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                className="mt-1 w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                value={form.confidence_gap_threshold}
                onChange={(e) =>
                  setForm((f) => ({ ...f, confidence_gap_threshold: Number(e.target.value) }))
                }
                disabled={isLoading}
              />
            </div>

            {/* disagreement_threshold */}
            <div>
              <label className="block text-sm font-medium text-gray-700">
                disagreement_threshold
              </label>
              <p className="mt-0.5 text-xs text-gray-400">
                라벨러 간 불일치 비율이 이 값을 넘으면 자동 합의 대신 Human Review 로 보냅니다.
              </p>
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                className="mt-1 w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                value={form.disagreement_threshold}
                onChange={(e) =>
                  setForm((f) => ({ ...f, disagreement_threshold: Number(e.target.value) }))
                }
                disabled={isLoading}
              />
            </div>

            {/* low_confidence_threshold */}
            <div>
              <label className="block text-sm font-medium text-gray-700">
                low_confidence_threshold{' '}
                <span className="text-xs text-gray-400">(선택, 기본 0.5)</span>
              </label>
              <p className="mt-0.5 text-xs text-gray-400">
                합의 신뢰도가 이 값보다 낮으면 저신뢰로 표시되어 검수 우선순위가 올라갑니다.
              </p>
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                className="mt-1 w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                value={form.low_confidence_threshold}
                onChange={(e) =>
                  setForm((f) => ({ ...f, low_confidence_threshold: Number(e.target.value) }))
                }
                disabled={isLoading}
              />
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full rounded bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isLoading ? 'Fusion 실행 중...' : 'Fusion 실행'}
            </button>
          </form>
        </div>

        {/* Error State */}
        {runError && <ErrorState message={`Fusion 실패: ${runError}`} />}

        {/* Polling State */}
        {isLoading && (
          <div className="flex items-center gap-3 rounded-lg border border-brand-200 bg-brand-50 p-4 text-sm text-brand-700">
            <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
            <span>
              Fusion 처리 중입니다…
              {runId && <span className="ml-2 font-mono text-xs text-brand-500">run_id: {runId}</span>}
            </span>
          </div>
        )}

        {/* Result Card */}
        <div
          className={`rounded-lg border p-6 shadow-sm transition-colors ${
            showResult ? 'bg-white' : 'bg-gray-50'
          }`}
        >
          <h2 className="mb-3 text-sm font-semibold text-gray-700">실행 결과</h2>
          {showResult && result ? (
            <div className="space-y-4">
              <div>
                <dt className="text-xs font-medium text-gray-500">run_id</dt>
                <dd className="mt-0.5 text-sm font-mono text-gray-900">{result.run_id}</dd>
              </div>
              <div className="grid grid-cols-3 gap-4">
                {/* L2 created */}
                <div className="rounded-lg border bg-green-50 p-3">
                  <p className="text-xs font-medium text-gray-500">L2 생성 수</p>
                  <p className="mt-1 text-xl font-bold text-green-700">
                    {formatNumber(result.created_l2_count)}
                  </p>
                </div>
                {/* Human review */}
                <div
                  className={`rounded-lg border p-3 ${
                    result.human_review_count > 0 ? 'bg-amber-50' : 'bg-gray-50'
                  }`}
                >
                  <p className="text-xs font-medium text-gray-500">Human Review 등록</p>
                  <p
                    className={`mt-1 text-xl font-bold ${
                      result.human_review_count > 0 ? 'text-amber-700' : 'text-gray-700'
                    }`}
                  >
                    {formatNumber(result.human_review_count)}
                  </p>
                  {result.human_review_count > 0 && (
                    <div className="mt-1.5">
                      <StatusBadge status="PENDING" />
                    </div>
                  )}
                </div>
                {/* Failed */}
                <div
                  className={`rounded-lg border p-3 ${
                    result.failed_count > 0 ? 'bg-red-50' : 'bg-gray-50'
                  }`}
                >
                  <p className="text-xs font-medium text-gray-500">실패</p>
                  <p
                    className={`mt-1 text-xl font-bold ${
                      result.failed_count > 0 ? 'text-red-700' : 'text-gray-700'
                    }`}
                  >
                    {formatNumber(result.failed_count)}
                  </p>
                  {result.failed_count > 0 && (
                    <div className="mt-1.5">
                      <StatusBadge status="FAILED" />
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-400">Fusion 실행 후 결과가 표시됩니다.</p>
          )}
        </div>
      </div>
    </div>
  )
}
