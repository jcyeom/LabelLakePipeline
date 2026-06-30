import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { auditApi, labelsApi } from '@/api/endpoints'
import type { AuditRecord, L1Label } from '@/types/api'
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

const l1Columns: Column<L1Label>[] = [
  { key: 'method', header: 'method', render: (l) => <StatusBadge status={l.method} /> },
  {
    key: 'method_ver',
    header: 'method_ver',
    render: (l) => <span className="font-mono text-xs text-gray-500">{l.method_ver}</span>,
  },
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
  {
    key: 'labeled_at',
    header: 'labeled_at',
    render: (l) => <span className="text-xs text-gray-500">{formatDateTime(l.labeled_at)}</span>,
  },
]

export function SampleDetailPage() {
  const { sampleId = '' } = useParams<{ sampleId: string }>()
  const navigate = useNavigate()
  const [showLineage, setShowLineage] = useState(false)

  const l1Query = useQuery({
    queryKey: ['labels', 'l1', sampleId],
    queryFn: () => labelsApi.getL1(sampleId),
    enabled: !!sampleId,
    staleTime: STALE_TIME,
  })

  const l2Query = useQuery({
    queryKey: ['labels', 'l2', sampleId],
    queryFn: () => labelsApi.getL2(sampleId),
    enabled: !!sampleId,
    retry: false,
    staleTime: STALE_TIME,
  })

  const l3Query = useQuery({
    queryKey: ['labels', 'l3', sampleId],
    queryFn: () => labelsApi.getL3(sampleId),
    enabled: !!sampleId,
    retry: false,
    staleTime: STALE_TIME,
  })

  const labels = l1Query.data?.labels ?? []
  const inputsHash = labels.find((l) => l.inputs_hash)?.inputs_hash ?? null
  // feature 값 요약 (§11.2): feature_id / feature_version 식별자 (실제 feature 값은 Feature Store 소관).
  const featureId = labels.find((l) => l.feature_id)?.feature_id ?? null
  const featureVersion = labels.find((l) => l.feature_version)?.feature_version ?? null
  const l2 = l2Query.data
  const l3 = l3Query.data

  const lineageQuery = useQuery({
    queryKey: ['audit', 'lineage', l2?.consensus_label_id],
    queryFn: () => auditApi.lineage(l2!.consensus_label_id),
    enabled: showLineage && !!l2?.consensus_label_id,
    staleTime: 60_000,
  })

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate(-1)}
          className="rounded-md border px-2.5 py-1 text-sm text-gray-600 hover:bg-gray-50"
        >
          ← 뒤로
        </button>
        <h1 className="text-xl font-bold text-gray-900">Sample Detail</h1>
        <code className="rounded bg-gray-100 px-2 py-1 font-mono text-sm text-gray-700">
          {sampleId || '—'}
        </code>
      </div>

      {/* 샘플 메타 정보 */}
      <section className="rounded-lg border bg-white p-5">
        <h2 className="text-sm font-semibold text-gray-500">샘플 메타 정보</h2>
        <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <MetaItem label="sample_id" value={<code className="font-mono">{sampleId || '—'}</code>} />
          <MetaItem label="feature_id" value={<code className="font-mono">{featureId ?? '—'}</code>} />
          <MetaItem label="feature_version" value={<code className="font-mono">{featureVersion ?? '—'}</code>} />
          <MetaItem
            label="inputs_hash"
            value={
              <code className="break-all font-mono text-xs">{inputsHash ?? '—'}</code>
            }
          />
        </dl>
      </section>

      {/* L1 후보 라벨 목록 */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-900">L1 후보 라벨 목록</h2>
          {!!l2?.consensus_label_id && (
            <button
              onClick={() => setShowLineage((v) => !v)}
              className="rounded-md border border-brand-500 px-3 py-1 text-sm font-medium text-brand-600 hover:bg-brand-50"
            >
              {showLineage ? '계보 숨기기' : '계보 보기'}
            </button>
          )}
        </div>

        {l1Query.isLoading ? (
          <LoadingSkeleton rows={4} />
        ) : l1Query.isError ? (
          <ErrorState message="L1 라벨을 불러오지 못했습니다." />
        ) : (
          <DataTable<L1Label>
            columns={l1Columns}
            data={labels}
            rowKey={(l) => l.label_id}
            emptyMessage="이 샘플에 대한 L1 라벨이 없습니다."
          />
        )}

        {showLineage && (
          <LineagePanel
            isLoading={lineageQuery.isLoading}
            isError={lineageQuery.isError}
            records={lineageQuery.data?.records ?? []}
          />
        )}
      </section>

      {/* L2 / L3 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* L2 합의 결과 */}
        <section className="rounded-lg border bg-white p-5">
          <h2 className="text-base font-semibold text-gray-900">L2 합의 결과</h2>
          {l2Query.isLoading ? (
            <div className="mt-4">
              <LoadingSkeleton rows={3} />
            </div>
          ) : l2 ? (
            <dl className="mt-4 space-y-3">
              <MetaItem
                label="값"
                value={<span className="font-medium text-gray-900">{formatValue(l2.value)}</span>}
              />
              <MetaItem label="flag" value={<StatusBadge status={l2.flag} />} />
              <MetaItem label="fusion_policy" value={l2.fusion_policy} />
              <MetaItem label="agreement_score" value={formatPercent(l2.agreement_score)} />
              <MetaItem label="label_version" value={<code className="font-mono text-xs">{l2.label_version}</code>} />
              <MetaItem label="source_l1 개수" value={`${l2.source_l1_ids.length}개`} />
              <MetaItem
                label="fusion_reason"
                value={<span className="text-gray-600">{l2.fusion_reason ?? '—'}</span>}
              />
              <AgreementList agreement={l2.agreement} />
            </dl>
          ) : (
            <EmptyCard text="L2 합의 라벨 없음" hint="Fusion 미실행 또는 Human Review 대기 중" />
          )}
        </section>

        {/* L3 검증 결과 */}
        <section className="rounded-lg border bg-white p-5">
          <h2 className="text-base font-semibold text-gray-900">L3 검증 결과</h2>
          {l3Query.isLoading ? (
            <div className="mt-4">
              <LoadingSkeleton rows={3} />
            </div>
          ) : l3 ? (
            <dl className="mt-4 space-y-3">
              <MetaItem
                label="값"
                value={<span className="font-medium text-gray-900">{formatValue(l3.value)}</span>}
              />
              <MetaItem label="reviewer_id" value={l3.reviewer_id} />
              <MetaItem
                label="review_reason"
                value={<span className="text-gray-600">{l3.review_reason ?? '—'}</span>}
              />
              <MetaItem label="status" value={<StatusBadge status={l3.status} />} />
            </dl>
          ) : (
            <EmptyCard text="L3 검증 라벨 없음" hint="검수 미완료" />
          )}
        </section>
      </div>

      {/* 계보 / 검수 링크 */}
      <RoleGate minRole="Reviewer">
        <div className="flex flex-wrap gap-3 text-sm">
          <Link
            to="/reviews"
            className="rounded-md bg-brand-600 px-4 py-2 font-medium text-white hover:bg-brand-900"
          >
            Human Review 큐 보기 →
          </Link>
        </div>
      </RoleGate>
    </div>
  )
}

function MetaItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-medium uppercase tracking-wide text-gray-400">{label}</dt>
      <dd className="text-sm text-gray-800">{value}</dd>
    </div>
  )
}

function EmptyCard({ text, hint }: { text: string; hint: string }) {
  return (
    <div className="mt-4 rounded-md border border-dashed border-gray-300 bg-gray-50 p-6 text-center">
      <p className="text-sm font-medium text-gray-500">{text}</p>
      <p className="mt-1 text-xs text-gray-400">{hint}</p>
    </div>
  )
}

function LineagePanel({
  isLoading,
  isError,
  records,
}: {
  isLoading: boolean
  isError: boolean
  records: AuditRecord[]
}) {
  return (
    <div className="rounded-lg border bg-white p-4">
      <h3 className="text-sm font-semibold text-gray-500">라벨 생성 이력 (계보)</h3>
      {isLoading ? (
        <div className="mt-3">
          <LoadingSkeleton rows={3} />
        </div>
      ) : isError ? (
        <ErrorState message="계보 정보를 불러오지 못했습니다." />
      ) : records.length === 0 ? (
        <p className="mt-3 text-sm text-gray-400">계보 기록 없음</p>
      ) : (
        <ol className="mt-3 space-y-2 border-l-2 border-gray-200 pl-4">
          {records.map((r) => (
            <li key={r.audit_id} className="relative">
              <span className="absolute -left-[1.4rem] top-1.5 h-2 w-2 rounded-full bg-brand-500" />
              <div className="flex flex-wrap items-baseline gap-2 text-sm">
                <span className="text-xs text-gray-400">{formatDateTime(r.created_at)}</span>
                <span className="font-medium text-gray-800">{r.action}</span>
                <span className="text-xs text-gray-500">{r.entity_type}</span>
                {r.actor && <span className="text-xs text-gray-400">· {r.actor}</span>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
