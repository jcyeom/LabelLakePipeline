import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { dashboardApi } from '@/api/endpoints'
import { MetricCard } from '@/components/MetricCard'
import { StatusBadge } from '@/components/StatusBadge'
import { LoadingSkeleton, ErrorState } from '@/components/LoadingSkeleton'
import { POLLING_INTERVALS } from '@/lib/constants'
import { formatPercent, formatNumber, formatFloat, formatDateTime } from '@/lib/formatters'
import type { DashboardMetrics } from '@/types/api'

// ── helpers ──────────────────────────────────────────────────────────────────

function buildChartData(metrics: DashboardMetrics) {
  const methods = new Set([
    ...Object.keys(metrics.l1_by_method),
    ...Object.keys(metrics.avg_confidence_by_method),
    ...Object.keys(metrics.failure_rate_by_method),
  ])
  return Array.from(methods).map((m) => ({
    method: m,
    L1수: metrics.l1_by_method[m] ?? 0,
    평균신뢰도: +(metrics.avg_confidence_by_method[m] ?? 0).toFixed(3),
    실패율: +(((metrics.failure_rate_by_method[m] ?? 0) * 100).toFixed(1)),
  }))
}

function overallDriftStatus(statusByMethod: Record<string, string>): string {
  const statuses = Object.values(statusByMethod)
  if (statuses.includes('CRITICAL') || statuses.includes('REPUBLISH_REQUIRED')) return 'CRITICAL'
  if (statuses.includes('WARNING')) return 'WARNING'
  return 'NORMAL'
}

function driftToCardStatus(s: string): 'normal' | 'warning' | 'critical' {
  if (s === 'CRITICAL' || s === 'REPUBLISH_REQUIRED') return 'critical'
  if (s === 'WARNING') return 'warning'
  return 'normal'
}

// ── sub-components ────────────────────────────────────────────────────────────

function LabelerMetricCardGrid({ metrics }: { metrics: DashboardMetrics }) {
  const methods = Array.from(new Set([
    ...Object.keys(metrics.l1_by_method),
    ...Object.keys(metrics.failure_rate_by_method),
    ...Object.keys(metrics.avg_confidence_by_method),
  ]))

  if (methods.length === 0) return null

  function methodCardStatus(failureRate: number): 'normal' | 'warning' | 'critical' {
    if (failureRate >= 0.2) return 'critical'
    if (failureRate >= 0.05) return 'warning'
    return 'normal'
  }

  return (
    <div>
      <h2 className="mb-3 text-sm font-semibold text-gray-700">라벨러별 지표</h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {methods.map((method) => {
          const l1Count = metrics.l1_by_method[method] ?? 0
          const failureRate = metrics.failure_rate_by_method[method] ?? 0
          const avgConf = metrics.avg_confidence_by_method[method] ?? 0
          return (
            <MetricCard
              key={method}
              title={method}
              value={formatNumber(l1Count)}
              subtitle={`실패율 ${formatPercent(failureRate, 1)} · 평균 conf ${formatPercent(avgConf, 1)}`}
              status={methodCardStatus(failureRate)}
            />
          )
        })}
      </div>
    </div>
  )
}

function MetricCardGrid({ metrics, navigate }: { metrics: DashboardMetrics; navigate: (p: string) => void }) {
  const driftStatus = overallDriftStatus(metrics.drift_status_by_method)
  const l2Status: 'normal' | 'warning' | 'critical' =
    metrics.l2_agreement_rate < 0.8 ? 'warning' : 'normal'
  const queueStatus: 'normal' | 'warning' | 'critical' =
    metrics.human_review_queue_size > 100 ? 'warning' : 'normal'

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      <MetricCard
        title="전체 L1 수"
        value={formatNumber(metrics.total_l1)}
        subtitle="전체 L1 라벨 생성 수"
        status="normal"
      />
      <MetricCard
        title="L2 합의율"
        value={formatPercent(metrics.l2_agreement_rate, 1)}
        subtitle="L2 Agreement Rate"
        status={l2Status}
      />
      <div
        className="cursor-pointer"
        onClick={() => navigate('/reviews')}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') navigate('/reviews') }}
      >
        <MetricCard
          title="Human Review 대기"
          value={formatNumber(metrics.human_review_queue_size)}
          subtitle="클릭하여 검수 큐 이동"
          status={queueStatus}
        />
      </div>
      <MetricCard
        title="L3 생성 수"
        value={formatNumber(metrics.l3_count)}
        subtitle="Gold Label 생성 수"
        status="normal"
      />
      <MetricCard
        title="Gold 버전"
        value={metrics.gold_label_version ?? '-'}
        subtitle="현재 Gold Label 버전"
        status="normal"
      />
      <div
        className="cursor-pointer"
        onClick={() => navigate('/drift')}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') navigate('/drift') }}
      >
        <MetricCard
          title="드리프트 상태"
          value={driftStatus}
          subtitle="클릭하여 Drift 모니터링 이동"
          status={driftToCardStatus(driftStatus)}
        />
      </div>
    </div>
  )
}

function LabelerComparisonChart({ metrics }: { metrics: DashboardMetrics }) {
  const data = buildChartData(metrics)
  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold text-gray-700">라벨러별 L1 생성 비교</h2>
      {data.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-400">데이터 없음</p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="method" tick={{ fontSize: 12 }} />
            <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar yAxisId="left" dataKey="L1수" fill="#6366f1" radius={[3, 3, 0, 0]} />
            <Bar yAxisId="right" dataKey="실패율" fill="#ef4444" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

function ConfidenceComparisonChart({ metrics }: { metrics: DashboardMetrics }) {
  const data = buildChartData(metrics)
  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold text-gray-700">라벨러별 평균 신뢰도</h2>
      {data.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-400">데이터 없음</p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="method" tick={{ fontSize: 12 }} />
            <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v) => formatFloat(Number(v), 3)} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="평균신뢰도" fill="#0ea5e9" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

function DriftSummaryCard({ metrics }: { metrics: DashboardMetrics }) {
  const entries = Object.entries(metrics.drift_status_by_method)
  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold text-gray-700">드리프트 상태 요약</h2>
      {entries.length === 0 ? (
        <p className="py-4 text-center text-sm text-gray-400">측정 데이터 없음</p>
      ) : (
        <ul className="space-y-2">
          {entries.map(([method, status]) => (
            <li key={method} className="flex items-center justify-between gap-2 rounded-md border px-3 py-2">
              <span className="text-sm font-medium text-gray-700">{method}</span>
              <StatusBadge status={status} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── page ──────────────────────────────────────────────────────────────────────

export function DashboardPage() {
  const navigate = useNavigate()

  const { data, isLoading, isError, error, dataUpdatedAt } = useQuery({
    queryKey: ['dashboard', 'metrics'],
    queryFn: dashboardApi.metrics,
    refetchInterval: POLLING_INTERVALS.DASHBOARD,
  })

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6 sm:px-6 lg:px-8">
      {/* ── header ── */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Dashboard</h1>
          <p className="mt-0.5 text-sm text-slate-500">파이프라인 전체 운영 현황</p>
        </div>
        {dataUpdatedAt > 0 && (
          <p className="text-xs text-slate-400">
            마지막 갱신: {formatDateTime(new Date(dataUpdatedAt).toISOString())}
          </p>
        )}
      </div>

      {/* ── loading ── */}
      {isLoading && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-24 animate-pulse rounded-lg bg-gray-200" />
            ))}
          </div>
          <LoadingSkeleton rows={4} />
        </div>
      )}

      {/* ── error ── */}
      {isError && (
        <ErrorState
          message={`대시보드 데이터를 불러오지 못했습니다. ${error instanceof Error ? error.message : '알 수 없는 오류'}`}
        />
      )}

      {/* ── data ── */}
      {data && (
        <div className="space-y-6">
          {/* metric cards */}
          <MetricCardGrid metrics={data} navigate={navigate} />

          {/* labeler metric cards */}
          <LabelerMetricCardGrid metrics={data} />

          {/* charts row 1 */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <LabelerComparisonChart metrics={data} />
            <ConfidenceComparisonChart metrics={data} />
          </div>

          {/* drift summary */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <DriftSummaryCard metrics={data} />

            {/* quick-stats panel */}
            <div className="rounded-lg border bg-white p-4 shadow-sm">
              <h2 className="mb-3 text-sm font-semibold text-gray-700">주요 집계 지표</h2>
              <dl className="space-y-2 text-sm">
                {Object.entries(data.l1_by_method).map(([method, count]) => (
                  <div key={method} className="flex justify-between border-b pb-1 last:border-0">
                    <dt className="text-gray-500">{method} L1 수</dt>
                    <dd className="font-mono font-semibold text-gray-800">{formatNumber(count)}</dd>
                  </div>
                ))}
                {Object.entries(data.failure_rate_by_method).map(([method, rate]) => (
                  <div key={method} className="flex justify-between border-b pb-1 last:border-0">
                    <dt className="text-gray-500">{method} 실패율</dt>
                    <dd className="font-mono font-semibold text-red-600">{formatPercent(rate, 1)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
