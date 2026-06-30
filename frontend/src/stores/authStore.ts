import { create } from 'zustand'
import type { Role } from '@/lib/enums'

// MVP dev-mode auth: identity is a selected role sent via the X-Role header (matches
// the backend auth_dev_mode). The accessToken slot is reserved for production JWT
// (frontend_design_prd 인증 플로우) but unused in dev-mode.
const ROLE_KEY = 'llp_role'
const USER_KEY = 'llp_user_id'
const TOKEN_KEY = 'llp_access_token'

interface AuthState {
  role: Role | null
  userId: string | null
  accessToken: string | null
  isAuthenticated: boolean
  login: (role: Role, userId: string) => void
  logout: () => void
  clearAuth: () => void
}

const storedRole = sessionStorage.getItem(ROLE_KEY) as Role | null

export const useAuthStore = create<AuthState>((set) => ({
  role: storedRole,
  userId: sessionStorage.getItem(USER_KEY),
  accessToken: sessionStorage.getItem(TOKEN_KEY),
  isAuthenticated: !!storedRole,
  login: (role, userId) => {
    sessionStorage.setItem(ROLE_KEY, role)
    sessionStorage.setItem(USER_KEY, userId)
    set({ role, userId, isAuthenticated: true })
  },
  logout: () => {
    sessionStorage.removeItem(ROLE_KEY)
    sessionStorage.removeItem(USER_KEY)
    sessionStorage.removeItem(TOKEN_KEY)
    set({ role: null, userId: null, accessToken: null, isAuthenticated: false })
  },
  clearAuth: () => {
    sessionStorage.removeItem(ROLE_KEY)
    sessionStorage.removeItem(USER_KEY)
    sessionStorage.removeItem(TOKEN_KEY)
    set({ role: null, userId: null, accessToken: null, isAuthenticated: false })
  },
}))
