import { useAuthStore } from '@/stores/authStore'

export function useAuth() {
  const role = useAuthStore((s) => s.role)
  const userId = useAuthStore((s) => s.userId)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const login = useAuthStore((s) => s.login)
  const logout = useAuthStore((s) => s.logout)
  return { role, userId, isAuthenticated, login, logout }
}
