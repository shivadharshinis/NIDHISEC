import { CircleAlert, CircleCheck, Loader2, RefreshCw, TriangleAlert } from 'lucide-react'
import { API_BASE_URL } from '../config'
import { useBackendHealth } from '../hooks/useBackendHealth'

const timeFormat = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export default function BackendStatus() {
  const { state, isChecking, recheck } = useBackendHealth()

  const tone = {
    loading: { ring: 'border-slate-200', dot: 'bg-slate-400', label: 'Checking connection…', text: 'text-slate-600' },
    online: { ring: 'border-emerald-200', dot: 'bg-emerald-500', label: 'Connected', text: 'text-emerald-700' },
    degraded: { ring: 'border-amber-200', dot: 'bg-amber-500', label: 'Degraded', text: 'text-amber-700' },
    offline: { ring: 'border-red-200', dot: 'bg-red-500', label: 'Unavailable', text: 'text-red-700' },
  }[state.kind]

  return (
    <section className={`rounded-lg border bg-white p-5 shadow-sm ${tone.ring}`} aria-labelledby="backend-status-title">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="backend-status-title" className="text-sm font-semibold text-slate-900">
            Backend connection
          </h2>
          <p className="mt-0.5 text-xs break-all text-slate-500">{API_BASE_URL}/health</p>
        </div>
        <button
          type="button"
          onClick={() => void recheck()}
          disabled={isChecking}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw className={`size-3.5 ${isChecking ? 'animate-spin' : ''}`} />
          Re-check
        </button>
      </div>

      <div className="mt-4 flex items-center gap-2" role="status" aria-live="polite">
        {state.kind === 'loading' ? (
          <Loader2 className="size-5 animate-spin text-slate-400" />
        ) : state.kind === 'online' ? (
          <CircleCheck className="size-5 text-emerald-600" />
        ) : state.kind === 'degraded' ? (
          <TriangleAlert className="size-5 text-amber-600" />
        ) : (
          <CircleAlert className="size-5 text-red-600" />
        )}
        <span className={`text-sm font-semibold ${tone.text}`}>{tone.label}</span>
        <span className={`ml-auto size-2 rounded-full ${tone.dot}`} aria-hidden="true" />
      </div>

      {(state.kind === 'online' || state.kind === 'degraded') && (
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <dt className="text-slate-500">Service</dt>
          <dd className="text-right font-medium text-slate-800">{state.data.service}</dd>
          <dt className="text-slate-500">Version</dt>
          <dd className="text-right font-medium text-slate-800">{state.data.version}</dd>
          <dt className="text-slate-500">Database</dt>
          <dd className={`text-right font-medium ${state.data.database === 'ok' ? 'text-emerald-700' : 'text-red-700'}`}>
            {state.data.database === 'ok' ? 'Reachable' : 'Error'}
          </dd>
          <dt className="text-slate-500">Environment</dt>
          <dd className="text-right font-medium text-slate-800">{state.data.environment}</dd>
        </dl>
      )}

      {state.kind === 'offline' && (
        <div className="mt-3 rounded-md bg-red-50 p-3 text-xs text-red-800">
          <p className="font-medium">{state.error}.</p>
          <p className="mt-1 text-red-700">
            Make sure the FastAPI server is running on port 8000 and that this origin is allowed by its CORS settings.
          </p>
        </div>
      )}

      {state.kind !== 'loading' && (
        <p className="mt-3 text-[11px] text-slate-400">Last checked {timeFormat.format(state.checkedAt)}</p>
      )}
    </section>
  )
}
