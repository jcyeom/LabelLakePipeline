import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ROLES } from '@/lib/enums'
import type { Role } from '@/lib/enums'
import { useAuth } from '@/hooks/useAuth'

// Dev-mode login: pick a role + user id (backend auth_dev_mode via X-Role header).
// Production replaces this with an OAuth2 redirect (frontend_design_prd 인증 플로우).
export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [role, setRole] = useState<Role>('DataEngineer')
  const [userId, setUserId] = useState('operator-1')

  return (
    <div className="flex h-full items-center justify-center bg-gray-50">
      <div className="w-80 rounded-lg border bg-white p-6 shadow-sm">
        <h1 className="text-xl font-bold text-brand-600">LLP 운영 콘솔</h1>
        <p className="mt-1 text-sm text-gray-500">개발 모드 로그인 (역할 선택)</p>

        <label className="mt-4 block text-sm font-medium text-gray-700">사용자 ID</label>
        <input
          className="mt-1 w-full rounded border px-3 py-2 text-sm"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
        />

        <label className="mt-3 block text-sm font-medium text-gray-700">역할</label>
        <select
          className="mt-1 w-full rounded border px-3 py-2 text-sm"
          value={role}
          onChange={(e) => setRole(e.target.value as Role)}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>

        <button
          className="mt-5 w-full rounded bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-900"
          onClick={() => {
            login(role, userId.trim() || 'dev-user')
            navigate('/dashboard')
          }}
        >
          로그인
        </button>
      </div>
    </div>
  )
}
