// 비동기 배치(202 + run_id) 폴링 헬퍼.
// runId 를 받아 GET /runs/{run_id} 를 일정 간격으로 폴링하여 status 가
// COMPLETED/FAILED 가 될 때까지 RunView 를 갱신한다. TanStack Query v5 refetchInterval 패턴.
import { useQuery } from '@tanstack/react-query'
import { runsApi } from '@/api/endpoints'
import type { RunView } from '@/types/api'

const POLL_INTERVAL_MS = 600
// 최대 폴링 시간 (안전 타임아웃). 600ms × 200 = 120s.
const POLL_TIMEOUT_MS = 120_000

export interface UseRunJobResult {
  run: RunView | undefined
  isPolling: boolean
  isCompleted: boolean
  isFailed: boolean
  isError: boolean
  error: Error | null
}

// runId 가 null 이면 비활성. status 가 종료 상태가 되면 폴링을 멈춘다.
export function useRunJob(runId: string | null): UseRunJobResult {
  const query = useQuery<RunView, Error>({
    queryKey: ['runs', runId],
    queryFn: () => runsApi.getRun(runId as string),
    enabled: !!runId,
    refetchInterval: (q) => {
      const status = q.state.data?.status
      if (status === 'COMPLETED' || status === 'FAILED') return false
      // 안전 타임아웃: 시작 후 일정 시간이 지나면 폴링 중단.
      const startedAt = q.state.dataUpdatedAt || Date.now()
      if (Date.now() - startedAt > POLL_TIMEOUT_MS) return false
      return POLL_INTERVAL_MS
    },
    refetchIntervalInBackground: false,
    staleTime: 0,
    gcTime: 0,
  })

  const status = query.data?.status
  const isCompleted = status === 'COMPLETED'
  const isFailed = status === 'FAILED'
  const isPolling = !!runId && !isCompleted && !isFailed && !query.isError

  return {
    run: query.data,
    isPolling,
    isCompleted,
    isFailed,
    isError: query.isError,
    error: query.error,
  }
}
