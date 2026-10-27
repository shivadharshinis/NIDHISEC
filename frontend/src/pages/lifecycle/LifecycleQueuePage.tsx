import { ChevronLeft, ChevronRight, Loader2, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { useCurrentUser } from '../../auth/AuthContext'
import { RequestStatusBadge } from '../../components/lifecycle/LifecyclePanel'
import { Alert, Card, PageHeader, Spinner, StatusBadge, buttonStyles, inputStyles } from '../../components/ui'
import { useApiQuery } from '../../hooks/useApiQuery'
import { ApiError, apiRequest, toQuery } from '../../lib/api'
import { describeDays, formatDate, formatDateTime, REQUEST_STATUS_LABELS, REQUEST_TYPE_LABELS } from '../../lib/format'
import type { LifecycleCheckResult, LifecycleRequestRead, LifecycleRequestType, MaturityItem, Page } from '../../types'

function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (p: number) => void }) {
  if (pages <= 1) return null
  return (
    <div className="flex justify-end gap-2 border-t border-slate-200 px-4 py-3">
      <button type="button" className={buttonStyles.secondary} disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft className="size-4" /> Previous</button>
      <button type="button" className={buttonStyles.secondary} disabled={page >= pages} onClick={() => onPage(page + 1)}>Next <ChevronRight className="size-4" /></button>
    </div>
  )
}

function MaturitySection() {
  const user = useCurrentUser()
  const isAicte = user.role === 'AICTE_OFFICIAL'
  const [within, setWithin] = useState(30)
  const [page, setPage] = useState(1)
  const [key, setKey] = useState(0)
  const result = useApiQuery<Page<MaturityItem>>(`/lifecycle/maturity${toQuery({ within_days: within, page, page_size: 25, k: key })}`)
  const [checking, setChecking] = useState(false)
  const [checkResult, setCheckResult] = useState<LifecycleCheckResult | null>(null)
  const [checkError, setCheckError] = useState<string | null>(null)
  const data = result.data

  async function runCheck() {
    setChecking(true)
    setCheckError(null)
    try {
      setCheckResult(await apiRequest<LifecycleCheckResult>('/lifecycle/check', { method: 'POST' }))
      setKey((k) => k + 1)
    } catch (err) {
      setCheckError(err instanceof ApiError ? err.message : 'The maturity check failed.')
    } finally {
      setChecking(false)
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Maturity</h3>
          <p className="text-xs text-slate-600">Active instruments that have matured or mature soon. Dates use Indian Standard Time.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select aria-label="Window" className={inputStyles} value={within} onChange={(e) => { setWithin(Number(e.target.value)); setPage(1) }}>
            {[7, 15, 30, 90, 365].map((d) => <option key={d} value={d}>Matured or due within {d} days</option>)}
          </select>
          {isAicte && (
            <button type="button" className={buttonStyles.secondary} onClick={runCheck} disabled={checking}>
              {checking ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />} Run maturity check
            </button>
          )}
        </div>
      </div>
      {checkError && <Alert tone="error">{checkError}</Alert>}
      {checkResult && (
        <Alert tone="info">
          Maturity check for {formatDate(checkResult.date)}: {checkResult.due} due, {checkResult.matured} matured,{' '}
          {checkResult.notifications_created} new notification(s). Running it again does not create duplicates.
        </Alert>
      )}
      {result.status === 'error' && <Alert tone="error">{result.error.message}</Alert>}
      {result.status === 'loading' && !data && <Spinner />}
      {data && data.total === 0 && <Card className="p-6 text-center text-sm text-slate-600">Nothing matures within {within} days.</Card>}
      {data && data.total > 0 && (
        <Card>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold tracking-wide text-slate-600 uppercase">
                <tr><th className="px-4 py-3">FDR</th>{isAicte && <th className="px-4 py-3">Institution</th>}<th className="px-4 py-3">Maturity</th>
                  <th className="px-4 py-3">Timing</th><th className="px-4 py-3">Review status</th><th className="px-4 py-3">Open request</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((item) => (
                  <tr key={item.fdr_id}>
                    <td className="px-4 py-3"><Link to={`/fdr-records/${item.fdr_id}`} className="font-medium text-navy-700 hover:underline">{item.fdr_number}</Link>
                      <div className="text-xs text-slate-500">{item.bank_name}</div></td>
                    {isAicte && <td className="px-4 py-3 text-slate-700">{item.institution.code}</td>}
                    <td className="px-4 py-3 whitespace-nowrap">{formatDate(item.maturity_date)}</td>
                    <td className={`px-4 py-3 whitespace-nowrap ${item.state === 'MATURED' ? 'text-red-700' : item.state === 'DUE' ? 'text-amber-700' : 'text-slate-700'}`}>
                      {item.state === 'MATURED' ? 'Matured — ' : ''}{describeDays(item.days_remaining)}</td>
                    <td className="px-4 py-3"><StatusBadge status={item.status} /></td>
                    <td className="px-4 py-3 text-xs text-slate-700">{item.open_request_type ? REQUEST_TYPE_LABELS[item.open_request_type] : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={data.page} pages={data.pages} onPage={setPage} />
        </Card>
      )}
    </section>
  )
}

function RequestsSection({ types }: { types: LifecycleRequestType[] }) {
  const user = useCurrentUser()
  const isAicte = user.role === 'AICTE_OFFICIAL'
  const [status, setStatus] = useState(isAicte ? 'SUBMITTED,UNDER_REVIEW' : '')
  const [page, setPage] = useState(1)
  const result = useApiQuery<Page<LifecycleRequestRead>>(
    `/lifecycle-requests${toQuery({ type: types, status: status ? status.split(',') : [], page, page_size: 20 })}`,
  )
  const data = result.data
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{types.map((t) => REQUEST_TYPE_LABELS[t]).join(' and ')} requests</h3>
          <p className="text-xs text-slate-600">{isAicte ? 'Requests from all institutions.' : 'Your institution’s requests. Start a new one from an FDR’s record page.'}</p>
        </div>
        <select aria-label="Status" className={inputStyles} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
          <option value="SUBMITTED,UNDER_REVIEW">Awaiting AICTE decision</option>
          <option value="CLARIFICATION_REQUESTED">Clarification requested</option>
          <option value="APPROVED">Approved — awaiting completion</option>
          <option value="COMPLETED,REJECTED,WITHDRAWN">Closed</option>
          <option value="">All</option>
        </select>
      </div>
      {result.status === 'error' && <Alert tone="error">{result.error.message}</Alert>}
      {result.status === 'loading' && !data && <Spinner />}
      {data && data.total === 0 && <Card className="p-6 text-center text-sm text-slate-600">No requests here.</Card>}
      {data && data.total > 0 && (
        <Card>
          <ul className="divide-y divide-slate-100">
            {data.items.map((r) => (
              <li key={r.id}>
                <Link to={`/lifecycle-requests/${r.id}`} className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-slate-50">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-navy-700">{REQUEST_TYPE_LABELS[r.request_type]} #{r.id} · FDR {r.fdr.fdr_number}</p>
                    <p className="text-xs text-slate-600">{isAicte && `${r.institution.code} · `}submitted {formatDateTime(r.created_at)}{r.successor && ` · new instrument ${r.successor.fdr_number}`}</p>
                  </div>
                  <RequestStatusBadge status={r.status} />
                </Link>
              </li>
            ))}
          </ul>
          <Pager page={data.page} pages={data.pages} onPage={setPage} />
        </Card>
      )}
    </section>
  )
}

export default function LifecycleQueuePage({ kind }: { kind: 'renewals' | 'release' }) {
  return kind === 'renewals' ? (
    <div className="space-y-6">
      <PageHeader title="Renewals & Maturity" description="Maturity tracking and renewal/replacement requests. Nothing changes automatically when an FDR matures." />
      <MaturitySection />
      <RequestsSection types={['RENEWAL', 'REPLACEMENT']} />
    </div>
  ) : (
    <div className="space-y-6">
      <PageHeader title="Release Requests" description={`Requests to release or refund security deposits. ${REQUEST_STATUS_LABELS.APPROVED} means a decision was made; completion is recorded separately and is an administrative record only.`} />
      <RequestsSection types={['RELEASE']} />
    </div>
  )
}
