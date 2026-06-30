import { QueryClient } from '@tanstack/react-query'
import { STALE_TIME } from '@/lib/constants'
import { ApiError } from '@/api/client'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: STALE_TIME,
      retry: (failureCount, error) => {
        // Do not retry auth/permission errors.
        if (error instanceof ApiError && [401, 403, 404, 422].includes(error.status)) return false
        return failureCount < 2
      },
      refetchOnWindowFocus: false,
    },
  },
})
