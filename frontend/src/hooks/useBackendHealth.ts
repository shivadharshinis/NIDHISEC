import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet } from '../lib/api'

/** Mirrors backend/app/schemas/health.py */
export interface HealthResponse {
  status: 'ok' | 'degraded'
  service: string
  description: string
  version: string
  environment: string
  database: 'ok' | 'error'
  timestamp: string
}

export type HealthState =
  | { kind: 'loading' }
  | { kind: 'online'; data: HealthResponse; checkedAt: Date }
  | { kind: 'degraded'; data: HealthResponse; checkedAt: Date }
  | { kind: 'offline'; error: string; checkedAt: Date }

const POLL_INTERVAL_MS = 30_000

/** Polls GET /health and reports the real backend connection state. */
export function useBackendHealth() {
  const [state, setState] = useState<HealthState>({ kind: 'loading' })
  const [isChecking, setIsChecking] = useState(true)
  const inFlight = useRef<AbortController | null>(null)

  const check = useCallback(async () => {
    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller
    setIsChecking(true)

    try {
      const data = await apiGet<HealthResponse>('/health', { signal: controller.signal, anonymous: true, timeoutMs: 8000 })
      if (controller.signal.aborted) return
      setState({ kind: data.status === 'ok' ? 'online' : 'degraded', data, checkedAt: new Date() })
    } catch (error) {
      if (controller.signal.aborted) return
      setState({
        kind: 'offline',
        error: error instanceof Error ? error.message : 'Unknown error',
        checkedAt: new Date(),
      })
    } finally {
      if (inFlight.current === controller) {
        inFlight.current = null
        setIsChecking(false)
      }
    }
  }, [])

  useEffect(() => {
    void check()
    const interval = window.setInterval(() => void check(), POLL_INTERVAL_MS)
    return () => {
      window.clearInterval(interval)
      inFlight.current?.abort()
    }
  }, [check])

  return { state, isChecking, recheck: check }
}
