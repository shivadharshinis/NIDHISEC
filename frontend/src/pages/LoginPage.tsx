import { Loader2, LogIn } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useAuth } from '../auth/AuthContext'
import BrandMark from '../components/BrandMark'
import { Alert, Field, buttonStyles, inputStyles } from '../components/ui'
import { ApiError } from '../lib/api'

export default function LoginPage() {
  const { state, login } = useAuth()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const from = (location.state as { from?: string } | null)?.from ?? '/'
  if (state.status === 'authenticated') return <Navigate to={from} replace />

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!email.trim() || !password) {
      setError('Enter your email address and password.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await login(email.trim(), password)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Sign-in failed. Please try again.')
      setPassword('')
    } finally {
      setSubmitting(false)
    }
  }

  const notice = state.status === 'anonymous' ? state.notice : undefined

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 lg:flex-row">
      <aside className="bg-gradient-to-br from-navy-800 to-navy-950 px-6 py-8 text-white sm:px-10 lg:flex lg:w-[42%] lg:flex-col lg:justify-between lg:py-12">
        <div className="flex items-center gap-3">
          <BrandMark className="size-10" />
          <div>
            <p className="text-xl font-semibold tracking-tight">NidhiSec</p>
            <p className="text-xs text-navy-200">AICTE FDR Management Portal</p>
          </div>
        </div>
        <div className="mt-8 hidden lg:block">
          <p className="text-xs font-semibold tracking-wider text-sky-300 uppercase">
            AICTE Security Deposit / FDR Management Portal
          </p>
          <p className="mt-3 max-w-md text-2xl leading-snug font-semibold">
            Lifecycle management of security deposits held as Fixed Deposit Receipts.
          </p>
          <p className="mt-3 max-w-md text-sm text-navy-200">
            For institutions, bank officers and AICTE officials. Access is limited to authorised accounts.
          </p>
        </div>
        <p className="mt-8 hidden text-xs text-navy-300 lg:block">Development prototype — not for use with real records.</p>
      </aside>

      <main className="flex flex-1 items-center justify-center px-4 py-10 sm:px-6">
        <div className="w-full max-w-sm">
          <h1 className="text-2xl font-semibold text-slate-900">Sign in</h1>
          <p className="mt-1 text-sm text-slate-600">Use the account issued to you for NidhiSec.</p>

          <div className="mt-6 space-y-4">
            {notice && <Alert tone="info">{notice}</Alert>}
            {error && <Alert tone="error">{error}</Alert>}
          </div>

          <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
            <Field id="email" label="Email address" required>
              <input
                id="email"
                type="email"
                autoComplete="username"
                className={inputStyles}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                maxLength={254}
                required
              />
            </Field>
            <Field id="password" label="Password" required>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                className={inputStyles}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                maxLength={128}
                required
              />
            </Field>
            <button type="submit" className={`${buttonStyles.primary} w-full`} disabled={submitting}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : <LogIn className="size-4" />}
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          {import.meta.env.DEV && (
            <p className="mt-8 rounded-md border border-dashed border-slate-300 p-3 text-xs leading-relaxed text-slate-500">
              <strong className="text-slate-600">Development:</strong> fictional demo accounts are created with{' '}
              <code className="rounded bg-slate-100 px-1">python -m app.cli seed-demo</code>. Their generated passwords
              are saved in <code className="rounded bg-slate-100 px-1">backend/data/dev-credentials.txt</code>.
            </p>
          )}
        </div>
      </main>
    </div>
  )
}
