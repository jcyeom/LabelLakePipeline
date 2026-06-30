# LLP Frontend (MVP)

Internal operations/admin SPA for the Label Lake Pipeline, built from
[`../design/frontend_design_prd.md`](../design/frontend_design_prd.md). Consumes the
FastAPI backend in [`../backend`](../backend). Not a labeling/annotation tool (PRD §2.2).

## Stack
- React 18 + TypeScript + Vite
- TanStack Query (server state / polling) · Zustand (UI/auth state)
- Tailwind CSS · Recharts (PSI/KL/trend charts) · React Router

## Setup & run
```bash
cd frontend
npm install
cp .env.example .env          # adjust VITE_PROXY_TARGET if backend runs elsewhere
npm run dev                   # http://localhost:5173 (proxies /api → backend :8000)
```
Run the backend in parallel: `cd ../backend && ./.venv/bin/python -m uvicorn app.main:app`.

## Build / typecheck
```bash
npm run build                 # tsc -b && vite build  → dist/
```

## Auth (dev-mode)
MVP uses **role-based dev auth**: the login screen picks a `Role`, sent to the backend
as the `X-Role` header (backend `auth_dev_mode`). Production swaps in OAuth2/JWT —
`apiFetch` already injects `Authorization: Bearer` when an access token is present.
A role switcher in the header lets you exercise the RBAC matrix live.

## Screens (frontend_design_prd 절차)
| Route | 화면 | 최소 권한 |
|---|---|---|
| `/dashboard` | 운영 지표 + 라벨러 비교 + 드리프트 요약 | Viewer |
| `/samples/:sampleId` | L1/L2/L3 라벨 계층 + 계보 | MLEngineer |
| `/reviews`, `/reviews/:id` | 검수 큐 + 분할 검수 패널(→L3) | Reviewer |
| `/drift` | PSI/KL/앵커 차트 + Drift 실행 | Viewer (실행 DataEngineer) |
| `/datasets/build` | Dataset 빌드 폼 | MLEngineer |
| `/fusion/run` | Fusion 트리거 폼 | DataEngineer |

## Layout
```
src/
  app/        App.tsx router.tsx providers.tsx
  api/        client.ts (typed fetch + auth) endpoints.ts (domain APIs)
  components/  StatusBadge MetricCard DataTable ConfidenceBar RationaleViewer
               RoleGate ProtectedRoute AppShell Sidebar Toaster LoadingSkeleton
  features/    dashboard samples reviews drift datasets fusion auth
  hooks/       useAuth useToast
  stores/      authStore uiStore (Zustand)
  lib/         enums constants formatters queryClient
  types/       api.ts (matches backend schemas)
```

## Verified
- `npm run build` passes (tsc strict + vite production build).
- Live wiring confirmed: dev-server proxy → backend; L1 create → 201; dashboard
  reflects counts; RBAC enforced (Viewer write → 403) through the proxy.
