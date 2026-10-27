import { Route, Routes } from 'react-router'
import { RequireAuth, RequireRole } from './auth/guards'
import AppLayout from './components/layout/AppLayout'
import { NAV_ITEMS } from './navigation'
import AuditLogPage from './pages/AuditLogPage'
import DashboardPage from './pages/DashboardPage'
import FdrDetailPage from './pages/fdrs/FdrDetailPage'
import FdrEditPage from './pages/fdrs/FdrEditPage'
import FdrListPage from './pages/fdrs/FdrListPage'
import FdrNewPage from './pages/fdrs/FdrNewPage'
import LoginPage from './pages/LoginPage'
import NotFoundPage from './pages/NotFoundPage'
import LifecycleQueuePage from './pages/lifecycle/LifecycleQueuePage'
import LifecycleRequestPage from './pages/lifecycle/LifecycleRequestPage'
import NotificationsPage from './pages/NotificationsPage'
import PlaceholderPage from './pages/PlaceholderPage'
import ScreeningQueuePage from './pages/ScreeningQueuePage'
import BankCasePage from './pages/verification/BankCasePage'
import VerificationPage from './pages/verification/VerificationPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />

          <Route path="fdr-records">
            <Route
              index
              element={
                <RequireRole roles={['INSTITUTION', 'AICTE_OFFICIAL']}>
                  <FdrListPage />
                </RequireRole>
              }
            />
            <Route
              path="new"
              element={
                <RequireRole roles={['INSTITUTION']}>
                  <FdrNewPage />
                </RequireRole>
              }
            />
            <Route
              path=":fdrId"
              element={
                <RequireRole roles={['INSTITUTION', 'AICTE_OFFICIAL']}>
                  <FdrDetailPage />
                </RequireRole>
              }
            />
            <Route
              path=":fdrId/edit"
              element={
                <RequireRole roles={['INSTITUTION']}>
                  <FdrEditPage />
                </RequireRole>
              }
            />
          </Route>

          <Route
            path="verification"
            element={
              <RequireRole roles={['AICTE_OFFICIAL', 'BANK_OFFICER']}>
                <VerificationPage />
              </RequireRole>
            }
          />
          <Route
            path="verification/cases/:assignmentId"
            element={
              <RequireRole roles={['BANK_OFFICER']}>
                <BankCasePage />
              </RequireRole>
            }
          />

          <Route
            path="screening"
            element={
              <RequireRole roles={['AICTE_OFFICIAL']}>
                <ScreeningQueuePage />
              </RequireRole>
            }
          />

          <Route
            path="renewals"
            element={
              <RequireRole roles={['INSTITUTION', 'AICTE_OFFICIAL']}>
                <LifecycleQueuePage kind="renewals" />
              </RequireRole>
            }
          />
          <Route
            path="release-requests"
            element={
              <RequireRole roles={['INSTITUTION', 'AICTE_OFFICIAL']}>
                <LifecycleQueuePage kind="release" />
              </RequireRole>
            }
          />
          <Route
            path="lifecycle-requests/:requestId"
            element={
              <RequireRole roles={['INSTITUTION', 'AICTE_OFFICIAL']}>
                <LifecycleRequestPage />
              </RequireRole>
            }
          />
          <Route path="notifications" element={<NotificationsPage />} />

          <Route
            path="audit-logs"
            element={
              <RequireRole roles={['AICTE_OFFICIAL']}>
                <AuditLogPage />
              </RequireRole>
            }
          />

          {NAV_ITEMS.filter((item) => !item.implemented).map((item) => (
            <Route key={item.path} path={item.path} element={<PlaceholderPage item={item} />} />
          ))}
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
