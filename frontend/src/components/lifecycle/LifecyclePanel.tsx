import { CalendarClock, Loader2, Send } from 'lucide-react'
import { type FormEvent, type ReactNode, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useCurrentUser } from '../../auth/AuthContext'
import { useApiQuery } from '../../hooks/useApiQuery'
import { ApiError, apiRequest } from '../../lib/api'
import {
  describeDays,
  formatDate,
  formatDateTime,
  formatINR,
  LIFECYCLE_STATUS_LABELS,
  REQUEST_STATUS_LABELS,
  REQUEST_STATUS_STYLES,
  REQUEST_TYPE_LABELS,
  todayIso,
} from '../../lib/format'
import type { FdrDetail, FdrFormValues, FdrLifecycle, LifecycleRequestDetail, LifecycleRequestRead, LifecycleRequestType } from '../../types'
import { toPayload, validateFdrForm } from '../fdrs/FdrForm'
import { Alert, Card, Field, Spinner, buttonStyles, inputStyles } from '../ui'

export function RequestStatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset ${REQUEST_STATUS_STYLES[status] ?? ''}`}>
      {REQUEST_STATUS_LABELS[status] ?? status}
    </span>
  )
}

function RequestRow({ req }: { req: LifecycleRequestRead }) {
  return (
    <li className="flex flex-wrap items-center gap-2 py-2 text-sm">
      <Link to={`/lifecycle-requests/${req.id}`} className="font-medium text-navy-700 hover:underline">
        {REQUEST_TYPE_LABELS[req.request_type]} request #{req.id}
      </Link>
      <RequestStatusBadge status={req.status} />
      <span className="text-xs text-slate-500">submitted {formatDateTime(req.created_at)}</span>
      {req.successor && (
        <Link to={`/fdr-records/${req.successor.id}`} className="text-xs text-navy-600 hover:underline">
          new instrument {req.successor.fdr_number}
        </Link>
      )}
    </li>
  )
}

const SUCCESSOR_FIELDS: [keyof FdrFormValues, string, string?][] = [
  ['bank_name', 'Bank name'], ['branch_name', 'Branch', 'Optional'], ['ifsc_code', 'Branch IFSC', 'Optional'],
  ['fdr_number', 'New FDR / reference number'], ['amount', 'Deposit amount (₹)'],
  ['issue_date', 'Issue date'], ['maturity_date', 'Maturity date'],
]

function RequestForm({ fdr, lifecycle, onCreated }: { fdr: FdrDetail; lifecycle: FdrLifecycle; onCreated: (id: number) => void }) {
  const allowedTypes = (Object.keys(lifecycle.eligibility) as LifecycleRequestType[]).filter((t) => lifecycle.eligibility[t].allowed)
  const [type, setType] = useState<LifecycleRequestType | ''>('')
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [values, setValues] = useState<FdrFormValues>({
    bank_name: fdr.bank_name, branch_name: fdr.branch_name ?? '', ifsc_code: fdr.ifsc_code ?? '', fdr_number: '',
    amount: fdr.amount, issue_date: todayIso(), maturity_date: '', remarks: '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [saving, setSaving] = useState(false)
  const needsSuccessor = type === 'RENEWAL' || type === 'REPLACEMENT'

  function check(): boolean {
    const found: Record<string, string> = {}
    if (!type) found.type = 'Choose a request type.'
    if (reason.trim().length < 20) found.reason = 'Explain the request in at least 20 characters.'
    if (needsSuccessor) {
      Object.assign(found, validateFdrForm(values))
      if (type === 'RENEWAL' && values.maturity_date && values.maturity_date <= fdr.maturity_date)
        found.maturity_date = `A renewal must mature after ${formatDate(fdr.maturity_date)}.`
    }
    setErrors(found)
    setFormError(Object.keys(found).length ? 'Please correct the highlighted fields.' : null)
    return Object.keys(found).length === 0
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!confirming) {
      if (check()) setConfirming(true)
      return
    }
    setSaving(true)
    setFormError(null)
    try {
      const created = await apiRequest<LifecycleRequestDetail>(`/fdrs/${fdr.id}/lifecycle-requests`, {
        method: 'POST',
        body: {
          request_type: type, fdr_version: lifecycle.fdr_version, reason: reason.trim(),
          supporting_note: note.trim() || null, successor: needsSuccessor ? toPayload(values) : null,
        },
      })
      onCreated(created.id)
    } catch (err) {
      setConfirming(false)
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors)
        setFormError(err.message)
      } else setFormError('Could not submit the request.')
    } finally {
      setSaving(false)
    }
  }

  if (allowedTypes.length === 0) return null
  return (
    <form onSubmit={submit} noValidate className="mt-4 space-y-3 rounded-md border border-dashed border-slate-300 bg-slate-50 p-4">
      <p className="text-sm font-medium text-slate-900">New lifecycle request</p>
      {formError && <Alert tone="error">{formError}</Alert>}
      <Field id="lc-type" label="Request" required error={errors.type}>
        <select id="lc-type" className={inputStyles} value={type} disabled={confirming}
          onChange={(e) => { setType(e.target.value as LifecycleRequestType | ''); setConfirming(false) }}>
          <option value="">Choose…</option>
          {allowedTypes.map((t) => <option key={t} value={t}>{REQUEST_TYPE_LABELS[t]}</option>)}
        </select>
      </Field>
      <Field id="lc-reason" label="Reason" required error={errors.reason} hint="At least 20 characters; visible to AICTE">
        <textarea id="lc-reason" rows={3} maxLength={2000} className={inputStyles} value={reason} disabled={confirming}
          onChange={(e) => setReason(e.target.value)} />
      </Field>
      {type === 'RELEASE' && (
        <Field id="lc-note" label="Supporting information" hint="Optional. Attach documents to this FDR using Supporting documents.">
          <textarea id="lc-note" rows={2} maxLength={2000} className={inputStyles} value={note} disabled={confirming} onChange={(e) => setNote(e.target.value)} />
        </Field>
      )}
      {needsSuccessor && (
        <fieldset className="grid gap-3 sm:grid-cols-2" disabled={confirming}>
          <legend className="mb-1 text-sm font-medium text-slate-700 sm:col-span-2">New instrument details</legend>
          {SUCCESSOR_FIELDS.map(([key, label, hint]) => (
            <Field key={key} id={`lc-${key}`} label={label} required={!hint} hint={hint} error={errors[key]}>
              <input id={`lc-${key}`} className={inputStyles} type={key.endsWith('_date') ? 'date' : 'text'} value={values[key]}
                aria-invalid={Boolean(errors[key])} onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))} />
            </Field>
          ))}
          <p className="text-xs text-slate-600 sm:col-span-2">
            The new instrument is saved as a separate proposed record. Attach its documents there; AICTE verifies it through the
            normal bank verification workflow. The current FDR and its documents stay unchanged.
          </p>
        </fieldset>
      )}
      {confirming && (
        <Alert tone="warning" title="Confirm this request">
          Submit a {REQUEST_TYPE_LABELS[type].toLowerCase()} request for FDR {fdr.fdr_number}? AICTE will review it. You can withdraw
          it until AICTE decides.
        </Alert>
      )}
      <div className="flex gap-2">
        <button type="submit" className={buttonStyles.primary} disabled={saving}>
          {saving ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />} {confirming ? 'Confirm and submit' : 'Review request'}
        </button>
        {confirming && <button type="button" className={buttonStyles.secondary} onClick={() => setConfirming(false)}>Edit</button>}
      </div>
    </form>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-900">{children}</dd>
    </div>
  )
}

/** Lifecycle status, eligibility and requests for one FDR (institutions and AICTE). */
export default function LifecyclePanel({ fdr, refreshKey }: { fdr: FdrDetail; refreshKey: number }) {
  const user = useCurrentUser()
  const navigate = useNavigate()
  const result = useApiQuery<FdrLifecycle>(`/fdrs/${fdr.id}/lifecycle?k=${refreshKey}&v=${fdr.version}`)
  const data = result.data

  return (
    <Card className="p-5 sm:p-6">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
        <CalendarClock className="size-4 text-navy-500" /> Lifecycle
      </h3>
      {result.status === 'loading' && !data && <Spinner />}
      {result.status === 'error' && <p className="mt-3 text-sm text-red-700">{result.error.message}</p>}
      {data && (
        <>
          <dl className="mt-3 grid gap-3 sm:grid-cols-3">
            <Row label="Lifecycle status">{LIFECYCLE_STATUS_LABELS[data.lifecycle_status]}</Row>
            <Row label="Maturity">{formatDate(data.maturity_date)}</Row>
            <Row label="Timing">
              <span className={data.days_to_maturity < 0 ? 'text-red-700' : data.days_to_maturity <= 30 ? 'text-amber-700' : ''}>
                {describeDays(data.days_to_maturity)}
              </span>
            </Row>
          </dl>
          {data.days_to_maturity < 0 && data.lifecycle_status === 'ACTIVE' && (
            <p className="mt-2 text-xs text-slate-600">Matured instruments are never released automatically; a release, renewal or replacement must be requested and decided.</p>
          )}
          {data.proposed_by_request && (
            <div className="mt-3"><Alert tone="info" title="Proposed new instrument">
              This record was submitted with <Link className="font-medium underline" to={`/lifecycle-requests/${data.proposed_by_request.id}`}>
                {REQUEST_TYPE_LABELS[data.proposed_by_request.request_type].toLowerCase()} request #{data.proposed_by_request.id}</Link> for
              FDR <Link className="font-medium underline" to={`/fdr-records/${data.proposed_by_request.fdr.id}`}>{data.proposed_by_request.fdr.fdr_number}</Link>
              {' '}({formatINR(data.proposed_by_request.fdr.amount)}). It takes effect only when AICTE records completion.
            </Alert></div>
          )}
          {data.requests.length > 0 && (
            <>
              <h4 className="mt-4 text-xs font-semibold tracking-wide text-slate-500 uppercase">Requests</h4>
              <ul className="divide-y divide-slate-100">{data.requests.map((r) => <RequestRow key={r.id} req={r} />)}</ul>
            </>
          )}
          {user.role === 'INSTITUTION' && data.lifecycle_status === 'ACTIVE' && (
            <>
              {(Object.keys(data.eligibility) as LifecycleRequestType[]).every((t) => !data.eligibility[t].allowed) && (
                <div className="mt-3 text-xs text-slate-600">
                  <p className="font-medium text-slate-700">No lifecycle request can be made right now:</p>
                  <ul className="mt-1 list-disc pl-5">
                    {[...new Set(Object.values(data.eligibility).flatMap((e) => e.reasons))].map((r) => <li key={r}>{r}</li>)}
                  </ul>
                </div>
              )}
              <RequestForm fdr={fdr} lifecycle={data} onCreated={(id) => navigate(`/lifecycle-requests/${id}`)} />
            </>
          )}
        </>
      )}
    </Card>
  )
}
