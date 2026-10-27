import { ArrowLeft, Loader2 } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useCurrentUser } from '../../auth/AuthContext'
import { RequestStatusBadge } from '../../components/lifecycle/LifecyclePanel'
import { Alert, Card, Field, Spinner, StatusBadge, buttonStyles, inputStyles } from '../../components/ui'
import { useApiQuery } from '../../hooks/useApiQuery'
import { ApiError, apiRequest } from '../../lib/api'
import {
  formatDate,
  formatDateTime,
  formatINR,
  LIFECYCLE_ACTION_LABELS,
  LIFECYCLE_STATUS_LABELS,
  REQUEST_STATUS_LABELS,
  REQUEST_TYPE_LABELS,
  ROLE_LABELS,
} from '../../lib/format'
import type { FdrBrief, LifecycleAction, LifecycleRequestDetail } from '../../types'

const ACTION_COPY: Record<LifecycleAction, { label: string; confirm: string; message?: string; danger?: boolean }> = {
  START_REVIEW: { label: 'Start review', confirm: 'Mark this request as under review?' },
  REQUEST_CLARIFICATION: { label: 'Request clarification', confirm: 'Send this request back to the institution for clarification?', message: 'Message to the institution' },
  APPROVE: { label: 'Approve', confirm: 'Approve this request? Approval is a decision only; completion must be recorded separately.', message: 'Message to the institution (optional)' },
  REJECT: { label: 'Reject', confirm: 'Reject this request? This cannot be undone. A proposed new instrument will be cancelled.', message: 'Reason (shown to the institution)', danger: true },
  COMPLETE: { label: 'Record completion', confirm: 'Record that this request has been completed? This changes the instrument’s lifecycle status. It does not move or confirm any money.', message: 'Completion note' },
  RESPOND: { label: 'Respond to clarification', confirm: 'Send your response to AICTE?', message: 'Your response' },
  WITHDRAW: { label: 'Withdraw request', confirm: 'Withdraw this request? This cannot be undone.', message: 'Reason for withdrawal', danger: true },
}
const MESSAGE_REQUIRED: LifecycleAction[] = ['REQUEST_CLARIFICATION', 'REJECT', 'RESPOND', 'WITHDRAW', 'COMPLETE']

function Instrument({ title, fdr }: { title: string; fdr: FdrBrief }) {
  return (
    <div className="rounded-md border border-slate-200 p-3 text-sm">
      <p className="text-xs font-medium text-slate-500">{title}</p>
      <Link to={`/fdr-records/${fdr.id}`} className="font-medium text-navy-700 hover:underline">{fdr.fdr_number}</Link>
      <p className="text-xs text-slate-600">{fdr.bank_name} · {formatINR(fdr.amount)}</p>
      <p className="text-xs text-slate-600">{formatDate(fdr.issue_date)} → {formatDate(fdr.maturity_date)}</p>
      <div className="mt-1 flex flex-wrap gap-1"><StatusBadge status={fdr.status} />
        <span className="text-xs text-slate-500">{LIFECYCLE_STATUS_LABELS[fdr.lifecycle_status]}</span></div>
    </div>
  )
}

function ActionForm({ req, action, onDone }: { req: LifecycleRequestDetail; action: LifecycleAction; onDone: (r: LifecycleRequestDetail) => void }) {
  const user = useCurrentUser()
  const copy = ACTION_COPY[action]
  const [message, setMessage] = useState('')
  const [internal, setInternal] = useState('')
  const [reference, setReference] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const needsMessage = MESSAGE_REQUIRED.includes(action)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (needsMessage && message.trim().length < 10) return setError('Please write at least 10 characters.')
    if (message.trim() && message.trim().length < 10) return setError('Messages must be at least 10 characters.')
    if (!confirming) return setConfirming(true)
    setSaving(true)
    setError(null)
    try {
      const updated = await apiRequest<LifecycleRequestDetail>(`/lifecycle-requests/${req.id}/transitions`, {
        method: 'POST',
        body: {
          action, version: req.version, message: message.trim() || null,
          internal_note: user.role === 'AICTE_OFFICIAL' ? internal.trim() || null : null,
          completion_reference: action === 'COMPLETE' ? reference.trim() || null : null,
        },
      })
      onDone(updated)
    } catch (err) {
      setConfirming(false)
      setError(err instanceof ApiError ? (err.fieldErrors.message ?? err.fieldErrors.completion_reference ?? err.message) : 'Action failed.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-2 rounded-md border border-slate-200 p-3">
      <p className="text-sm font-medium text-slate-900">{copy.label}</p>
      {error && <Alert tone="error">{error}</Alert>}
      {copy.message && (
        <Field id={`${action}-message`} label={copy.message} required={needsMessage}>
          <textarea id={`${action}-message`} rows={2} maxLength={2000} className={inputStyles} value={message} disabled={confirming} onChange={(e) => setMessage(e.target.value)} />
        </Field>
      )}
      {user.role === 'AICTE_OFFICIAL' && action !== 'START_REVIEW' && (
        <Field id={`${action}-internal`} label="Internal note" hint="AICTE only; never shown to the institution">
          <input id={`${action}-internal`} className={inputStyles} maxLength={2000} value={internal} disabled={confirming} onChange={(e) => setInternal(e.target.value)} />
        </Field>
      )}
      {action === 'COMPLETE' && (
        <Field id="complete-reference" label="Administrative reference" hint="Optional, e.g. an order number. Not a payment record.">
          <input id="complete-reference" className={inputStyles} maxLength={100} value={reference} disabled={confirming} onChange={(e) => setReference(e.target.value)} />
        </Field>
      )}
      {confirming && <Alert tone={copy.danger ? 'error' : 'warning'}>{copy.confirm}</Alert>}
      <div className="flex gap-2">
        <button type="submit" className={copy.danger && confirming ? buttonStyles.primary.replace('bg-navy-700', 'bg-red-700').replace('hover:bg-navy-800', 'hover:bg-red-800') : buttonStyles.primary} disabled={saving}>
          {saving && <Loader2 className="size-4 animate-spin" />} {confirming ? `Confirm: ${copy.label.toLowerCase()}` : copy.label}
        </button>
        {confirming && <button type="button" className={buttonStyles.secondary} onClick={() => setConfirming(false)}>Cancel</button>}
      </div>
    </form>
  )
}

export default function LifecycleRequestPage() {
  const { requestId } = useParams()
  const user = useCurrentUser()
  const result = useApiQuery<LifecycleRequestDetail>(`/lifecycle-requests/${Number(requestId)}`)
  const [updated, setUpdated] = useState<LifecycleRequestDetail | null>(null)
  const req = updated ?? result.data
  const backTo = req?.request_type === 'RELEASE' ? '/release-requests' : '/renewals'

  if (result.status === 'loading' && !req) return <Spinner label="Loading request…" />
  if (result.status === 'error' && !req) {
    return <Alert tone="error" title={result.error.status === 404 ? 'Request not found' : 'Could not load this request'}>
      {result.error.status === 404 ? 'It does not exist or you do not have access to it.' : result.error.message}</Alert>
  }
  if (!req) return null

  return (
    <div className="space-y-5">
      <Link to={backTo} className="inline-flex items-center gap-1 text-sm font-medium text-navy-600 hover:text-navy-800">
        <ArrowLeft className="size-4" /> {req.request_type === 'RELEASE' ? 'Release requests' : 'Renewals & maturity'}
      </Link>
      <div>
        <p className="text-xs font-medium text-slate-500">{req.institution.code} · {req.institution.name}</p>
        <h2 className="text-2xl font-semibold text-slate-900">{REQUEST_TYPE_LABELS[req.request_type]} request #{req.id}</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2"><RequestStatusBadge status={req.status} />
          <span className="text-xs text-slate-500">submitted {formatDateTime(req.created_at)} by {req.created_by_name}</span></div>
      </div>
      {updated && <Alert tone="info">Saved. The request is now {REQUEST_STATUS_LABELS[updated.status].toLowerCase()}.</Alert>}
      {req.status === 'APPROVED' && (
        <Alert tone="info" title="Approved, not yet completed">
          Approval is a decision only. The instrument’s lifecycle changes when AICTE records completion. NidhiSec does not move or confirm funds.
        </Alert>
      )}
      {req.status === 'COMPLETED' && req.request_type === 'RELEASE' && (
        <Alert tone="info" title="Release recorded">
          AICTE recorded completion{req.completion_reference && ` (reference ${req.completion_reference})`} on {req.completed_at && formatDateTime(req.completed_at)}.
          This is an administrative record; NidhiSec has no connection to any payment system.
        </Alert>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card className="p-5 sm:p-6">
            <div className="grid gap-3 sm:grid-cols-2">
              <Instrument title="Current instrument" fdr={req.fdr} />
              {req.successor && <Instrument title="Proposed new instrument" fdr={req.successor} />}
            </div>
            <h3 className="mt-4 text-xs font-semibold tracking-wide text-slate-500 uppercase">Reason</h3>
            <p className="mt-1 text-sm whitespace-pre-line text-slate-800">{req.reason}</p>
            {req.supporting_note && <p className="mt-2 text-sm text-slate-700">Supporting information: {req.supporting_note}</p>}
            {req.successor && user.role === 'INSTITUTION' && ['SUBMITTED', 'UNDER_REVIEW', 'CLARIFICATION_REQUESTED'].includes(req.status) && (
              <p className="mt-3 text-xs text-slate-600">
                Attach the new instrument’s documents on its <Link to={`/fdr-records/${req.successor.id}`} className="font-medium text-navy-600 underline">record page</Link>.
              </p>
            )}
          </Card>
          <Card className="p-5 sm:p-6">
            <h3 className="text-sm font-semibold text-slate-900">History</h3>
            <ol className="mt-3 space-y-3 border-l border-slate-200 pl-4">
              {req.events.map((e) => (
                <li key={e.id} className="relative">
                  <span className="absolute top-1.5 -left-[21px] size-2 rounded-full bg-navy-400" aria-hidden="true" />
                  <p className="text-sm font-medium text-slate-900">{LIFECYCLE_ACTION_LABELS[e.action] ?? e.action}
                    <span className="font-normal text-slate-500"> → {REQUEST_STATUS_LABELS[e.to_status]}</span></p>
                  {e.message && <p className="text-sm text-slate-700">{e.message}</p>}
                  {e.internal_note && <p className="text-xs text-slate-600">Internal note: {e.internal_note}</p>}
                  <p className="text-[11px] text-slate-500">{formatDateTime(e.created_at)} · {e.actor_name} ({ROLE_LABELS[e.actor_role]})</p>
                </li>
              ))}
            </ol>
          </Card>
        </div>
        <div className="space-y-3">
          {req.completion_blockers.length > 0 && (
            <Alert tone="warning" title="Completion not yet possible"><ul className="list-disc pl-4">{req.completion_blockers.map((b) => <li key={b}>{b}</li>)}</ul></Alert>
          )}
          {req.allowed_actions.length === 0 && <Card className="p-4 text-sm text-slate-600">No actions are available to you for this request.</Card>}
          {req.allowed_actions.map((action) => (
            <ActionForm key={`${action}-${req.version}`} req={req} action={action} onDone={setUpdated} />
          ))}
        </div>
      </div>
    </div>
  )
}
