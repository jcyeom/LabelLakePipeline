import type { ReactNode } from 'react'
import type { Role } from '@/lib/enums'
import { roleAtLeast } from '@/lib/enums'
import { useAuth } from '@/hooks/useAuth'

interface RoleGateProps {
  minRole: Role
  children: ReactNode
  fallback?: ReactNode
}

// Renders children only when the current user's role meets minRole (§12 RBAC).
export function RoleGate({ minRole, children, fallback = null }: RoleGateProps) {
  const { role } = useAuth()
  if (!roleAtLeast(role, minRole)) return <>{fallback}</>
  return <>{children}</>
}
