import { Building2, CalendarClock, Copy, FilePlus2, FileStack, Info, Landmark, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useCurrentUser } from '../auth/AuthContext'
import BackendStatus from '../components/BackendStatus'
import { Alert, Card, buttonStyles } from '../components/ui'
import { useApiQuery } from '../hooks/useApiQuery'
import { addDaysIso, ROLE_LABELS, STATUS_LABELS, todayIso } from '../lib/format'
import { navItemsFor } from '../navigation'
import type { DashboardSummary, FdrStatus, FdrSummary } from '../types'

const PORTALS = [
  {
    icon: Building2,
    title: 'Institution / College',
    description: 'Submit FDRs, track review status and correct records when clarification is requested.',
  },
  {
    icon: Landmark,
    title: 'Bank Officer',
    description: 'Checks FDRs assigned by AICTE against the bank’s own records and records an outcome.',
  },
  {
    icon: ShieldCheck,
    title: 'AICTE Official',
    description: 'Search and review FDRs across institutions, examine possible duplicates and the audit trail.',
  },
]

function StatTile({ label, value, to, icon }: { label: string; value: number | string; to?: string; icon: ReactNode }) {
  const body = (
    <div className="flex items-center gap-3 p-4">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-navy-50 text-navy-600">{icon}</span>
      <span className="min-w-0">
        <span className="block text-2xl font-semibold text-slate-900 tabular-nums">{value}</span>
        <span className="block text-xs leading-tight text-slate-600">{label}</span>
      </span>
    </div>
  )
  return (
    <Card className={to ? 'transition hover:border-navy-300 hover:shadow' : ''}>
      {to ? <Link to={to}>{body}</Link> : body}
    </Card>
  )
}

function FdrOverview() {
  const summary = useApiQuery<FdrSummary>('/fdrs/summary')
  const today = todayIso()

  if (summary.status === 'error') {
    return (
      <Alert tone="error" title="Could not load FDR summary" action={
        <button type="button" className={buttonStyles.secondary} onClick={summary.reload}>Try again</button>
      }>
        {summary.error.message}
      </Alert>
    )
  }
  const data = summary.data
  const value = (n: number | undefined) => (data ? (n ?? 0) : '…')
  const statuses: FdrStatus[] = ['SUBMITTED', 'UNDER_REVIEW', 'CLARIFICATION_REQUESTED', 'ACCEPTED', 'REJECTED']

  return (
    <section aria-labelledby="overview-title" aria-busy={summary.status === 'loading'}>
      <h2 id="overview-title" className="text-sm font-semibold text-slate-900">FDR overview</h2>
      <div className="mt-3 grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatTile label="FDR records" value={value(data?.total)} to="/fdr-records" icon={<FileStack className="size-5" />} />
        <StatTile
          label="Possible duplicates"
          value={value(data?.possible_duplicates)}
          to="/fdr-records?duplicates=1"
          icon={<Copy className="size-5" />}
        />
        <StatTile
          label="Maturing in 90 days"
          value={value(data?.maturing_within_90_days)}
          to={`/fdr-records?maturity_from=${today}&maturity_to=${addDaysIso(today, 90)}&sort=maturity_asc`}
          icon={<CalendarClock className="size-5" />}
        />
        <StatTile
          label="Past maturity (open)"
          value={value(data?.matured)}
          to={`/fdr-records?maturity_to=${addDaysIso(today, -1)}&sort=maturity_asc`}
          icon={<CalendarClock className="size-5" />}
        />
      </div>
      <Card className="mt-3 divide-y divide-slate-100">
        {statuses.map((status) => (
          <Link
            key={status}
            to={`/fdr-records?status=${status}`}
            className="flex items-center justify-between px-4 py-2.5 text-sm hover:bg-slate-50"
          >
            <span className="text-slate-700">{STATUS_LABELS[status]}</span>
            <span className="font-semibold text-slate-900 tabular-nums">{value(data?.by_status[status])}</span>
          </Link>
        ))}
      </Card>
      <p className="mt-2 text-xs text-slate-500">
        Counts reflect records submitted to NidhiSec. No status means an FDR has been confirmed authentic by its bank.
      </p>
    </section>
  )
}

function sum(record: Record<string, number> | null | undefined): number {
  return record ? Object.values(record).reduce((a, b) => a + b, 0) : 0
}

/** Role-specific counts that need someone's attention, from /dashboard/summary. */
function ActionSummary() {
  const result = useApiQuery<DashboardSummary>('/dashboard/summary')
  if (result.status === 'error') {
    return <Alert tone="error" title="Could not load your action summary">{result.error.message}</Alert>
  }
  const d = result.data
  const v = (n: number | null | undefined) => (d ? (n ?? 0) : '…')
  const tiles: { label: string; value: number | string; to: string }[] = []
  if (d?.role === 'BANK_OFFICER') {
    tiles.push({ label: 'Cases awaiting your outcome', value: v(d?.cases_awaiting_action), to: '/verification' })
    tiles.push({ label: 'Cases you completed', value: v(d?.cases_completed), to: '/verification' })
    tiles.push({ label: 'Reassigned or cancelled', value: v(d?.cases_closed_other), to: '/verification' })
  } else if (d?.role === 'INSTITUTION') {
    tiles.push({ label: 'Clarifications needing your action', value: v(d.clarifications_requiring_action), to: '/fdr-records?status=CLARIFICATION_REQUESTED' })
    tiles.push({ label: 'Maturing within 30 days', value: v(d.maturing_within_30_days), to: '/renewals' })
    tiles.push({ label: 'Matured, still active', value: v(d.overdue_active), to: '/renewals' })
    tiles.push({ label: 'Open renewal / replacement requests', value: sum(d.lifecycle_requests_open) - (d.lifecycle_requests_open?.RELEASE ?? 0), to: '/renewals' })
    tiles.push({ label: 'Open release requests', value: d.lifecycle_requests_open?.RELEASE ?? 0, to: '/release-requests' })
  } else if (d?.role === 'AICTE_OFFICIAL') {
    tiles.push({ label: 'Bank outcomes awaiting your decision', value: v(d.verification_outcomes_awaiting_decision), to: '/verification' })
    tiles.push({ label: 'Active verification cases', value: v(d.verification_active), to: '/verification' })
    tiles.push({ label: 'Unreviewed high-priority screening findings', value: v(d.screening_unreviewed_high), to: '/screening' })
    tiles.push({ label: 'Renewal / replacement requests to decide', value: (d.lifecycle_requests_awaiting_decision?.RENEWAL ?? 0) + (d.lifecycle_requests_awaiting_decision?.REPLACEMENT ?? 0), to: '/renewals' })
    tiles.push({ label: 'Release requests to decide', value: d.lifecycle_requests_awaiting_decision?.RELEASE ?? 0, to: '/release-requests' })
    tiles.push({ label: 'Approved requests awaiting completion', value: v(d.lifecycle_requests_awaiting_completion), to: '/renewals' })
    tiles.push({ label: 'Maturing within 30 days', value: v(d.maturing_within_30_days), to: '/renewals' })
    tiles.push({ label: 'Matured, still active', value: v(d.overdue_active), to: '/renewals' })
  }
  return (
    <section aria-labelledby="actions-title" aria-busy={result.status === 'loading'}>
      <h2 id="actions-title" className="text-sm font-semibold text-slate-900">Action needed</h2>
      {!d ? <Card className="mt-3 p-4 text-sm text-slate-500">Loading…</Card> : (
        <Card className="mt-3 divide-y divide-slate-100">
          {tiles.map((t) => (
            <Link key={t.label} to={t.to} className="flex items-center justify-between px-4 py-2.5 text-sm hover:bg-slate-50">
              <span className="text-slate-700">{t.label}</span>
              <span className={`font-semibold tabular-nums ${Number(t.value) > 0 ? 'text-navy-700' : 'text-slate-400'}`}>{t.value}</span>
            </Link>
          ))}
        </Card>
      )}
      {d && <p className="mt-2 text-xs text-slate-500">Counts from records you are permitted to see, as of {d.as_of}.</p>}
    </section>
  )
}

export default function DashboardPage() {
  const user = useCurrentUser()
  const modules = navItemsFor(user.role).filter((item) => item.path !== '/')
  const showFdrs = user.role === 'INSTITUTION' || user.role === 'AICTE_OFFICIAL'

  return (
    <div className="space-y-6">
      <section className="overflow-hidden rounded-lg bg-gradient-to-br from-navy-800 to-navy-900 px-6 py-7 text-white shadow-sm sm:px-8">
        <p className="text-xs font-semibold tracking-wider text-sky-300 uppercase">
          AICTE Security Deposit / FDR Management Portal
        </p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">Welcome, {user.full_name}</h2>
        <p className="mt-2 text-sm text-navy-100">
          Signed in as {ROLE_LABELS[user.role]}
          {user.institution && ` for ${user.institution.name} (${user.institution.code})`}.
        </p>
        {user.role === 'INSTITUTION' && (
          <Link to="/fdr-records/new" className="mt-5 inline-flex items-center gap-1.5 rounded-md bg-white px-3.5 py-2 text-sm font-medium text-navy-800 hover:bg-navy-50">
            <FilePlus2 className="size-4" /> Submit an FDR
          </Link>
        )}
      </section>

      <Alert tone="info">
        <strong>Available now:</strong> sign-in, FDR submission and correction, supporting-document upload with integrity
        hashes, AICTE review status, possible-duplicate flags, bank verification assignments with officer-recorded outcomes, advisory screening for AICTE, maturity alerts,
        renewal/replacement and release requests, notifications and the audit trail.{' '}
        <strong>Not implemented yet:</strong> integration with bank or payment systems, and reports.
      </Alert>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {showFdrs && <FdrOverview />}

          <ActionSummary />

          <section aria-labelledby="modules-title">
            <h2 id="modules-title" className="text-sm font-semibold text-slate-900">Portal modules</h2>
            <ul className="mt-3 grid gap-3 sm:grid-cols-2">
              {modules.map(({ path, label, icon: Icon, summary, implemented }) => (
                <li key={path}>
                  <Link
                    to={path}
                    className="flex h-full gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:border-navy-300 hover:shadow"
                  >
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-navy-50 text-navy-600">
                      <Icon className="size-5" />
                    </span>
                    <span className="min-w-0">
                      <span className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-900">{label}</span>
                        {implemented ? (
                          <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
                            Available
                          </span>
                        ) : (
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                            Planned
                          </span>
                        )}
                      </span>
                      <span className="mt-1 block text-xs leading-relaxed text-slate-600">{summary}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="portals-title">
            <h2 id="portals-title" className="text-sm font-semibold text-slate-900">Stakeholder portals</h2>
            <ul className="mt-3 grid gap-3 md:grid-cols-3">
              {PORTALS.map(({ icon: Icon, title, description }) => (
                <li key={title} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                  <Icon className="size-5 text-navy-600" />
                  <h3 className="mt-2 text-sm font-semibold text-slate-900">{title}</h3>
                  <p className="mt-1 text-xs leading-relaxed text-slate-600">{description}</p>
                </li>
              ))}
            </ul>
          </section>
        </div>

        {/* Status first on small screens, right-hand column on large screens. */}
        <div className="order-first space-y-6 lg:order-last">
          <BackendStatus />
          <Card className="p-5 text-xs leading-relaxed text-slate-600">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
              <Info className="size-4 text-navy-500" /> About record status
            </h2>
            <p className="mt-2">
              Saving an FDR in NidhiSec records the details the institution entered. It does not confirm that the FDR
              is genuine. A bank officer’s recorded outcome is their own attestation, and AICTE decides separately; NidhiSec has no connection to bank systems.
            </p>
          </Card>
        </div>
      </div>
    </div>
  )
}
