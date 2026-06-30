import { forwardRef, useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { driftApi, goldApi } from '@/api/endpoints'
import type { Column } from '@/components/DataTable'
import { DataTable } from '@/components/DataTable'
import { StatusBadge } from '@/components/StatusBadge'
import { RoleGate } from '@/components/RoleGate'
import { LoadingSkeleton, ErrorState } from '@/components/LoadingSkeleton'
import { POLLING_INTERVALS, THRESHOLDS } from '@/lib/constants'
import { formatPercent, formatFloat, formatDateTime, formatNumber } from '@/lib/formatters'
import { useToast } from '@/hooks/useToast'
import { useRunJob } from '@/hooks/useRunJob'
import { useAuth } from '@/hooks/useAuth'
import { roleAtLeast } from '@/lib/enums'
import type { DriftMetric, GoldRepublishResponse } from '@/types/api'

// ── helpers ──────────────────────────────────────────────────────────────────

// Collect unique method keys for distinct line colors
const LINE_COLORS = ['#6366f1', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444']

function uniqueMethods(metrics: DriftMetric[]): string[] {
  return Array.from(new Set(metrics.map((m) => `${m.method}@${m.method_ver}`)))
}

// 단일 공유 data 배열을 타임스탬프 키로 정렬해 구성. 각 method 는 별도 dataKey 로 그린다.
// (이전 구현은 <Line> 마다 data 를 따로 필터링해 X축 정렬이 깨질 수 있었다.)
type ChartMetric = 'psi' | 'kl' | 'anchor'
interface ChartRow {
  ts: number
  measured_at: string
  [methodKey: string]: number | string
}

function metricValue(m: DriftMetric, metric: ChartMetric): number {
  if (metric === 'psi') return m.psi ?? 0
  if (metric === 'kl') return m.kl_divergence ?? 0
  return m.anchor_accuracy ?? 0
}

// metric(psi/kl/anchor) 기준으로 시계열을 피벗: 행=타임스탬프, 열=method 라벨.
function buildSharedSeries(metrics: DriftMetric[], metric: ChartMetric): ChartRow[] {
  const byTs = new Map<number, ChartRow>()
  for (const m of metrics) {
    const ts = new Date(m.measured_at).getTime()
    const key = Number.isNaN(ts) ? 0 : ts
    const label = `${m.method}@${m.method_ver}`
    let row = byTs.get(key)
    if (!row) {
      row = { ts: key, measured_at: formatDateTime(m.measured_at) }
      byTs.set(key, row)
    }
    row[label] = metricValue(m, metric)
  }
  return Array.from(byTs.values()).sort((a, b) => a.ts - b.ts)
}

// ── sub-components ────────────────────────────────────────────────────────────

interface RunFormState {
  method: 'rule' | 'llm' | 'human'
  method_ver: string
  baseline_window: string
  current_window: string
  metrics: string[]
}

function DriftRunForm({ onSuccess }: { onSuccess: () => void }) {
  const toast = useToast()
  const [form, setForm] = useState<RunFormState>({
    method: 'rule',
    method_ver: '',
    baseline_window: '',
    current_window: '',
    metrics: ['psi'],
  })
  const [runId, setRunId] = useState<string | null>(null)
  // 완료 알림이 한 번만 발생하도록 가드.
  const notifiedRef = useRef<string | null>(null)

  const job = useRunJob(runId)

  const mutation = useMutation({
    mutationFn: () =>
      driftApi.run({
        method: form.method,
        method_ver: form.method_ver,
        baseline_window: form.baseline_window,
        current_window: form.current_window,
        metrics: form.metrics,
      }),
    onSuccess: (data) => {
      setRunId(data.run_id)
      toast.success('드리프트 측정이 접수되었습니다. 처리 중...')
    },
    onError: (err: unknown) => {
      toast.error(`드리프트 측정 실패: ${err instanceof Error ? err.message : '알 수 없는 오류'}`)
    },
  })

  // 폴링 완료/실패 시 1회 처리 (render 중 side-effect 금지 → effect).
  useEffect(() => {
    if (!runId || notifiedRef.current === runId) return
    if (job.isCompleted) {
      notifiedRef.current = runId
      toast.success('드리프트 측정이 완료되었습니다.')
      onSuccess()
    } else if (job.isFailed || job.isError) {
      notifiedRef.current = runId
      toast.error(`드리프트 측정 실패: ${job.run?.error ?? job.error?.message ?? '알 수 없는 오류'}`)
    }
  }, [runId, job.isCompleted, job.isFailed, job.isError, job.run?.error, job.error, onSuccess, toast])

  const toggleMetric = (m: string) => {
    setForm((prev) => ({
      ...prev,
      metrics: prev.metrics.includes(m) ? prev.metrics.filter((x) => x !== m) : [...prev.metrics, m],
    }))
  }

  const isRunning = mutation.isPending || job.isPolling

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setRunId(null)
    notifiedRef.current = null
    mutation.mutate()
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border bg-white p-4 shadow-sm space-y-4"
    >
      <h2 className="text-sm font-semibold text-gray-700">Drift 측정 실행</h2>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {/* method */}
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Method</label>
          <select
            value={form.method}
            onChange={(e) => setForm((p) => ({ ...p, method: e.target.value as RunFormState['method'] }))}
            className="w-full rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400"
          >
            <option value="rule">rule</option>
            <option value="llm">llm</option>
            <option value="human">human</option>
          </select>
        </div>

        {/* method_ver */}
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Method Version</label>
          <input
            type="text"
            placeholder="예: rule-v1"
            value={form.method_ver}
            onChange={(e) => setForm((p) => ({ ...p, method_ver: e.target.value }))}
            required
            className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400"
          />
        </div>

        {/* baseline_window */}
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">
            기준 기간 <span className="text-gray-300">(예: 2026-01-01/2026-01-31)</span>
          </label>
          <input
            type="text"
            placeholder="2026-01-01/2026-01-31"
            value={form.baseline_window}
            onChange={(e) => setForm((p) => ({ ...p, baseline_window: e.target.value }))}
            required
            className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400"
          />
        </div>

        {/* current_window */}
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">
            현재 기간 <span className="text-gray-300">(예: 2026-02-01/2026-02-28)</span>
          </label>
          <input
            type="text"
            placeholder="2026-02-01/2026-02-28"
            value={form.current_window}
            onChange={(e) => setForm((p) => ({ ...p, current_window: e.target.value }))}
            required
            className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400"
          />
        </div>
      </div>

      {/* metrics checkboxes */}
      <div>
        <label className="block text-xs font-medium text-gray-500 mb-2">측정 지표</label>
        <div className="flex gap-4">
          {(['psi', 'kl_divergence', 'anchor_accuracy'] as const).map((m) => (
            <label key={m} className="flex items-center gap-1.5 text-sm text-gray-700 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={form.metrics.includes(m)}
                onChange={() => toggleMetric(m)}
                className="rounded border-gray-300 text-sky-500 focus:ring-sky-400"
              />
              {m}
            </label>
          ))}
        </div>
      </div>

      <button
        type="submit"
        disabled={isRunning}
        className="inline-flex items-center gap-2 rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-sky-700 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-sky-400"
      >
        {isRunning ? (
          <>
            <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
            측정 중…
          </>
        ) : (
          '측정 실행'
        )}
      </button>
      {isRunning && runId && (
        <p className="text-xs text-sky-600">처리 중… (run_id: {runId})</p>
      )}
    </form>
  )
}

function PsiKlChart({ metrics }: { metrics: DriftMetric[] }) {
  const data = buildSharedSeries(metrics, 'psi')
  const methods = uniqueMethods(metrics)

  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold text-gray-700">PSI 추세 (라벨러별)</h2>
      {data.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-400">측정 데이터 없음</p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="measured_at" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <ReferenceLine
              y={THRESHOLDS.PSI_WARNING}
              stroke="#f59e0b"
              strokeDasharray="4 3"
              label={{ value: 'WARNING', fill: '#f59e0b', fontSize: 10 }}
            />
            <ReferenceLine
              y={THRESHOLDS.PSI_CRITICAL}
              stroke="#ef4444"
              strokeDasharray="4 3"
              label={{ value: 'CRITICAL', fill: '#ef4444', fontSize: 10 }}
            />
            {methods.map((method, i) => (
              <Line
                key={method}
                type="monotone"
                dataKey={method}
                name={`PSI (${method})`}
                stroke={LINE_COLORS[i % LINE_COLORS.length]}
                dot={{ r: 3 }}
                strokeWidth={2}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

function KlChart({ metrics }: { metrics: DriftMetric[] }) {
  const data = buildSharedSeries(metrics, 'kl')
  const methods = uniqueMethods(metrics)

  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold text-gray-700">KL Divergence 추세</h2>
      {data.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-400">측정 데이터 없음</p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="measured_at" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <ReferenceLine
              y={THRESHOLDS.KL_WARNING}
              stroke="#f59e0b"
              strokeDasharray="4 3"
              label={{ value: 'WARNING', fill: '#f59e0b', fontSize: 10 }}
            />
            <ReferenceLine
              y={THRESHOLDS.KL_CRITICAL}
              stroke="#ef4444"
              strokeDasharray="4 3"
              label={{ value: 'CRITICAL', fill: '#ef4444', fontSize: 10 }}
            />
            {methods.map((method, i) => (
              <Line
                key={method}
                type="monotone"
                dataKey={method}
                name={`KL (${method})`}
                stroke={LINE_COLORS[i % LINE_COLORS.length]}
                dot={{ r: 3 }}
                strokeWidth={2}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

function AnchorAccuracyChart({ metrics }: { metrics: DriftMetric[] }) {
  const data = buildSharedSeries(metrics, 'anchor')
  const methods = uniqueMethods(metrics)

  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold text-gray-700">L3 앵커 정확도 추세</h2>
      {data.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-400">측정 데이터 없음</p>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="measured_at" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v) => formatPercent(Number(v), 1)} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <ReferenceLine
              y={0.95}
              stroke="#f59e0b"
              strokeDasharray="4 3"
              label={{ value: '기준치 -5%', fill: '#f59e0b', fontSize: 10 }}
            />
            {methods.map((method, i) => (
              <Line
                key={method}
                type="monotone"
                dataKey={method}
                name={`앵커정확도 (${method})`}
                stroke={LINE_COLORS[i % LINE_COLORS.length]}
                dot={{ r: 3 }}
                strokeWidth={2}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

const GoldRepublishPanel = forwardRef<HTMLDivElement>(function GoldRepublishPanel(_props, ref) {
  const toast = useToast()
  const [confirming, setConfirming] = useState(false)
  const [runId, setRunId] = useState<string | null>(null)
  const notifiedRef = useRef<string | null>(null)

  const job = useRunJob(runId)

  const mutation = useMutation({
    mutationFn: () => goldApi.republish({ trigger: 'manual' }),
    onSuccess: (data) => {
      setRunId(data.run_id)
      setConfirming(false)
      toast.success('Gold 재발행이 접수되었습니다. 처리 중...')
    },
    onError: (err: unknown) => {
      toast.error(`Gold 재발행 실패: ${err instanceof Error ? err.message : '알 수 없는 오류'}`)
      setConfirming(false)
    },
  })

  // 폴링 완료/실패 1회 처리 (render 중 side-effect 금지 → effect).
  useEffect(() => {
    if (!runId || notifiedRef.current === runId) return
    if (job.isCompleted) {
      notifiedRef.current = runId
      const r = job.run?.result as unknown as GoldRepublishResponse | undefined
      toast.success(`Gold 재발행 완료: ${r?.label_version ?? ''}`)
    } else if (job.isFailed || job.isError) {
      notifiedRef.current = runId
      toast.error(`Gold 재발행 실패: ${job.run?.error ?? job.error?.message ?? '알 수 없는 오류'}`)
    }
  }, [runId, job.isCompleted, job.isFailed, job.isError, job.run, job.error, toast])

  const isRunning = mutation.isPending || job.isPolling
  const result =
    job.isCompleted && job.run?.result
      ? (job.run.result as unknown as GoldRepublishResponse)
      : undefined

  return (
    <div ref={ref} className="rounded-lg border border-red-200 bg-red-50 p-4 shadow-sm">
      <h2 className="mb-1 text-sm font-semibold text-red-800">Gold Republish (Admin 전용)</h2>
      <p className="mb-3 text-xs text-red-600">
        현재 Gold 라벨을 기반으로 재발행합니다. 이 작업은 되돌릴 수 없습니다.
      </p>

      {isRunning ? (
        <div className="flex items-center gap-2 text-sm text-red-700">
          <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-red-500 border-t-transparent" />
          재발행 처리 중…{runId && <span className="font-mono text-xs">({runId})</span>}
        </div>
      ) : !confirming ? (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-400"
        >
          Gold 재발행 실행
        </button>
      ) : (
        <div className="space-y-2">
          <p className="text-sm font-medium text-red-800">
            정말로 재발행하시겠습니까? 이 작업은 되돌릴 수 없습니다.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              취소
            </button>
            <button
              type="button"
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
              className="inline-flex items-center gap-1.5 rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              {mutation.isPending ? (
                <>
                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  재발행 중…
                </>
              ) : (
                '재발행 실행'
              )}
            </button>
          </div>
        </div>
      )}

      {result && (
        <dl className="mt-3 grid grid-cols-2 gap-2 rounded-md border border-red-200 bg-white p-3 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-gray-500">version_id</dt>
            <dd className="font-mono text-xs text-gray-900">{result.version_id}</dd>
          </div>
          <div>
            <dt className="text-xs text-gray-500">label_version</dt>
            <dd className="font-mono text-xs text-gray-900">{result.label_version}</dd>
          </div>
          <div>
            <dt className="text-xs text-gray-500">run_id</dt>
            <dd className="font-mono text-xs text-gray-900">{result.run_id}</dd>
          </div>
          <div>
            <dt className="text-xs text-gray-500">재발행 건수</dt>
            <dd className="font-semibold text-gray-900">{formatNumber(result.republished_count)}</dd>
          </div>
        </dl>
      )}
    </div>
  )
})

// ── columns ───────────────────────────────────────────────────────────────────

const driftColumns: Column<DriftMetric>[] = [
  {
    key: 'method',
    header: 'Method',
    render: (row) => (
      <span className="font-medium text-gray-800">{row.method}</span>
    ),
  },
  {
    key: 'method_ver',
    header: 'Version',
    render: (row) => <span className="font-mono text-xs text-gray-600">{row.method_ver}</span>,
  },
  {
    key: 'baseline_window',
    header: '기준 기간',
    render: (row) => <span className="text-xs text-gray-500">{row.baseline_window}</span>,
  },
  {
    key: 'current_window',
    header: '현재 기간',
    render: (row) => <span className="text-xs text-gray-500">{row.current_window}</span>,
  },
  {
    key: 'psi',
    header: 'PSI',
    render: (row) => (
      <span
        className={`font-mono text-sm font-semibold ${
          (row.psi ?? 0) >= THRESHOLDS.PSI_CRITICAL
            ? 'text-red-600'
            : (row.psi ?? 0) >= THRESHOLDS.PSI_WARNING
            ? 'text-amber-600'
            : 'text-gray-700'
        }`}
      >
        {formatFloat(row.psi)}
      </span>
    ),
  },
  {
    key: 'kl_divergence',
    header: 'KL Divergence',
    render: (row) => (
      <span
        className={`font-mono text-sm font-semibold ${
          (row.kl_divergence ?? 0) >= THRESHOLDS.KL_CRITICAL
            ? 'text-red-600'
            : (row.kl_divergence ?? 0) >= THRESHOLDS.KL_WARNING
            ? 'text-amber-600'
            : 'text-gray-700'
        }`}
      >
        {formatFloat(row.kl_divergence)}
      </span>
    ),
  },
  {
    key: 'anchor_accuracy',
    header: '앵커 정확도',
    render: (row) => <span className="font-mono text-sm">{formatPercent(row.anchor_accuracy, 1)}</span>,
  },
  {
    key: 'status',
    header: '상태',
    render: (row) => <StatusBadge status={row.status} />,
  },
  {
    key: 'measured_at',
    header: '측정 시각',
    render: (row) => <span className="text-xs text-gray-500">{formatDateTime(row.measured_at)}</span>,
  },
]

// ── page ──────────────────────────────────────────────────────────────────────

export function DriftPage() {
  const queryClient = useQueryClient()
  const { role } = useAuth()
  const isAdmin = roleAtLeast(role, 'Admin')
  const republishPanelRef = useRef<HTMLDivElement>(null)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['drift', 'metrics'],
    queryFn: () => driftApi.metrics(),
    refetchInterval: POLLING_INTERVALS.DRIFT,
  })

  const handleDriftRunSuccess = () => {
    void queryClient.invalidateQueries({ queryKey: ['drift', 'metrics'] })
  }

  const scrollToRepublish = () => {
    republishPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  // REPUBLISH_REQUIRED 행에 한해 Admin 인라인 액션 컬럼을 덧붙인다.
  const columns: Column<DriftMetric>[] = isAdmin
    ? [
        ...driftColumns,
        {
          key: 'republish_action',
          header: '',
          render: (row) =>
            row.status === 'REPUBLISH_REQUIRED' ? (
              <button
                type="button"
                onClick={scrollToRepublish}
                className="rounded-md bg-red-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-red-700"
              >
                Gold 재발행 →
              </button>
            ) : null,
        },
      ]
    : driftColumns

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6 sm:px-6 lg:px-8">
      {/* ── header ── */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Drift Monitoring</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            라벨러별 분포 드리프트(PSI · KL Divergence) 및 L3 앵커 정확도 모니터링
          </p>
        </div>
      </div>

      {/* ── run form (DataEngineer+) ── */}
      <div className="mb-6">
        <RoleGate
          minRole="DataEngineer"
          fallback={
            <p className="rounded-md border border-gray-200 bg-white px-4 py-3 text-sm text-gray-400">
              Drift 측정 실행은 DataEngineer 이상 권한이 필요합니다.
            </p>
          }
        >
          <DriftRunForm onSuccess={handleDriftRunSuccess} />
        </RoleGate>
      </div>

      {/* ── loading ── */}
      {isLoading && (
        <div className="space-y-4">
          <LoadingSkeleton rows={5} />
          <div className="h-64 animate-pulse rounded-lg bg-gray-200" />
          <div className="h-64 animate-pulse rounded-lg bg-gray-200" />
        </div>
      )}

      {/* ── error ── */}
      {isError && (
        <ErrorState
          message={`드리프트 데이터를 불러오지 못했습니다. ${error instanceof Error ? error.message : '알 수 없는 오류'}`}
        />
      )}

      {/* ── data ── */}
      {data && (
        <div className="space-y-6">
          {/* status table */}
          <div className="rounded-lg border bg-white shadow-sm">
            <div className="border-b px-4 py-3">
              <h2 className="text-sm font-semibold text-gray-700">라벨러별 드리프트 상태</h2>
            </div>
            <div className="p-2">
              <DataTable<DriftMetric>
                columns={columns}
                data={data}
                isLoading={isLoading}
                rowKey={(m) => m.metric_id}
                rowClassName={(m) =>
                  m.status === 'REPUBLISH_REQUIRED' ? 'bg-red-50 ring-1 ring-inset ring-red-200' : undefined
                }
                emptyMessage="드리프트 측정 이력이 없습니다. 측정 실행 버튼을 눌러주세요."
              />
            </div>
          </div>

          {/* charts */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <PsiKlChart metrics={data} />
            <KlChart metrics={data} />
          </div>
          <AnchorAccuracyChart metrics={data} />

          {/* gold republish (Admin only) */}
          <RoleGate minRole="Admin">
            <GoldRepublishPanel ref={republishPanelRef} />
          </RoleGate>
        </div>
      )}
    </div>
  )
}
