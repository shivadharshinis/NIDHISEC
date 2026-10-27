import { ArrowRight } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useCurrentUser } from '../auth/AuthContext'
import { RequestStatusBadge } from '../components/lifecycle/LifecyclePanel'
import { PriorityBadge } from '../components/screening/ScreeningPanel'
import { OutcomeBadge } from '../components/verification/VerificationPanel'
import { Alert, Card, PageHeader, Spinner, StatusBadge, buttonStyles } from '../components/ui'
import { type QueryState, useApiQuery } from '../hooks/useApiQuery'
import { toQuery } from '../lib/api'
import { formatDate, formatDateTime, REQUEST_TYPE_LABELS } from '../lib/format'
import type {
  AssignmentQueueItem,
  AwaitingDecisionItem,
  FdrDetail,
  FdrListItem,
  LifecycleRequestDetail,
  LifecycleRequestRead,
  MaturityItem,
  Page,
  ScreeningQueueItem,
} from '../types'

const SHOWN = 10
const WORKABLE = ['ACTIVE', 'PROPOSED']

// ---------- shared pieces ----------

function Pill({ className, children }: { className: string; children: ReactNode }) {
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset ${className}`}>{children}</span>
}

/** Deadline urgency from the maturity endpoint's own state and alert window. Not a risk measure. */
function DeadlineBadge({ item }: { item: MaturityItem }) {
  if (item.state === 'MATURED') {
    return <Pill className="bg-red-50 text-red-700 ring-red-200">Deadline: overdue by {-item.days_remaining} day{item.days_remaining === -1 ? '' : 's'}</Pill>
  }
  const text = item.days_remaining === 0 ? 'matures today' : `${item.days_remaining} day${item.days_remaining === 1 ? '' : 's'} left`
  const style = (item.alert_window ?? 99) <= 7 ? 'bg-orange-50 text-orange-800 ring-orange-200' : 'bg-amber-50 text-amber-800 ring-amber-200'
  return <Pill className={style}>Deadline: {text}</Pill>
}

interface SectionProps<T> {
  title: string
  description: string
  query: QueryState<Page<T>> & { reload: () => void }
  filter?: (item: T) => boolean
  sort?: (a: T, b: T) => number
  empty: string
  viewAll?: { to: string; label: string }
  render: (item: T) => ReactNode
  itemKey: (item: T) => string | number
}

function Section<T>({ title, description, query, filter, sort, empty, viewAll, render, itemKey }: SectionProps<T>) {
  const all = query.data?.items ?? []
  const items = (filter ? all.filter(filter) : all).slice().sort(sort ?? (() => 0))
  const truncated = (query.data?.total ?? 0) > all.length
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 px-5 py-4">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-slate-900">
            {title}
            {query.data && <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 tabular-nums">{items.length}</span>}
          </h2>
          <p className="mt-0.5 text-xs text-slate-600">{description}</p>
        </div>
        {viewAll && (
          <Link to={viewAll.to} className="inline-flex items-center gap-1 text-xs font-medium text-navy-600 hover:text-navy-800">
            {viewAll.label} <ArrowRight className="size-3.5" />
          </Link>
        )}
      </div>
      {query.status === 'loading' && !query.data && <Spinner />}
      {query.status === 'error' && (
        <div className="p-4">
          <Alert tone="error" title="Could not load this section"
            action={<button type="button" className={buttonStyles.secondary} onClick={query.reload}>Try again</button>}>
            {query.error.message}
          </Alert>
        </div>
      )}
      {query.data && items.length === 0 && <p className="px-5 py-6 text-center text-sm text-slate-500">{empty}</p>}
      {items.length > 0 && (
        <ul className="divide-y divide-slate-100">
          {items.slice(0, SHOWN).map((item) => <li key={itemKey(item)} className="px-5 py-3">{render(item)}</li>)}
        </ul>
      )}
      {(items.length > SHOWN || truncated) && (
        <p className="border-t border-slate-100 px-5 py-2 text-xs text-slate-500">
          Showing {Math.min(items.length, SHOWN)} of {truncated ? 'at least ' : ''}{items.length}.{viewAll ? ` Use “${viewAll.label}” for the full list.` : ''}
        </p>
      )}
    </Card>
  )
}

function ItemLine({ to, title, meta, badges, action }: { to: string; title: ReactNode; meta?: ReactNode; badges?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start gap-3">
      <div className="min-w-0 flex-1">
        <Link to={to} className="font-medium text-navy-700 hover:underline">{title}</Link>
        {meta && <div className="mt-0.5 text-xs text-slate-600">{meta}</div>}
        {badges && <div className="mt-1.5 flex flex-wrap gap-1.5">{badges}</div>}
      </div>
      {action}
    </div>
  )
}

function Legend() {
  return (
    <Card className="p-4 text-xs text-slate-600">
      <p className="font-medium text-slate-800">How to read this page</p>
      <ul className="mt-1 grid gap-1 sm:grid-cols-3">
        <li><span className="font-medium text-slate-800">Deadline</span> — time to or since an FDR’s maturity date (Indian Standard Time).</li>
        <li><span className="font-medium text-slate-800">Request status</span> — where a renewal, replacement or release request is in its workflow.</li>
        <li><span className="font-medium text-slate-800">Review priority</span> — AICTE screening only: the most severe unreviewed finding. Not a measure of fraud.</li>
      </ul>
      <p className="mt-2">Nothing here is decided automatically. Every item links to the page where a person acts on it.</p>
    </Card>
  )
}

// ---------- institution ----------

/** Fetches the record to show AICTE's message; the list endpoint does not include remarks. */
function FdrClarification({ fdr }: { fdr: FdrListItem }) {
  const detail = useApiQuery<FdrDetail>(`/fdrs/${fdr.id}`)
  return (
    <ItemLine
      to={`/fdr-records/${fdr.id}`}
      title={`FDR ${fdr.fdr_number}`}
      meta={<>
        {fdr.bank_name} · updated {formatDateTime(fdr.updated_at)}
        <p className="mt-1 text-sm text-slate-800">
          {detail.data?.review_remarks ? <>AICTE: “{detail.data.review_remarks}”</> : detail.status === 'error' ? 'Open the record to read AICTE’s message.' : '…'}
        </p>
      </>}
      badges={<StatusBadge status={fdr.status} />}
      action={<Link to={`/fdr-records/${fdr.id}/edit`} className={buttonStyles.secondary}>Correct details</Link>}
    />
  )
}

/** Fetches the request to show AICTE's latest clarification message (institution view excludes internal notes). */
function RequestClarification({ req }: { req: LifecycleRequestRead }) {
  const detail = useApiQuery<LifecycleRequestDetail>(`/lifecycle-requests/${req.id}`)
  const ask = detail.data?.events.filter((e) => e.action === 'REQUEST_CLARIFICATION').at(-1)
  return (
    <ItemLine
      to={`/lifecycle-requests/${req.id}`}
      title={`${REQUEST_TYPE_LABELS[req.request_type]} request #${req.id} · FDR ${req.fdr.fdr_number}`}
      meta={<p className="mt-1 text-sm text-slate-800">
        {ask?.message ? <>AICTE: “{ask.message}”</> : detail.status === 'error' ? 'Open the request to read AICTE’s message.' : '…'}
      </p>}
      badges={<RequestStatusBadge status={req.status} />}
      action={<Link to={`/lifecycle-requests/${req.id}`} className={buttonStyles.secondary}>Respond</Link>}
    />
  )
}

function InstitutionActionCentre() {
  const fdrClarifications = useApiQuery<Page<FdrListItem>>(
    `/fdrs${toQuery({ status: ['CLARIFICATION_REQUESTED'], sort: 'oldest', page_size: 50 })}`)
  const requestClarifications = useApiQuery<Page<LifecycleRequestRead>>(
    `/lifecycle-requests${toQuery({ status: ['CLARIFICATION_REQUESTED'], page_size: 50 })}`)
  const missingCopy = useApiQuery<Page<FdrListItem>>(
    `/fdrs${toQuery({ missing_fdr_copy: true, status: ['SUBMITTED', 'UNDER_REVIEW', 'CLARIFICATION_REQUESTED'], sort: 'oldest', page_size: 50 })}`)
  const maturity = useApiQuery<Page<MaturityItem>>(`/lifecycle/maturity${toQuery({ within_days: 30, page_size: 100 })}`)
  const pending = useApiQuery<Page<LifecycleRequestRead>>(
    `/lifecycle-requests${toQuery({ status: ['SUBMITTED', 'UNDER_REVIEW', 'APPROVED'], page_size: 50 })}`)
  const oldestFirst = (a: LifecycleRequestRead, b: LifecycleRequestRead) => a.created_at.localeCompare(b.created_at)

  return (
    <div className="space-y-5">
      <PageHeader title="Action Centre" description="Items for your institution that need attention. Only your own records are shown." />
      <Legend />

      <Section
        title="Corrections requested on FDR records"
        description="AICTE asked for clarification. Correct the details or add documents, then save to resubmit."
        query={fdrClarifications}
        filter={(f) => WORKABLE.includes(f.lifecycle_status)}
        empty="No FDR record is waiting for your correction."
        viewAll={{ to: '/fdr-records?status=CLARIFICATION_REQUESTED', label: 'All records needing clarification' }}
        itemKey={(f) => f.id}
        render={(f) => <FdrClarification fdr={f} />}
      />
      <Section
        title="Clarifications requested on lifecycle requests"
        description="AICTE needs more information before deciding these renewal, replacement or release requests."
        query={requestClarifications}
        sort={oldestFirst}
        empty="No lifecycle request is waiting for your response."
        itemKey={(r) => r.id}
        render={(r) => <RequestClarification req={r} />}
      />
      <Section
        title="Records without an FDR copy"
        description="Open records with no current document marked “FDR copy”. Upload one on the record page."
        query={missingCopy}
        filter={(f) => WORKABLE.includes(f.lifecycle_status)}
        empty="Every open record has an FDR copy attached."
        itemKey={(f) => f.id}
        render={(f) => (
          <ItemLine to={`/fdr-records/${f.id}`} title={`FDR ${f.fdr_number}`} meta={`${f.bank_name} · submitted ${formatDateTime(f.created_at)}`}
            badges={<StatusBadge status={f.status} />}
            action={<Link to={`/fdr-records/${f.id}`} className={buttonStyles.secondary}>Upload document</Link>} />
        )}
      />
      <Section
        title="Maturity deadlines"
        description="Active FDRs that have matured or mature within 30 days. Nothing is released or renewed automatically."
        query={maturity}
        empty="No active FDR matures within 30 days."
        viewAll={{ to: '/renewals', label: 'Renewals & Maturity' }}
        itemKey={(m) => m.fdr_id}
        render={(m) => (
          <ItemLine to={`/fdr-records/${m.fdr_id}`} title={`FDR ${m.fdr_number}`} meta={`${m.bank_name} · matures ${formatDate(m.maturity_date)}`}
            badges={<>
              <DeadlineBadge item={m} />
              {m.open_request_type
                ? <Pill className="bg-white text-slate-700 ring-slate-300">{REQUEST_TYPE_LABELS[m.open_request_type]} request open</Pill>
                : <Pill className="bg-white text-slate-500 ring-slate-200">No request yet</Pill>}
            </>} />
        )}
      />
      <Section
        title="Your requests awaiting AICTE"
        description="Submitted, under review, or approved and awaiting AICTE’s recorded completion. No action needed from you."
        query={pending}
        sort={oldestFirst}
        empty="No request is waiting on AICTE."
        viewAll={{ to: '/renewals', label: 'All requests' }}
        itemKey={(r) => r.id}
        render={(r) => (
          <ItemLine to={`/lifecycle-requests/${r.id}`} title={`${REQUEST_TYPE_LABELS[r.request_type]} request #${r.id} · FDR ${r.fdr.fdr_number}`}
            meta={`submitted ${formatDateTime(r.created_at)}`} badges={<RequestStatusBadge status={r.status} />} />
        )}
      />
    </div>
  )
}

// ---------- AICTE ----------

function AicteActionCentre() {
  const screening = useApiQuery<Page<ScreeningQueueItem>>(`/screening/queue${toQuery({ page_size: 100 })}`)
  const maturity = useApiQuery<Page<MaturityItem>>(`/lifecycle/maturity${toQuery({ within_days: 30, page_size: 100 })}`)
  const decisions = useApiQuery<Page<LifecycleRequestRead>>(
    `/lifecycle-requests${toQuery({ status: ['SUBMITTED', 'UNDER_REVIEW'], page_size: 100 })}`)
  const completions = useApiQuery<Page<LifecycleRequestRead>>(
    `/lifecycle-requests${toQuery({ status: ['APPROVED'], page_size: 100 })}`)
  const waiting = useApiQuery<Page<LifecycleRequestRead>>(
    `/lifecycle-requests${toQuery({ status: ['CLARIFICATION_REQUESTED'], page_size: 100 })}`)
  const outcomes = useApiQuery<Page<AwaitingDecisionItem>>(`/verification/awaiting-decision${toQuery({ page_size: 100 })}`)
  const cases = useApiQuery<Page<AssignmentQueueItem>>(`/verification/assignments${toQuery({ status: ['ACTIVE'], page_size: 100 })}`)
  const oldestFirst = (a: LifecycleRequestRead, b: LifecycleRequestRead) => a.created_at.localeCompare(b.created_at)
  const today = Date.now()
  const daysSince = (iso: string) => Math.floor((today - new Date(iso).getTime()) / 86_400_000)

  const requestLine = (r: LifecycleRequestRead) => (
    <ItemLine to={`/lifecycle-requests/${r.id}`}
      title={`${REQUEST_TYPE_LABELS[r.request_type]} request #${r.id} · FDR ${r.fdr.fdr_number}`}
      meta={`${r.institution.code} · submitted ${formatDateTime(r.created_at)}${r.successor ? ` · new instrument ${r.successor.fdr_number}` : ''}`}
      badges={<RequestStatusBadge status={r.status} />} />
  )

  return (
    <div className="space-y-5">
      <PageHeader title="Action Centre" description="Review workload across all institutions. Each list keeps its own ordering; there is no combined score." />
      <Legend />

      <Section
        title="Screening findings awaiting human review"
        description="Latest screening run per FDR with unreviewed high-priority or warning findings, highest review priority first."
        query={screening}
        filter={(s) => s.run_status === 'FAILED' || s.unreviewed_high + s.unreviewed_warning > 0}
        empty="No screening findings are waiting for review."
        viewAll={{ to: '/screening', label: 'Screening queue' }}
        itemKey={(s) => s.run_id}
        render={(s) => (
          <ItemLine to={`/fdr-records/${s.fdr_id}`} title={`FDR ${s.fdr_number}`}
            meta={`${s.institution.code} · ${s.bank_name} · run #${s.run_number}, ${formatDateTime(s.completed_at)}`}
            badges={<>
              {s.run_status === 'FAILED'
                ? <Pill className="bg-red-50 text-red-700 ring-red-200">Last run failed — run again</Pill>
                : <PriorityBadge priority={s.review_priority} />}
              {s.run_status !== 'FAILED' && <Pill className="bg-white text-slate-700 ring-slate-300">Unreviewed: {s.unreviewed_high} high, {s.unreviewed_warning} warning</Pill>}
              {s.is_stale && <Pill className="bg-white text-amber-700 ring-amber-200">Record changed since run</Pill>}
            </>} />
        )}
      />
      <Section
        title="Bank outcomes awaiting your decision"
        description="A bank officer recorded an outcome since your last review decision, oldest first. Decide in the record’s review panel."
        query={outcomes}
        empty="No bank outcome is awaiting your decision."
        viewAll={{ to: '/verification?view=awaiting', label: 'Review queue' }}
        itemKey={(o) => o.fdr_id}
        render={(o) => (
          <ItemLine to={`/fdr-records/${o.fdr_id}`} title={`FDR ${o.fdr_number}`}
            meta={`${o.institution.code} · ${o.bank_name} · outcome by ${o.officer.full_name}, ${formatDateTime(o.outcome_submitted_at)}`}
            badges={<><OutcomeBadge outcome={o.outcome} /><StatusBadge status={o.fdr_status} /></>} />
        )}
      />
      <Section
        title="Lifecycle requests awaiting your decision"
        description="Submitted or under review. Decide, or ask the institution for clarification."
        query={decisions}
        sort={oldestFirst}
        empty="No lifecycle request is awaiting a decision."
        viewAll={{ to: '/renewals', label: 'Renewal requests' }}
        itemKey={(r) => r.id}
        render={requestLine}
      />
      <Section
        title="Approved requests awaiting recorded completion"
        description="Approval was a decision only. Record completion once the action has actually been carried out."
        query={completions}
        sort={oldestFirst}
        empty="No approved request is awaiting completion."
        viewAll={{ to: '/release-requests', label: 'Release requests' }}
        itemKey={(r) => r.id}
        render={requestLine}
      />
      <Section
        title="Maturity deadlines"
        description="Active FDRs across institutions that have matured or mature within 30 days."
        query={maturity}
        empty="No active FDR matures within 30 days."
        viewAll={{ to: '/renewals', label: 'Renewals & Maturity' }}
        itemKey={(m) => m.fdr_id}
        render={(m) => (
          <ItemLine to={`/fdr-records/${m.fdr_id}`} title={`FDR ${m.fdr_number}`}
            meta={`${m.institution.code} · ${m.bank_name} · matures ${formatDate(m.maturity_date)}`}
            badges={<>
              <DeadlineBadge item={m} />
              <StatusBadge status={m.status} />
              {m.open_request_type && <Pill className="bg-white text-slate-700 ring-slate-300">{REQUEST_TYPE_LABELS[m.open_request_type]} request open</Pill>}
            </>} />
        )}
      />
      <Section
        title="Verification cases with bank officers"
        description="Active assignments; the bank officer has not yet recorded an outcome. Reassign from the record page if needed."
        query={cases}
        sort={(a, b) => a.assigned_at.localeCompare(b.assigned_at)}
        empty="No verification case is open."
        viewAll={{ to: '/verification', label: 'Verification' }}
        itemKey={(c) => c.id}
        render={(c) => (
          <ItemLine to={`/fdr-records/${c.fdr_id}`} title={`FDR ${c.fdr_number}`}
            meta={`${c.institution.code} · with ${c.bank_officer.full_name} since ${formatDateTime(c.assigned_at)} (${daysSince(c.assigned_at)} day${daysSince(c.assigned_at) === 1 ? '' : 's'})`} />
        )}
      />
      <Section
        title="Waiting on institutions"
        description="Lifecycle requests where you asked for clarification. Shown for follow-up; the next step is the institution’s."
        query={waiting}
        sort={oldestFirst}
        empty="No request is waiting on an institution."
        itemKey={(r) => r.id}
        render={requestLine}
      />
    </div>
  )
}

export default function ActionCentrePage() {
  const user = useCurrentUser()
  return user.role === 'AICTE_OFFICIAL' ? <AicteActionCentre /> : <InstitutionActionCentre />
}
