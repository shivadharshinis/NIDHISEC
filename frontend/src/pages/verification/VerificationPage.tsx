import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useCurrentUser } from '../../auth/AuthContext'
import { Alert, Card, PageHeader, Spinner, StatusBadge, buttonStyles } from '../../components/ui'
import { AssignmentStatusBadge, OUTCOME_DISCLAIMER, OutcomeBadge } from '../../components/verification/VerificationPanel'
import { useApiQuery } from '../../hooks/useApiQuery'
import { toQuery } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type { AssignmentQueueItem, AssignmentStatus, AwaitingDecisionItem, BankCaseSummary, Page } from '../../types'

const PAGE_SIZE = 20

function Tabs<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="flex flex-wrap gap-1 rounded-lg border border-slate-200 bg-white p-1" role="tablist">
      {options.map(([key, label]) => (
        <button
          key={key}
          type="button"
          role="tab"
          aria-selected={value === key}
          onClick={() => onChange(key)}
          className={`rounded-md px-3 py-1.5 text-sm font-medium ${value === key ? 'bg-navy-700 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

function Pager({ page, pages, total, onPage }: { page: number; pages: number; total: number; onPage: (p: number) => void }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3 text-sm text-slate-600">
      <span>{total} case{total === 1 ? '' : 's'} · page {page} of {Math.max(pages, 1)}</span>
      <div className="flex gap-2">
        <button type="button" className={buttonStyles.secondary} disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft className="size-4" /> Previous
        </button>
        <button type="button" className={buttonStyles.secondary} disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next <ChevronRight className="size-4" />
        </button>
      </div>
    </div>
  )
}

/** FDRs whose bank outcome awaits an AICTE decision; same definition as the dashboard count. */
function AwaitingDecision() {
  const [page, setPage] = useState(1)
  const result = useApiQuery<Page<AwaitingDecisionItem>>(`/verification/awaiting-decision${toQuery({ page, page_size: PAGE_SIZE })}`)
  const data = result.data
  return (
    <>
      <p className="text-sm text-slate-600">
        A bank officer has recorded an outcome since your last decision on these records, oldest first. Open a record to read the
        outcome and record your decision in its review panel. Nothing here is decided automatically.
      </p>
      {result.status === 'error' && (
        <Alert tone="error" title="Could not load the review queue" action={<button type="button" className={buttonStyles.secondary} onClick={result.reload}>Try again</button>}>
          {result.error.message}
        </Alert>
      )}
      {result.status === 'loading' && !data && <Spinner label="Loading review queue…" />}
      {data && data.total === 0 && <Card className="p-10 text-center text-sm text-slate-600">No bank outcome is awaiting your decision.</Card>}
      {data && data.total > 0 && (
        <Card className={result.status === 'loading' ? 'opacity-60' : ''}>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold tracking-wide text-slate-600 uppercase">
                <tr>
                  <th scope="col" className="px-4 py-3">FDR</th>
                  <th scope="col" className="px-4 py-3">Institution</th>
                  <th scope="col" className="px-4 py-3">Bank outcome</th>
                  <th scope="col" className="px-4 py-3">Recorded</th>
                  <th scope="col" className="px-4 py-3">Review status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((item) => (
                  <tr key={item.fdr_id} className="align-top hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <Link to={`/fdr-records/${item.fdr_id}`} className="font-medium text-navy-700 hover:underline">{item.fdr_number}</Link>
                      <div className="text-xs text-slate-500">{item.bank_name}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-700">{item.institution.code}</td>
                    <td className="px-4 py-3"><OutcomeBadge outcome={item.outcome} /><div className="mt-1 text-xs text-slate-500">by {item.officer.full_name}</div></td>
                    <td className="px-4 py-3 whitespace-nowrap text-slate-700">{formatDateTime(item.outcome_submitted_at)}</td>
                    <td className="px-4 py-3"><StatusBadge status={item.fdr_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
        </Card>
      )}
    </>
  )
}

type AicteView = AssignmentStatus | 'ALL' | 'AWAITING'

function AicteQueue() {
  const [params, setParams] = useSearchParams()
  const status: AicteView = params.get('view') === 'awaiting' ? 'AWAITING' : ((params.get('status') as AicteView | null) ?? 'ACTIVE')
  const setStatus = (view: AicteView) => setParams(view === 'AWAITING' ? { view: 'awaiting' } : { status: view }, { replace: true })
  const [page, setPage] = useState(1)
  const result = useApiQuery<Page<AssignmentQueueItem>>(
    status === 'AWAITING' ? null : `/verification/assignments${toQuery({ status: status === 'ALL' ? '' : status, page, page_size: PAGE_SIZE })}`,
  )
  const data = status === 'AWAITING' ? undefined : result.data

  return (
    <div className="space-y-5">
      <PageHeader
        title="Verification"
        description="Bank verification assignments across all institutions. Assign new cases from an FDR’s record page."
      />
      <Tabs
        value={status}
        onChange={(v) => { setStatus(v); setPage(1) }}
        options={[['AWAITING', 'Awaiting your decision'], ['ACTIVE', 'Active'], ['COMPLETED', 'Outcome recorded'], ['SUPERSEDED', 'Reassigned'], ['CANCELLED', 'Cancelled'], ['ALL', 'All']]}
      />
      {status === 'AWAITING' && <AwaitingDecision />}
      {status !== 'AWAITING' && result.status === 'error' && (
        <Alert tone="error" title="Could not load assignments" action={<button type="button" className={buttonStyles.secondary} onClick={result.reload}>Try again</button>}>
          {result.error.message}
        </Alert>
      )}
      {status !== 'AWAITING' && result.status === 'loading' && !data && <Spinner label="Loading assignments…" />}
      {data && data.total === 0 && (
        <Card className="p-10 text-center text-sm text-slate-600">
          No assignments here. Open an FDR in <Link to="/fdr-records" className="font-medium text-navy-600">FDR Records</Link> to assign it to a bank officer.
        </Card>
      )}
      {data && data.total > 0 && (
        <Card className={result.status === 'loading' ? 'opacity-60' : ''}>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold tracking-wide text-slate-600 uppercase">
                <tr>
                  <th scope="col" className="px-4 py-3">FDR</th>
                  <th scope="col" className="px-4 py-3">Institution</th>
                  <th scope="col" className="px-4 py-3">Bank officer</th>
                  <th scope="col" className="px-4 py-3">Assigned</th>
                  <th scope="col" className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((item) => (
                  <tr key={item.id} className="align-top hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <Link to={`/fdr-records/${item.fdr_id}`} className="font-medium text-navy-700 hover:underline">{item.fdr_number}</Link>
                      <div className="text-xs text-slate-500">{item.bank_name}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-700">{item.institution.code}</td>
                    <td className="px-4 py-3 text-slate-700">{item.bank_officer.full_name}</td>
                    <td className="px-4 py-3 whitespace-nowrap text-slate-700">{formatDateTime(item.assigned_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-col items-start gap-1">
                        <AssignmentStatusBadge status={item.status} />
                        {item.outcome && <OutcomeBadge outcome={item.outcome} />}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
        </Card>
      )}
    </div>
  )
}

function OfficerCases() {
  const [state, setState] = useState<'active' | 'closed'>('active')
  const [page, setPage] = useState(1)
  const result = useApiQuery<Page<BankCaseSummary>>(`/verification/cases${toQuery({ state, page, page_size: PAGE_SIZE })}`)
  const data = result.data

  return (
    <div className="space-y-5">
      <PageHeader title="My verification cases" description="FDRs assigned to you by AICTE. You can open a case only while it is assigned to you." />
      <Alert tone="info">{OUTCOME_DISCLAIMER}</Alert>
      <Tabs value={state} onChange={(v) => { setState(v); setPage(1) }} options={[['active', 'Assigned to me'], ['closed', 'My case history']]} />
      {result.status === 'error' && (
        <Alert tone="error" title="Could not load your cases" action={<button type="button" className={buttonStyles.secondary} onClick={result.reload}>Try again</button>}>
          {result.error.message}
        </Alert>
      )}
      {result.status === 'loading' && !data && <Spinner label="Loading cases…" />}
      {data && data.total === 0 && (
        <Card className="p-10 text-center text-sm text-slate-600">
          {state === 'active' ? 'No cases are assigned to you right now.' : 'You have no closed cases yet.'}
        </Card>
      )}
      {data && data.total > 0 && (
        <Card className={result.status === 'loading' ? 'opacity-60' : ''}>
          <ul className="divide-y divide-slate-100">
            {data.items.map((item) => (
              <li key={item.id}>
                <Link to={`/verification/cases/${item.id}`} className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-slate-50">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-navy-700">{item.fdr_number}</p>
                    <p className="text-xs text-slate-600">{item.bank_name} · {item.institution.name} ({item.institution.code})</p>
                    <p className="text-xs text-slate-500">Assigned {formatDateTime(item.assigned_at)}</p>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <AssignmentStatusBadge status={item.status} />
                    {item.outcome && <OutcomeBadge outcome={item.outcome} />}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          <Pager page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
        </Card>
      )}
    </div>
  )
}

export default function VerificationPage() {
  const user = useCurrentUser()
  return user.role === 'BANK_OFFICER' ? <OfficerCases /> : <AicteQueue />
}
