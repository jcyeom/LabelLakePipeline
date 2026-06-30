import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { datasetsApi } from '@/api/endpoints'
import type { DatasetBuildRequest, DatasetBuildResponse } from '@/types/api'
import { LABEL_LEVEL, LABEL_METHOD } from '@/lib/enums'
import type { LabelLevel, LabelMethod } from '@/lib/enums'
import { RoleGate } from '@/components/RoleGate'
import { ErrorState } from '@/components/LoadingSkeleton'
import { useToast } from '@/hooks/useToast'
import { formatNumber } from '@/lib/formatters'

interface FormState {
  feature_version: string
  label_version: string
  label_level: LabelLevel
  confidence_min: string
  exclude_disagreement: boolean
  include_rationale: boolean
  task_type: string
  label_method_filter: LabelMethod[]
}

const INITIAL: FormState = {
  feature_version: '',
  label_version: '',
  label_level: 'L2',
  confidence_min: '',
  exclude_disagreement: false,
  include_rationale: false,
  task_type: '',
  label_method_filter: [],
}

export function DatasetBuilderPage() {
  const toast = useToast()
  const [form, setForm] = useState<FormState>(INITIAL)
  const [copied, setCopied] = useState(false)

  const mutation = useMutation<DatasetBuildResponse, Error, DatasetBuildRequest>({
    mutationFn: (body) => datasetsApi.build(body),
    onSuccess: (data) => {
      toast.success(`데이터셋 빌드 완료: ${data.dataset_id} (${data.sample_count.toLocaleString()}건)`)
    },
    onError: (err) => {
      toast.error(err.message)
    },
  })

  function buildRequest(): DatasetBuildRequest {
    const confidenceNum = form.confidence_min.trim() === '' ? undefined : Number(form.confidence_min)
    return {
      feature_version: form.feature_version.trim(),
      label_version: form.label_version.trim(),
      label_level: form.label_level,
      task_type: form.task_type.trim() !== '' ? form.task_type.trim() : undefined,
      confidence_min: confidenceNum !== undefined && !Number.isNaN(confidenceNum) ? confidenceNum : undefined,
      exclude_disagreement: form.exclude_disagreement,
      label_method_filter:
        form.label_method_filter.length > 0 ? form.label_method_filter : undefined,
      include_rationale: form.include_rationale,
    }
  }

  function toggleMethod(m: LabelMethod) {
    setForm((f) => ({
      ...f,
      label_method_filter: f.label_method_filter.includes(m)
        ? f.label_method_filter.filter((x) => x !== m)
        : [...f.label_method_filter, m],
    }))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.feature_version.trim()) {
      toast.error('feature_version을 입력해주세요.')
      return
    }
    if (!form.label_version.trim()) {
      toast.error('label_version을 입력해주세요.')
      return
    }
    mutation.mutate(buildRequest())
  }

  function handleCopy() {
    if (!mutation.data) return
    navigator.clipboard.writeText(mutation.data.manifest_uri).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const isLoading = mutation.isPending

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">Dataset Builder</h1>
        <p className="mt-1 text-sm text-gray-500">
          학습용 데이터셋을 빌드하고 manifest URI를 확인합니다. (FR-9)
        </p>
      </div>

      <RoleGate minRole="MLEngineer">
        <div className="space-y-6 max-w-2xl">
          {/* Build Config Form */}
          <div className="rounded-lg border bg-white p-6 shadow-sm">
            <h2 className="mb-4 text-sm font-semibold text-gray-700">데이터셋 빌드 설정</h2>
            <form onSubmit={handleSubmit} className="space-y-4">
              {/* feature_version */}
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  feature_version <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  className="mt-1 w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                  placeholder="예: fv-2026-01"
                  value={form.feature_version}
                  onChange={(e) => setForm((f) => ({ ...f, feature_version: e.target.value }))}
                  disabled={isLoading}
                />
              </div>

              {/* label_version */}
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  label_version <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  className="mt-1 w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                  placeholder="예: lv-2026-01"
                  value={form.label_version}
                  onChange={(e) => setForm((f) => ({ ...f, label_version: e.target.value }))}
                  disabled={isLoading}
                />
              </div>

              {/* label_level */}
              <div>
                <label className="block text-sm font-medium text-gray-700">label_level</label>
                <div className="mt-2 flex gap-4">
                  {LABEL_LEVEL.map((level) => (
                    <label key={level} className="flex items-center gap-1.5 cursor-pointer text-sm">
                      <input
                        type="radio"
                        name="label_level"
                        value={level}
                        checked={form.label_level === level}
                        onChange={() => setForm((f) => ({ ...f, label_level: level }))}
                        disabled={isLoading}
                        className="accent-brand-600"
                      />
                      {level}
                    </label>
                  ))}
                </div>
              </div>

              {/* confidence_min */}
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  confidence_min{' '}
                  <span className="text-xs text-gray-400">(선택, 0.0 ~ 1.0)</span>
                </label>
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  className="mt-1 w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                  placeholder="예: 0.70"
                  value={form.confidence_min}
                  onChange={(e) => setForm((f) => ({ ...f, confidence_min: e.target.value }))}
                  disabled={isLoading}
                />
              </div>

              {/* task_type */}
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  task_type{' '}
                  <span className="text-xs text-gray-400">(선택)</span>
                </label>
                <input
                  type="text"
                  className="mt-1 w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                  placeholder="예: cls"
                  value={form.task_type}
                  onChange={(e) => setForm((f) => ({ ...f, task_type: e.target.value }))}
                  disabled={isLoading}
                />
              </div>

              {/* label_method_filter */}
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  label_method_filter{' '}
                  <span className="text-xs text-gray-400">(선택, 미선택 시 전체)</span>
                </label>
                <div className="mt-2 flex gap-4">
                  {LABEL_METHOD.map((m) => (
                    <label key={m} className="flex items-center gap-1.5 cursor-pointer text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={form.label_method_filter.includes(m)}
                        onChange={() => toggleMethod(m)}
                        disabled={isLoading}
                        className="accent-brand-600"
                      />
                      {m}
                    </label>
                  ))}
                </div>
              </div>

              {/* checkboxes */}
              <div className="space-y-2">
                <label className="flex items-center gap-2 cursor-pointer text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={form.exclude_disagreement}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, exclude_disagreement: e.target.checked }))
                    }
                    disabled={isLoading}
                    className="accent-brand-600"
                  />
                  불일치 샘플 제외 (exclude_disagreement)
                </label>
                <label className="flex items-center gap-2 cursor-pointer text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={form.include_rationale}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, include_rationale: e.target.checked }))
                    }
                    disabled={isLoading}
                    className="accent-brand-600"
                  />
                  근거 포함 (include_rationale)
                </label>
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="w-full rounded bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isLoading ? '데이터셋 빌드 중...' : '데이터셋 빌드 실행'}
              </button>
            </form>
          </div>

          {/* Error State */}
          {mutation.isError && (
            <ErrorState message={`빌드 실패: ${mutation.error.message}`} />
          )}

          {/* Result Card */}
          <div
            className={`rounded-lg border p-6 shadow-sm transition-colors ${
              mutation.isSuccess ? 'bg-white' : 'bg-gray-50'
            }`}
          >
            <h2 className="mb-3 text-sm font-semibold text-gray-700">빌드 결과</h2>
            {mutation.isSuccess && mutation.data ? (
              <dl className="space-y-3">
                <div>
                  <dt className="text-xs font-medium text-gray-500">dataset_id</dt>
                  <dd className="mt-0.5 text-sm font-mono text-gray-900">{mutation.data.dataset_id}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-gray-500">sample_count</dt>
                  <dd className="mt-0.5 text-sm font-semibold text-gray-900">
                    {formatNumber(mutation.data.sample_count)}건
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-gray-500">manifest_uri</dt>
                  <dd className="mt-0.5 flex items-center gap-2">
                    <span className="text-sm font-mono text-gray-800 break-all">
                      {mutation.data.manifest_uri}
                    </span>
                    <button
                      type="button"
                      onClick={handleCopy}
                      className="shrink-0 rounded border px-2 py-0.5 text-xs font-medium text-gray-600 hover:bg-gray-100 transition-colors"
                    >
                      {copied ? '복사됨 ✓' : '복사'}
                    </button>
                  </dd>
                </div>
              </dl>
            ) : (
              <p className="text-sm text-gray-400">빌드 실행 후 결과가 표시됩니다.</p>
            )}
          </div>
        </div>
      </RoleGate>
    </div>
  )
}
