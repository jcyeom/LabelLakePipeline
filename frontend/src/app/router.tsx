import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { LoginPage } from '@/features/auth/LoginPage'
import { DashboardPage } from '@/features/dashboard/DashboardPage'
import { SampleDetailPage } from '@/features/samples/SampleDetailPage'
import { ReviewQueuePage } from '@/features/reviews/ReviewQueuePage'
import { ReviewDetailPage } from '@/features/reviews/ReviewDetailPage'
import { DriftPage } from '@/features/drift/DriftPage'
import { DatasetBuilderPage } from '@/features/datasets/DatasetBuilderPage'
import { FusionRunPage } from '@/features/fusion/FusionRunPage'

export const router = createBrowserRouter([
  { path: '/auth/login', element: <LoginPage /> },
  {
    element: (
      <ProtectedRoute minRole="Viewer">
        <AppShell />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: '/dashboard', element: <DashboardPage /> },
      {
        path: '/samples/:sampleId',
        element: (
          <ProtectedRoute minRole="MLEngineer">
            <SampleDetailPage />
          </ProtectedRoute>
        ),
      },
      {
        path: '/reviews',
        element: (
          <ProtectedRoute minRole="Reviewer">
            <ReviewQueuePage />
          </ProtectedRoute>
        ),
      },
      {
        path: '/reviews/:reviewId',
        element: (
          <ProtectedRoute minRole="Reviewer">
            <ReviewDetailPage />
          </ProtectedRoute>
        ),
      },
      {
        // Viewer+ may view drift metrics (README §6: GET /drift/metrics = Viewer+).
        // Running drift / Gold republish inside the page are RoleGated to DataEngineer/Admin.
        path: '/drift',
        element: (
          <ProtectedRoute minRole="Viewer">
            <DriftPage />
          </ProtectedRoute>
        ),
      },
      {
        path: '/datasets/build',
        element: (
          <ProtectedRoute minRole="MLEngineer">
            <DatasetBuilderPage />
          </ProtectedRoute>
        ),
      },
      {
        path: '/fusion/run',
        element: (
          <ProtectedRoute minRole="DataEngineer">
            <FusionRunPage />
          </ProtectedRoute>
        ),
      },
    ],
  },
  { path: '*', element: <Navigate to="/dashboard" replace /> },
])
