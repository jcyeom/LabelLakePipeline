import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import type { Role } from '@/lib/enums'
import { roleAtLeast } from '@/lib/enums'
import { useAuth } from '@/hooks/useAuth'

interface ProtectedRouteProps {
  minRole: Role
  children: ReactNode
}

// Guards a route by authentication + minimum role (frontend_design_prd 라우팅 맵).
export function ProtectedRoute({ minRole, children }: ProtectedRouteProps) {
  const { isAuthenticated, role } = useAuth()
  if (!isAuthenticated) return <Navigate to="/auth/login" replace />
  if (!roleAtLeast(role, minRole)) {
    return (
      <div className="p-8">
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-amber-800">
          <p className="font-semibold">접근 권한 없음</p>
          <p className="mt-1 text-sm">
            이 화면은 <b>{minRole}</b> 이상 권한이 필요합니다. 현재 역할: <b>{role}</b>
          </p>
        </div>
      </div>
    )
  }
  return <>{children}</>
}
