import { useCallback, useEffect, useState } from 'react'
import { ApiError, apiGet } from '../lib/api'

export type QueryState<T> =
  | { status: 'loading'; data?: T }
  | { status: 'error'; error: ApiError; data?: T }
  | { status: 'success'; data: T }

/** GET `path` (null = skip) and track loading / error / success. Re-fetches when `path` changes. */
export function useApiQuery<T>(path: string | null) {
  const [state, setState] = useState<QueryState<T>>({ status: 'loading' })
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    if (path === null) return
    const controller = new AbortController()
    // Keep showing previous data while refreshing (e.g. when paging).
    setState((previous) => ({ status: 'loading', data: previous.data }))
    apiGet<T>(path, { signal: controller.signal })
      .then((data) => setState({ status: 'success', data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        const apiError = error instanceof ApiError ? error : new ApiError('Unexpected error')
        setState((previous) => ({ status: 'error', error: apiError, data: previous.data }))
      })
    return () => controller.abort()
  }, [path, reloadKey])

  const reload = useCallback(() => setReloadKey((key) => key + 1), [])
  return { ...state, reload }
}
