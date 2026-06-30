// Typed fetch wrapper (frontend_design_prd API 클라이언트 레이어).
// Dev-mode: injects X-Role / X-User-Id headers (backend auth_dev_mode). Production
// would inject `Authorization: Bearer <token>` instead.
import { useAuthStore } from '@/stores/authStore'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

export class ApiError extends Error {
  status: number
  errorCode?: string
  details?: unknown
  constructor(status: number, message: string, errorCode?: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.errorCode = errorCode
    this.details = details
  }
}

function authHeaders(): Record<string, string> {
  const { role, userId, accessToken } = useAuthStore.getState()
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  if (userId) headers['X-User-Id'] = userId
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`
  return headers
}

// 422 details 가 배열(FastAPI validation 형태)일 수 있으므로 사람이 읽을 수 있는 한 줄로 변환.
function summarizeDetails(details: unknown): string | undefined {
  if (Array.isArray(details)) {
    const parts = details
      .map((d) => {
        if (d && typeof d === 'object') {
          const rec = d as Record<string, unknown>
          const loc = Array.isArray(rec.loc) ? rec.loc.join('.') : undefined
          const msg = typeof rec.msg === 'string' ? rec.msg : undefined
          return [loc, msg].filter(Boolean).join(': ')
        }
        return typeof d === 'string' ? d : undefined
      })
      .filter((s): s is string => Boolean(s))
    return parts.length > 0 ? parts.join('; ') : undefined
  }
  if (typeof details === 'string') return details
  return undefined
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...init?.headers,
    },
  })

  if (res.status === 401) {
    useAuthStore.getState().clearAuth()
    if (typeof window !== 'undefined') window.location.href = '/auth/login'
    throw new ApiError(401, '인증이 만료되었습니다.')
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}) as Record<string, unknown>)
    const message =
      (typeof body.message === 'string' ? body.message : undefined) ??
      (typeof body.detail === 'string' ? body.detail : undefined) ??
      summarizeDetails(body.details) ??
      `요청 실패 (${res.status})`
    throw new ApiError(res.status, message, body.error_code as string | undefined, body.details)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
