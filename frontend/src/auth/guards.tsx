import { RefreshCw, ServerCrash, ShieldX } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, Navigate, Outlet, useLocation } from 'react-router'
import { Card, Spinner, buttonStyles } from '../components/ui'
import type { Role } from '../types'
import { useAuth } from './AuthContext'

/** Renders child routes only for signed-in users; otherwise redirects to /login. */
export function RequireAuth() {
  const { state, retrySession, logout } = useAuth()
  const location = useLocation()

  if (state.status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Checking your session…" />
      </div>
    )
  }
  if (state.status === 'unreachable') {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <Card className="max-w-md p-8 text-center">
          <ServerCrash className="mx-auto size-8 text-slate-400" />
          <h1 className="mt-3 text-lg font-semibold text-slate-900">Can’t reach the NidhiSec server</h1>
          <p className="mt-1 text-sm text-slate-600">
            Your session is still saved in this tab. Check that the backend is running, then try again.
          </p>
          <div className="mt-5 flex justify-center gap-2">
            <button type="button" className={buttonStyles.primary} onClick={retrySession}><RefreshCw className="size-4" /> Try again</button>
            <button type="button" className={buttonStyles.secondary} onClick={() => logout()}>Sign out</button>
          </div>
        </Card>
      </div>
    )
  }
  if (state.status === 'anonymous') {
    // After an explicit sign-out, don't send the next user back to the previous user's page.
    const from = state.signedOut ? undefined : location.pathname + location.search
    return <Navigate to="/login" replace state={from ? { from } : null} />
  }
  return <Outlet />
}

/**
 * Hides screens a role cannot use. This is a usability measure only: the
 * backend enforces every permission independently.
 */
export function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { hasRole } = useAuth()
  if (hasRole(...roles)) return <>{children}</>
  return (
    <Card className="p-8 text-center">
      <ShieldX className="mx-auto size-8 text-slate-400" />
      <h2 className="mt-3 text-lg font-semibold text-slate-900">Not available for your role</h2>
      <p className="mt-1 text-sm text-slate-600">Your account does not have access to this page.</p>
      <Link to="/" className="mt-6 inline-block text-sm font-medium text-navy-600 hover:text-navy-800">
        ← Back to dashboard
      </Link>
    </Card>
  )
}
