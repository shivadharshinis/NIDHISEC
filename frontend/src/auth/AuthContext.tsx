import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { apiGet, apiRequest, setAuthToken, setUnauthorizedHandler } from '../lib/api'
import type { Role, TokenResponse, User } from '../types'

// sessionStorage: the session ends when the tab closes. See README "Security limitations".
const STORAGE_KEY = 'nidhisec.session'

interface StoredSession {
  token: string
  expiresAt: string
}

type AuthState =
  | { status: 'loading' }
  // signedOut: the user chose to sign out, so the next login starts fresh at the dashboard.
  | { status: 'anonymous'; notice?: string; signedOut?: boolean }
  | { status: 'authenticated'; user: User; expiresAt: string }

interface AuthContextValue {
  state: AuthState
  user: User | null
  login: (email: string, password: string) => Promise<void>
  /** Ends the session. Pass a notice when the session ended for the user (e.g. expiry). */
  logout: (notice?: string) => void
  hasRole: (...roles: Role[]) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

function readSession(): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const session = JSON.parse(raw) as StoredSession
    return new Date(session.expiresAt).getTime() > Date.now() ? session : null
  } catch {
    return null
  }
}

function writeSession(session: StoredSession | null) {
  try {
    if (session) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    else sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // Storage unavailable (e.g. privacy mode): the session lives in memory only.
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' })

  const logout = useCallback((notice?: string) => {
    writeSession(null)
    setAuthToken(null)
    setState({ status: 'anonymous', notice, signedOut: notice === undefined })
  }, [])

  // Restore a session from this tab, validating it with the backend.
  useEffect(() => {
    const session = readSession()
    if (!session) {
      writeSession(null)
      setState({ status: 'anonymous' })
      return
    }
    setAuthToken(session.token)
    const controller = new AbortController()
    apiGet<User>('/auth/me', { signal: controller.signal })
      .then((user) => setState({ status: 'authenticated', user, expiresAt: session.expiresAt }))
      .catch(() => {
        if (!controller.signal.aborted) logout()
      })
    return () => controller.abort()
  }, [logout])

  // Any 401 from the API ends the session.
  useEffect(() => {
    setUnauthorizedHandler(() => logout('Your session has expired. Please sign in again.'))
    return () => setUnauthorizedHandler(null)
  }, [logout])

  // Sign out when the token expires.
  const expiresAt = state.status === 'authenticated' ? state.expiresAt : null
  useEffect(() => {
    if (!expiresAt) return
    const ms = new Date(expiresAt).getTime() - Date.now()
    const timer = window.setTimeout(() => logout('Your session has expired. Please sign in again.'), Math.max(ms, 0))
    return () => window.clearTimeout(timer)
  }, [expiresAt, logout])

  const login = useCallback(async (email: string, password: string) => {
    const result = await apiRequest<TokenResponse>('/auth/login', {
      method: 'POST',
      body: { email, password },
      anonymous: true,
    })
    writeSession({ token: result.access_token, expiresAt: result.expires_at })
    setAuthToken(result.access_token)
    setState({ status: 'authenticated', user: result.user, expiresAt: result.expires_at })
  }, [])

  const value = useMemo<AuthContextValue>(() => {
    const user = state.status === 'authenticated' ? state.user : null
    return {
      state,
      user,
      login,
      logout,
      hasRole: (...roles: Role[]) => user !== null && roles.includes(user.role),
    }
  }, [state, login, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}

/** For components rendered only inside authenticated routes. */
export function useCurrentUser(): User {
  const { user } = useAuth()
  if (!user) throw new Error('useCurrentUser requires a signed-in user')
  return user
}
