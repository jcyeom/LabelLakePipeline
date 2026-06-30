import { useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import { Sidebar } from '@/components/Sidebar'
import { Toaster } from '@/components/Toaster'
import { useAuth } from '@/hooks/useAuth'
import { ROLES } from '@/lib/enums'
import type { Role } from '@/lib/enums'

// Sidebar + header layout (frontend_design_prd AppShell). The role switcher emulates
// dev-mode identity selection (no IdP in MVP).
export function AppShell() {
  const { role, userId, login, logout } = useAuth()
  const navigate = useNavigate()
  const [current, setCurrent] = useState<Role>(role ?? 'Viewer')

  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b bg-white px-6 py-3">
          <div className="flex items-center gap-3">
            <input
              className="rounded border px-3 py-1.5 text-sm"
              placeholder="sample_id 로 이동"
              onKeyDown={(e) => {
                const v = (e.target as HTMLInputElement).value.trim()
                if (e.key === 'Enter' && v) navigate(`/samples/${v}`)
              }}
            />
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-gray-500">역할(dev):</span>
            <select
              className="rounded border px-2 py-1"
              value={current}
              onChange={(e) => {
                const r = e.target.value as Role
                setCurrent(r)
                login(r, userId ?? 'dev-user')
              }}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <button
              className="rounded bg-gray-100 px-3 py-1 text-gray-700 hover:bg-gray-200"
              onClick={() => {
                logout()
                navigate('/auth/login')
              }}
            >
              로그아웃
            </button>
          </div>
        </header>
        <main className="min-w-0 flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
      <Toaster />
    </div>
  )
}
