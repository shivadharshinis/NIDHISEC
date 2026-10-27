import { ChevronDown, ChevronRight, Loader2, RefreshCw, ScanSearch } from 'lucide-react'
import { type FormEvent, type ReactNode, useState } from 'react'
import { Link } from 'react-router'
import { useApiQuery } from '../../hooks/useApiQuery'
import { ApiError, apiRequest } from '../../lib/api'
import {
  CATEGORY_LABELS,
  DISPOSITION_LABELS,
  EXTRACTION_STATUS_LABELS,
  formatDateTime,
  MATCH_TYPE_LABELS,
  PRIORITY_STYLES,
  SEVERITY_LABELS,
  SEVERITY_STYLES,
} from '../../lib/format'
import type {
  FindingRead,
  FindingSeverity,
  ReviewPriority,
  RunDetail,
  ScreeningDisposition,
  ScreeningOverview,
  ScreeningReviewRead,
} from '../../types'
import { Alert, Card, Field, Spinner, buttonStyles, inputStyles } from '../ui'

function Pill({ className, children }: { className: string; children: ReactNode }) {
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset ${className}`}>{children}</span>
}

export function PriorityBadge({ priority }: { priority: ReviewPriority | null }) {
  if (!priority) return <Pill className="bg-slate-100 text-slate-600 ring-slate-300">No result</Pill>
  return <Pill className={PRIORITY_STYLES[priority]}>Review priority: {priority.toLowerCase()}</Pill>
}

const SEVERITY_ORDER: FindingSeverity[] = ['HIGH', 'WARNING', 'INFO']

type Observed = Record<string, unknown>
type RecordSummary = { id: number; institution: { code: string; name: string }; fdr_number: string; bank_name: string;
  ifsc_code: string | null; amount: string; issue_date: string; maturity_date: string; status: string }

function DuplicateComparison({ observed }: { observed: Observed }) {
  const self = observed.this as RecordSummary | undefined
  const other = observed.other as RecordSummary | undefined
  if (!self || !other) return null
  const differing = new Set((observed.differing_fields as string[] | undefined) ?? [])
  const rows: [string, keyof RecordSummary][] = [
    ['FDR reference', 'fdr_number'], ['Bank', 'bank_name'], ['IFSC', 'ifsc_code'], ['Amount', 'amount'],
    ['Issue date', 'issue_date'], ['Maturity date', 'maturity_date'], ['Status', 'status'],
  ]
  return (
    <div className="mt-2 overflow-x-auto">
      <table className="min-w-full text-xs">
        <thead className="text-left text-slate-500">
          <tr><th className="py-1 pr-3 font-medium" /><th className="py-1 pr-3 font-medium">This record</th>
            <th className="py-1 font-medium">
              Matched record <Link to={`/fdr-records/${other.id}`} className="text-navy-600 hover:underline">#{other.id}</Link>
              {' '}· {other.institution.code}
            </th></tr>
        </thead>
        <tbody>
          {rows.map(([label, key]) => {
            const differs = differing.has(key)
            return (
              <tr key={key} className={differs ? 'bg-amber-50' : ''}>
                <td className="py-0.5 pr-3 text-slate-500">{label}</td>
                <td className="py-0.5 pr-3 font-mono text-slate-800">{String(self[key] ?? '—')}</td>
                <td className="py-0.5 font-mono text-slate-800">{String(other[key] ?? '—')}{differs && ' ≠'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="mt-1 text-[11px] text-slate-500">Matched record institution: {other.institution.name}</p>
    </div>
  )
}

function ObservedValues({ finding }: { finding: FindingRead }) {
  const observed = finding.observed
  if (!observed) return null
  if (finding.category === 'DUPLICATE') return <DuplicateComparison observed={observed} />
  const docValues = observed.document_values as { value: string; snippet: string; page: number }[] | undefined
  return (
    <dl className="mt-2 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[auto_1fr]">
      {observed.document_name !== undefined && (<><dt className="text-slate-500">Document</dt><dd className="break-all text-slate-800">{String(observed.document_name)}</dd></>)}
      {observed.record !== undefined && (<><dt className="text-slate-500">Submitted record</dt><dd className="font-mono text-slate-800">{String(observed.record)}</dd></>)}
      {docValues?.map((v, i) => (
        <span key={i} className="contents">
          <dt className="text-slate-500">Read from document</dt>
          <dd className="text-slate-800"><span className="font-mono">{v.value}</span>
            <span className="text-slate-500"> — page {v.page}: “{v.snippet}”</span></dd>
        </span>
      ))}
      {Object.entries(observed)
        .filter(([k]) => !['document_name', 'document_id', 'document_type', 'record', 'document_values'].includes(k))
        .map(([k, v]) => (
          <span key={k} className="contents">
            <dt className="text-slate-500">{k.replace(/_/g, ' ')}</dt>
            <dd className="font-mono break-all text-slate-800">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
          </span>
        ))}
    </dl>
  )
}

function ReviewList({ reviews, label }: { reviews: ScreeningReviewRead[]; label: string }) {
  if (!reviews.length) return null
  return (
    <div className="mt-2 text-xs">
      <p className="font-medium text-slate-600">{label}</p>
      <ul className="mt-1 space-y-1">
        {reviews.map((r) => (
          <li key={r.id} className="text-slate-700">
            <span className="font-medium">{DISPOSITION_LABELS[r.disposition]}</span> — {r.notes}
            <span className="text-slate-500"> ({r.reviewer.full_name}, {formatDateTime(r.reviewed_at)}, run #{r.run_number})</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ReviewForm({ fdrId, finding, onSaved }: { fdrId: number; finding: FindingRead; onSaved: () => void }) {
  const [disposition, setDisposition] = useState<ScreeningDisposition | ''>('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const id = `review-${finding.id}`

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!disposition) return setError('Choose a disposition.')
    if (notes.trim().length < 10) return setError('Notes must be at least 10 characters.')
    setSaving(true)
    setError(null)
    try {
      await apiRequest(`/fdrs/${fdrId}/screening/findings/${finding.id}/reviews`, {
        method: 'POST', body: { disposition, notes: notes.trim() },
      })
      setDisposition('')
      setNotes('')
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save the review.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="mt-3 grid gap-2 rounded-md bg-slate-50 p-3 sm:grid-cols-[12rem_1fr_auto] sm:items-end">
      <Field id={`${id}-disposition`} label="Your review">
        <select id={`${id}-disposition`} className={inputStyles} value={disposition} onChange={(e) => setDisposition(e.target.value as ScreeningDisposition | '')}>
          <option value="">Choose…</option>
          {(Object.keys(DISPOSITION_LABELS) as ScreeningDisposition[]).map((d) => <option key={d} value={d}>{DISPOSITION_LABELS[d]}</option>)}
        </select>
      </Field>
      <Field id={`${id}-notes`} label="Notes">
        <input id={`${id}-notes`} className={inputStyles} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      <button type="submit" className={buttonStyles.secondary} disabled={saving}>
        {saving && <Loader2 className="size-4 animate-spin" />} Record review
      </button>
      {error && <p className="text-xs text-red-700 sm:col-span-3" role="alert">{error}</p>}
    </form>
  )
}

function FindingItem({ fdrId, finding, canReview, onReviewed }: { fdrId: number; finding: FindingRead; canReview: boolean; onReviewed: () => void }) {
  const current = finding.reviews[finding.reviews.length - 1]
  return (
    <li className="py-4">
      <div className="flex flex-wrap items-center gap-2">
        <Pill className={SEVERITY_STYLES[finding.severity]}>{SEVERITY_LABELS[finding.severity]}</Pill>
        <span className="text-xs text-slate-500">{CATEGORY_LABELS[finding.category] ?? finding.category}</span>
        {finding.match_type && <Pill className="bg-white text-slate-700 ring-slate-300">{MATCH_TYPE_LABELS[finding.match_type] ?? finding.match_type}</Pill>}
        {current && <Pill className="bg-navy-50 text-navy-700 ring-navy-200">Reviewed: {DISPOSITION_LABELS[current.disposition]}</Pill>}
      </div>
      <p className="mt-1.5 text-sm font-medium text-slate-900">{finding.title}</p>
      <p className="text-sm text-slate-700">{finding.description}</p>
      <p className="mt-1 text-xs text-slate-600"><span className="font-medium">Why this was raised:</span> {finding.reason}</p>
      <p className="mt-0.5 font-mono text-[11px] text-slate-400">
        {finding.code} · rule v{finding.rule_version}{finding.field && ` · field: ${finding.field}`}
      </p>
      <ObservedValues finding={finding} />
      <ReviewList reviews={finding.reviews} label="Reviews in this run" />
      <ReviewList reviews={finding.earlier_reviews} label="Earlier reviews of the same finding (context only, not applied)" />
      {canReview && <ReviewForm fdrId={fdrId} finding={finding} onSaved={onReviewed} />}
    </li>
  )
}

function Collapsible({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-4 border-t border-slate-100 pt-3">
      <button type="button" className="inline-flex items-center gap-1 text-sm font-medium text-slate-700" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />} {title}
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  )
}

function RunView({ fdrId, run, onReviewed }: { fdrId: number; run: RunDetail; onReviewed: () => void }) {
  if (run.status === 'FAILED') {
    return (
      <div className="mt-4">
        <Alert tone="error" title={`Screening run #${run.run_number} failed`}>
          The screening engine stopped with an error ({run.error_code}). Nothing about the record was changed. You can run it again.
        </Alert>
      </div>
    )
  }
  return (
    <>
      {run.findings.length === 0 ? (
        <p className="mt-4 text-sm text-slate-600">No findings. This does not mean the FDR is genuine; it means none of the rules were triggered.</p>
      ) : (
        SEVERITY_ORDER.map((severity) => {
          const group = run.findings.filter((f) => f.severity === severity)
          if (!group.length) return null
          return (
            <section key={severity} className="mt-4">
              <h4 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">{SEVERITY_LABELS[severity]} ({group.length})</h4>
              <ul className="divide-y divide-slate-100">
                {group.map((f) => <FindingItem key={f.id} fdrId={fdrId} finding={f} canReview={run.is_latest} onReviewed={onReviewed} />)}
              </ul>
            </section>
          )
        })
      )}

      {run.no_longer_raised.length > 0 && (
        <div className="mt-4 rounded-md border border-slate-200 p-3 text-xs text-slate-700">
          <p className="font-medium">Not raised in this run (compared with run #{run.no_longer_raised[0].previous_run_number})</p>
          <p className="text-slate-500">These disappeared automatically because the rules no longer match; that is not a human review.</p>
          <ul className="mt-1 list-disc pl-5">
            {run.no_longer_raised.map((g) => (
              <li key={g.fingerprint}>{g.title} <span className="text-slate-500">({g.code}{g.reviewed_by_human ? '; had been reviewed by a person' : ''})</span></li>
            ))}
          </ul>
        </div>
      )}

      <Collapsible title={`Document reading (${run.extraction.length} document${run.extraction.length === 1 ? '' : 's'})`}>
        {run.extraction.length === 0 ? <p className="text-sm text-slate-600">No current documents.</p> : (
          <ul className="space-y-3">
            {run.extraction.map((doc) => (
              <li key={doc.document_id} className="text-xs">
                <p className="font-medium break-all text-slate-900">{doc.document_name}</p>
                <p className="text-slate-600">{EXTRACTION_STATUS_LABELS[doc.status] ?? doc.status}{doc.method && ` · ${doc.method}`}{doc.pages_read ? ` · ${doc.pages_read} page(s)` : ''}</p>
                {doc.note && <p className="text-slate-500">{doc.note}</p>}
                {doc.fields.length > 0 && (
                  <table className="mt-1 text-left">
                    <tbody>
                      {doc.fields.map((f, i) => (
                        <tr key={i}><td className="pr-3 text-slate-500">{f.field.replace(/_/g, ' ')}</td>
                          <td className="pr-3 font-mono text-slate-800">{f.value}</td>
                          <td className="text-slate-500">p.{f.page}: “{f.raw}”</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-[11px] text-slate-500">
          Values are read only from a PDF’s text layer, only when clearly labelled. No OCR, no external services. Reading a value does not show the document is genuine.
        </p>
      </Collapsible>
    </>
  )
}

/** AICTE-only advisory screening section on the FDR page. */
export default function ScreeningPanel({ fdrId, onActivity }: { fdrId: number; onActivity: () => void }) {
  const [key, setKey] = useState(0)
  const overview = useApiQuery<ScreeningOverview>(`/fdrs/${fdrId}/screening?k=${key}`)
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null)
  const selected = useApiQuery<RunDetail>(selectedRunId ? `/fdrs/${fdrId}/screening/runs/${selectedRunId}?k=${key}` : null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [justRan, setJustRan] = useState<RunDetail | null>(null)

  const refresh = () => {
    setKey((k) => k + 1)
    onActivity()
  }

  async function runNow() {
    setRunning(true)
    setRunError(null)
    setJustRan(null)
    try {
      const result = await apiRequest<RunDetail>(`/fdrs/${fdrId}/screening/runs`, { method: 'POST', timeoutMs: 60000 })
      setJustRan(result)
      setSelectedRunId(null)
      refresh()
    } catch (err) {
      setRunError(err instanceof ApiError ? err.message : 'Screening could not be started.')
    } finally {
      setRunning(false)
    }
  }

  const data = overview.data
  const latest = data?.latest
  const shown = selectedRunId && selected.data ? selected.data : latest

  return (
    <Card className="p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
            <ScanSearch className="size-4 text-navy-500" /> Advisory screening
          </h3>
          <p className="mt-1 text-xs text-slate-600">Visible to AICTE officials only.</p>
        </div>
        <button type="button" className={buttonStyles.secondary} onClick={runNow} disabled={running}>
          {running ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
          {running ? 'Screening…' : latest ? 'Run again' : 'Run screening'}
        </button>
      </div>

      {data && <p className="mt-3 rounded-md bg-slate-50 p-3 text-xs text-slate-600">{data.advisory_notice}</p>}
      {runError && <div className="mt-3"><Alert tone="error">{runError}</Alert></div>}
      {justRan && justRan.status === 'COMPLETED' && (
        <div className="mt-3"><Alert tone="info">Screening run #{justRan.run_number} completed. Earlier runs are kept below.</Alert></div>
      )}

      {overview.status === 'loading' && !data && <Spinner label="Loading screening…" />}
      {overview.status === 'error' && <div className="mt-3"><Alert tone="error">{overview.error.message}</Alert></div>}
      {data && !latest && <p className="mt-4 text-sm text-slate-600">This record has not been screened yet.</p>}

      {shown && (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <span className="text-sm font-medium text-slate-900">Run #{shown.run_number}</span>
            <PriorityBadge priority={shown.review_priority} />
            <span>{formatDateTime(shown.completed_at)} · by {shown.triggered_by.full_name}</span>
            <span className="font-mono text-[11px] text-slate-400">{shown.engine_version}</span>
          </div>
          {shown.status === 'COMPLETED' && (
            <p className="mt-1 text-xs text-slate-500">{shown.high_count} high · {shown.warning_count} warning · {shown.info_count} informational. {data?.priority_explanation}</p>
          )}
          {!shown.is_latest && (
            <div className="mt-3"><Alert tone="info" title="Viewing an earlier run">
              Reviews can only be recorded on the latest run. <button type="button" className="font-medium underline" onClick={() => setSelectedRunId(null)}>Show latest</button>
            </Alert></div>
          )}
          {shown.is_latest && shown.is_stale && (
            <div className="mt-3"><Alert tone="warning" title="Out of date">The record or its documents changed after this run. Run screening again for current results.</Alert></div>
          )}
          <RunView fdrId={fdrId} run={shown} onReviewed={refresh} />
        </>
      )}

      {data && data.runs.length > 1 && (
        <Collapsible title={`All runs (${data.runs.length})`}>
          <ul className="space-y-1 text-xs">
            {data.runs.map((r) => (
              <li key={r.id}>
                <button type="button" className="text-left text-navy-700 hover:underline" onClick={() => setSelectedRunId(r.id === latest?.id ? null : r.id)}>
                  Run #{r.run_number} · {formatDateTime(r.completed_at)} · {r.status === 'FAILED' ? 'failed' : `priority ${r.review_priority?.toLowerCase()}`} · {r.triggered_by.full_name}
                </button>
              </li>
            ))}
          </ul>
        </Collapsible>
      )}
    </Card>
  )
}
