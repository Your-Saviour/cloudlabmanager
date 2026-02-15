import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useAuthStore } from '@/stores/authStore'
import { useAuthStatus, useCurrentUser, useInventoryTypes } from '@/hooks/useAuth'
import { AppLayout } from '@/components/layout/AppLayout'
import { Skeleton } from '@/components/ui/skeleton'

// Pages
import LoginPage from '@/pages/auth/LoginPage'
import SetupPage from '@/pages/auth/SetupPage'
import AcceptInvitePage from '@/pages/auth/AcceptInvitePage'
import ForgotPasswordPage from '@/pages/auth/ForgotPasswordPage'
import ResetPasswordPage from '@/pages/auth/ResetPasswordPage'
import DashboardPage from '@/pages/dashboard/DashboardPage'
import InventoryHubPage from '@/pages/inventory/InventoryHubPage'
import InventoryDetailPage from '@/pages/inventory/InventoryDetailPage'
import InventoryCreatePage from '@/pages/inventory/InventoryCreatePage'
import JobsListPage from '@/pages/jobs/JobsListPage'
import JobDetailPage from '@/pages/jobs/JobDetailPage'
import ServicesPage from '@/pages/services/ServicesPage'
import ServiceConfigPage from '@/pages/services/ServiceConfigPage'
import ServiceFilesPage from '@/pages/services/ServiceFilesPage'
import SSHTerminalPage from '@/pages/ssh/SSHTerminalPage'
import UsersPage from '@/pages/users/UsersPage'
import RolesPage from '@/pages/roles/RolesPage'
import RoleEditPage from '@/pages/roles/RoleEditPage'
import AuditLogPage from '@/pages/audit/AuditLogPage'
import ProfilePage from '@/pages/profile/ProfilePage'
import CostsPage from '@/pages/costs/CostsPage'
import SchedulesPage from '@/pages/schedules/SchedulesPage'
import HealthPage from '@/pages/health/HealthPage'
import DriftPage from '@/pages/drift/DriftPage'
import NotificationRulesPage from '@/pages/notifications/NotificationRulesPage'
import PortalPage from '@/pages/portal/PortalPage'
import WebhooksPage from '@/pages/webhooks/WebhooksPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

function AuthGuard({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  const location = useLocation()
  const { data: status, isLoading: statusLoading } = useAuthStatus()

  useCurrentUser()
  useInventoryTypes()

  if (statusLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="space-y-4 w-64">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      </div>
    )
  }

  if (status && !status.setup_complete) {
    return <Navigate to="/setup" replace />
  }

  if (!token) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}

function AppRoutes() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/accept-invite/:token" element={<AcceptInvitePage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password/:token" element={<ResetPasswordPage />} />

      {/* Protected routes */}
      <Route
        element={
          <AuthGuard>
            <AppLayout />
          </AuthGuard>
        }
      >
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/inventory" element={<InventoryHubPage />} />
        <Route path="/inventory/tags" element={<InventoryHubPage />} />
        <Route path="/inventory/:typeSlug" element={<InventoryHubPage />} />
        <Route path="/inventory/:typeSlug/new" element={<InventoryCreatePage />} />
        <Route path="/inventory/:typeSlug/:objId" element={<InventoryDetailPage />} />
        <Route path="/jobs" element={<JobsListPage />} />
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
        <Route path="/schedules" element={<SchedulesPage />} />
        <Route path="/webhooks" element={<WebhooksPage />} />
        <Route path="/services" element={<ServicesPage />} />
        <Route path="/services/:name/config" element={<ServiceConfigPage />} />
        <Route path="/services/:name/files" element={<ServiceFilesPage />} />
        <Route path="/ssh/:hostname/:ip" element={<SSHTerminalPage />} />
        <Route path="/ssh/:hostname/:ip/:user" element={<SSHTerminalPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/roles" element={<RolesPage />} />
        <Route path="/roles/:roleId" element={<RoleEditPage />} />
        <Route path="/audit" element={<AuditLogPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/costs" element={<CostsPage />} />
        <Route path="/health" element={<HealthPage />} />
        <Route path="/drift" element={<DriftPage />} />
        <Route path="/notifications/rules" element={<NotificationRulesPage />} />
        <Route path="/portal" element={<PortalPage />} />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
      </Route>

      {/* Catch-all */}
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <BrowserRouter>
          <AppRoutes />
          <Toaster
            position="bottom-right"
            theme="dark"
            toastOptions={{
              style: {
                background: 'hsl(240, 12%, 8%)',
                border: '1px solid hsl(240, 8%, 16%)',
                color: 'hsl(210, 20%, 92%)',
              },
            }}
          />
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  )
}
