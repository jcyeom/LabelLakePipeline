import { NavLink } from 'react-router-dom'
import type { Role } from '@/lib/enums'
import { roleAtLeast } from '@/lib/enums'
import { useAuth } from '@/hooks/useAuth'

interface NavItem {
  to: string
  label: string
  minRole: Role
}

// Menu visibility matrix (frontend_design_prd 절차 7 메뉴 노출 매트릭스).
const NAV: NavItem[] = [
  { to: '/dashboard', label: '대시보드', minRole: 'Viewer' },
  { to: '/drift', label: 'Drift 모니터링', minRole: 'Viewer' },
  { to: '/reviews', label: 'Human Review', minRole: 'Reviewer' },
  { to: '/datasets/build', label: 'Dataset Builder', minRole: 'MLEngineer' },
  { to: '/fusion/run', label: 'Fusion 실행', minRole: 'DataEngineer' },
]

export function Sidebar() {
  const { role } = useAuth()
  return (
    <aside className="w-56 shrink-0 border-r bg-white">
      <div className="px-4 py-4 text-lg font-bold text-brand-600">LLP 운영 콘솔</div>
      <nav className="flex flex-col gap-1 px-2">
        {NAV.filter((n) => roleAtLeast(role, n.minRole)).map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            className={({ isActive }) =>
              `rounded px-3 py-2 text-sm ${
                isActive ? 'bg-brand-50 font-medium text-brand-900' : 'text-gray-600 hover:bg-gray-50'
              }`
            }
          >
            {n.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
