import { Download } from 'lucide-react'
import type { ReactNode } from 'react'
import { Alert, Card, PageHeader, Spinner, buttonStyles } from '../components/ui'
import { useApiQuery } from '../hooks/useApiQuery'
import { formatDate, formatDateTime, formatINR, LIFECYCLE_STATUS_LABELS, REQUEST_STATUS_LABELS, REQUEST_TYPE_LABELS, STATUS_LABELS } from '../lib/format'
import type { FdrStatus, ReportSummary } from '../types'

const FDR_STATUSES: FdrStatus[] = ['SUBMITTED', 'UNDER_REVIEW', 'CLARIFICATION_REQUESTED', 'ACCEPTED', 'REJECTED']
const LIFECYCLE = ['ACTIVE', 'PROPOSED', 'RENEWED', 'REPLACED', 'RELEASED', 'CANCELLED']
const REQUEST_TYPES = ['RENEWAL', 'REPLACEMENT', 'RELEASE']
const REQUEST_STATUSES = ['SUBMITTED', 'UNDER_REVIEW', 'CLARIFICATION_REQUESTED', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'COMPLETED']

function Section({ title, note, actions, children }: { title: string; note?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          {note && <p className="mt-0.5 text-xs text-slate-600">{note}</p>}
        </div>
        {actions}
      </div>
      <div className="overflow-x-auto">{children}</div>
    </Card>
  )
}

const th = 'px-4 py-2.5 text-left text-xs font-semibold tracking-wide text-slate-600 uppercase'
const td = 'px-4 py-2 text-sm text-slate-800'
const num = 'px-4 py-2 text-right text-sm tabular-nums text-slate-900'

function CountTable({ rows, total }: { rows: [string, number][]; total: number }) {
  return (
    <table className="min-w-full divide-y divide-slate-100">
      <tbody className="divide-y divide-slate-100">
        {rows.map(([label, count]) => (
          <tr key={label}><td className={td}>{label}</td><td className={num}>{count}</td></tr>
        ))}
        <tr className="bg-slate-50 font-semibold"><td className={td}>Total</td><td className={num}>{total}</td></tr>
      </tbody>
    </table>
  )
}

/** CSV cell: quoted, and prefixed when it could be read as a spreadsheet formula. */
function csvCell(value: string | number): string {
  let text = String(value)
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`
  return `"${text.replace(/"/g, '""')}"`
}

function downloadInstitutionCsv(report: ReportSummary) {
  const header = ['Institution code', 'Institution name', 'Total FDRs', ...FDR_STATUSES.map((s) => STATUS_LABELS[s]),
    'Active instruments', 'Active amount (INR)', 'Maturing within 30 days', 'Matured, still active', 'Open lifecycle requests']
  const lines = [
    [`NidhiSec institution summary — snapshot of current records as of ${report.as_of} (IST), generated ${report.generated_at}`],
    [],
    header,
    ...report.institutions.map((r) => [
      r.institution.code, r.institution.name, r.total_fdrs, ...FDR_STATUSES.map((s) => r.by_status[s] ?? 0),
      r.active_instruments, r.active_amount, r.maturing_within_30_days, r.overdue_active, r.open_lifecycle_requests,
    ]),
  ]
  const csv = lines.map((line) => line.map(csvCell).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `nidhisec-institution-summary-${report.as_of}.csv`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

export default function ReportsPage() {
  const result = useApiQuery<ReportSummary>('/reports/summary')
  const r = result.data

  return (
    <div className="space-y-5">
      <PageHeader title="Reports" description="Portfolio summaries across all institutions, computed from current records." />
      {result.status === 'error' && (
        <Alert tone="error" title="Could not load reports" action={<button type="button" className={buttonStyles.secondary} onClick={result.reload}>Try again</button>}>
          {result.error.message}
        </Alert>
      )}
      {result.status === 'loading' && !r && <Spinner label="Loading reports…" />}
      {r && (
        <>
          <Alert tone="info" title={`Snapshot as of ${formatDate(r.as_of)} (generated ${formatDateTime(r.generated_at)})`}>
            {r.scope_note} This is not a historical report of activity over a period.
            <button type="button" className="ml-2 font-medium underline" onClick={result.reload}>Refresh</button>
          </Alert>

          <div className="grid gap-5 lg:grid-cols-2">
            <Section title="FDRs by review status" note="Current AICTE review status of every FDR record.">
              <CountTable rows={FDR_STATUSES.map((s) => [STATUS_LABELS[s], r.fdr_by_status[s] ?? 0])} total={r.fdr_total} />
            </Section>
            <Section title="FDRs by lifecycle status" note="Whether each instrument is in force, proposed, superseded, released or cancelled.">
              <CountTable rows={LIFECYCLE.map((s) => [LIFECYCLE_STATUS_LABELS[s], r.fdr_by_lifecycle[s] ?? 0])} total={r.fdr_total} />
            </Section>
          </div>

          <Section title="Maturity summary" note={`Active, non-rejected instruments (${r.monitored_total}) grouped by time to maturity as of ${formatDate(r.as_of)}.`}>
            <table className="min-w-full divide-y divide-slate-100">
              <thead className="bg-slate-50"><tr><th className={th}>Period</th><th className={`${th} text-right`}>FDRs</th><th className={`${th} text-right`}>Total deposit amount</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {r.maturity.map((m) => (
                  <tr key={m.bucket} className={m.bucket === 'OVERDUE' && m.count > 0 ? 'bg-red-50/40' : ''}>
                    <td className={td}>{m.label}</td><td className={num}>{m.count}</td><td className={num}>{formatINR(m.total_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <Section title="Lifecycle requests by type and status" note="Every renewal, replacement and release request, counted by its current status.">
            {r.lifecycle_requests.length === 0 ? <p className="px-5 py-6 text-center text-sm text-slate-500">No lifecycle requests yet.</p> : (
              <table className="min-w-full divide-y divide-slate-100">
                <thead className="bg-slate-50">
                  <tr><th className={th}>Type</th>{REQUEST_STATUSES.map((s) => <th key={s} className={`${th} text-right`}>{REQUEST_STATUS_LABELS[s]}</th>)}<th className={`${th} text-right`}>Total</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {REQUEST_TYPES.map((t) => {
                    const counts = REQUEST_STATUSES.map((s) => r.lifecycle_requests.find((x) => x.request_type === t && x.status === s)?.count ?? 0)
                    return (
                      <tr key={t}><td className={td}>{REQUEST_TYPE_LABELS[t]}</td>{counts.map((c, i) => <td key={i} className={num}>{c}</td>)}
                        <td className={`${num} font-semibold`}>{counts.reduce((a, b) => a + b, 0)}</td></tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </Section>

          <Section
            title="Institution-wise summary"
            note="FDR counts by review status, plus active instruments (in force, not rejected), their total amount and maturity position."
            actions={r.institutions.length > 0 && (
              <button type="button" className={buttonStyles.secondary} onClick={() => downloadInstitutionCsv(r)}>
                <Download className="size-4" /> Export CSV
              </button>
            )}
          >
            {r.institutions.length === 0 ? <p className="px-5 py-6 text-center text-sm text-slate-500">No institutions registered.</p> : (
              <table className="min-w-full divide-y divide-slate-100">
                <thead className="bg-slate-50">
                  <tr>
                    <th className={th}>Institution</th><th className={`${th} text-right`}>Total</th>
                    {FDR_STATUSES.map((s) => <th key={s} className={`${th} text-right`}>{STATUS_LABELS[s]}</th>)}
                    <th className={`${th} text-right`}>Active</th><th className={`${th} text-right`}>Active amount</th>
                    <th className={`${th} text-right`}>Due ≤30 days</th><th className={`${th} text-right`}>Matured</th><th className={`${th} text-right`}>Open requests</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {r.institutions.map((row) => (
                    <tr key={row.institution.id}>
                      <td className={td}><div className="font-medium">{row.institution.code}</div><div className="text-xs text-slate-500">{row.institution.name}</div></td>
                      <td className={num}>{row.total_fdrs}</td>
                      {FDR_STATUSES.map((s) => <td key={s} className={num}>{row.by_status[s] ?? 0}</td>)}
                      <td className={num}>{row.active_instruments}</td><td className={`${num} whitespace-nowrap`}>{formatINR(row.active_amount)}</td>
                      <td className={num}>{row.maturing_within_30_days}</td><td className={num}>{row.overdue_active}</td><td className={num}>{row.open_lifecycle_requests}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
          <p className="text-xs text-slate-500">
            The CSV contains exactly the institution table shown above (counts and amounts only), generated in your browser from this snapshot.
          </p>
        </>
      )}
    </div>
  )
}
