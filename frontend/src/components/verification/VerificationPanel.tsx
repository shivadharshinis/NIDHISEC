import { ArrowRightLeft, BadgeCheck, Loader2, Send } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { useApiQuery } from '../../hooks/useApiQuery'
import { ApiError, apiRequest } from '../../lib/api'
import {
  ASSIGNMENT_STATUS_LABELS,
  formatDateTime,
  OUTCOME_LABELS,
  OUTCOME_STYLES,
  STATUS_LABELS,
  VERIFICATION_STATE_LABELS,
} from '../../lib/format'
import type { AssignmentRead, AssignmentStatus, OutcomeRead, OutcomeType, UserBrief, VerificationHistory } from '../../types'
import { Alert, Card, Field, Spinner, buttonStyles, inputStyles } from '../ui'

export function OutcomeBadge({ outcome }: { outcome: OutcomeType }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${OUTCOME_STYLES[outcome]}`}>
      {OUTCOME_LABELS[outcome]}
    </span>
  )
}

export function AssignmentStatusBadge({ status }: { status: AssignmentStatus }) {
  const style = status === 'ACTIVE' ? 'bg-sky-50 text-sky-800 ring-sky-200' : 'bg-slate-100 text-slate-700 ring-slate-300'
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}>
      {ASSIGNMENT_STATUS_LABELS[status]}
    </span>
  )
}

/** Disclaimer shown wherever an officer's outcome appears. */
export const OUTCOME_DISCLAIMER =
  'Recorded by the bank officer as their own attestation. NidhiSec has no connection to bank systems, so this is not independent proof that the FDR is genuine.'

export function OutcomeDetails({ outcome }: { outcome: OutcomeRead }) {
  return (
    <div className="mt-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
      <div className="flex flex-wrap items-center gap-2">
        <OutcomeBadge outcome={outcome.outcome} />
        <span className="text-slate-500">
          {formatDateTime(outcome.submitted_at)} · {outcome.submitted_by.full_name}
        </span>
      </div>
      <p className="mt-2 whitespace-pre-line text-slate-800">{outcome.notes}</p>
      {outcome.bank_reference && <p className="mt-1">Bank reference: <span className="font-mono">{outcome.bank_reference}</span></p>}
      {outcome.evidence_documents.length > 0 && (
        <p className="mt-1">
          Evidence reviewed:{' '}
          {outcome.evidence_documents.map((doc) => `${doc.original_filename} (SHA-256 ${doc.sha256.slice(0, 12)}…)`).join(', ')}
        </p>
      )}
      <p className="mt-2 text-[11px] text-slate-500">{OUTCOME_DISCLAIMER}</p>
    </div>
  )
}

function OfficerSelect({ id, value, onChange, officers, exclude }: {
  id: string
  value: string
  onChange: (value: string) => void
  officers: UserBrief[] | undefined
  exclude?: number
}) {
  return (
    <select id={id} className={inputStyles} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Choose a bank officer…</option>
      {officers?.filter((o) => o.id !== exclude).map((o) => (
        <option key={o.id} value={o.id}>{o.full_name} — {o.email}</option>
      ))}
    </select>
  )
}

function AssignForm({ history, officers, onDone }: { history: VerificationHistory; officers?: UserBrief[]; onDone: () => void }) {
  const [officerId, setOfficerId] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!officerId) return setError('Choose a bank officer.')
    setSaving(true)
    setError(null)
    try {
      await apiRequest(`/fdrs/${history.fdr_id}/verification/assignments`, {
        method: 'POST',
        body: { bank_officer_id: Number(officerId), fdr_version: history.fdr_version, note: note.trim() || null },
      })
      setOfficerId('')
      setNote('')
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? (err.fieldErrors.bank_officer_id ?? err.message) : 'Could not assign the case.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="mt-4 space-y-3 rounded-md border border-dashed border-slate-300 bg-slate-50 p-4">
      <p className="text-sm font-medium text-slate-900">Assign for bank verification</p>
      {error && <Alert tone="error">{error}</Alert>}
      <Field id="assign-officer" label="Bank officer" required>
        <OfficerSelect id="assign-officer" value={officerId} onChange={setOfficerId} officers={officers} />
      </Field>
      <Field id="assign-note" label="Instructions to the officer" hint="Visible to the assigned officer, not to the institution">
        <textarea id="assign-note" rows={2} maxLength={1000} className={inputStyles} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <p className="text-xs text-slate-600">
        A Submitted record moves to Under review, and the institution can no longer edit its details while the bank checks them.
      </p>
      <button type="submit" className={buttonStyles.primary} disabled={saving}>
        {saving ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />} Assign
      </button>
    </form>
  )
}

function ReassignForm({ assignment, officers, onDone }: { assignment: AssignmentRead; officers?: UserBrief[]; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [officerId, setOfficerId] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  if (!open) {
    return (
      <button type="button" className={`${buttonStyles.secondary} mt-3`} onClick={() => setOpen(true)}>
        <ArrowRightLeft className="size-4" /> Reassign
      </button>
    )
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!officerId) return setError('Choose the new bank officer.')
    if (reason.trim().length < 10) return setError('Give a reason of at least 10 characters.')
    setSaving(true)
    setError(null)
    try {
      await apiRequest(`/verification/assignments/${assignment.id}/reassign`, {
        method: 'POST',
        body: { bank_officer_id: Number(officerId), version: assignment.version, reason: reason.trim() },
      })
      setOpen(false)
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? (err.fieldErrors.bank_officer_id ?? err.fieldErrors.reason ?? err.message) : 'Could not reassign.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="mt-3 space-y-3">
      {error && <Alert tone="error">{error}</Alert>}
      <Field id="reassign-officer" label="New bank officer" required>
        <OfficerSelect id="reassign-officer" value={officerId} onChange={setOfficerId} officers={officers} exclude={assignment.bank_officer.id} />
      </Field>
      <Field id="reassign-reason" label="Reason" required hint="Kept in the assignment history">
        <input id="reassign-reason" className={inputStyles} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <div className="flex gap-2">
        <button type="submit" className={buttonStyles.primary} disabled={saving}>
          {saving && <Loader2 className="size-4 animate-spin" />} Confirm reassignment
        </button>
        <button type="button" className={buttonStyles.secondary} onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </form>
  )
}

function AssignmentEntry({ assignment }: { assignment: AssignmentRead }) {
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium text-slate-900">#{assignment.id} · {assignment.bank_officer.full_name}</span>
        <AssignmentStatusBadge status={assignment.status} />
      </div>
      <p className="mt-0.5 text-xs text-slate-600">
        Assigned {formatDateTime(assignment.assigned_at)} by {assignment.assigned_by.full_name}
        {assignment.previous_assignment_id && ` · replaces #${assignment.previous_assignment_id}`}
      </p>
      {assignment.assignment_note && <p className="mt-1 text-xs text-slate-700">Instructions: {assignment.assignment_note}</p>}
      {assignment.end_reason && (
        <p className="mt-1 text-xs text-slate-700">
          {ASSIGNMENT_STATUS_LABELS[assignment.status]} {assignment.ended_at && formatDateTime(assignment.ended_at)}
          {assignment.ended_by && ` by ${assignment.ended_by.full_name}`}: {assignment.end_reason}
        </p>
      )}
      {assignment.outcome && <OutcomeDetails outcome={assignment.outcome} />}
    </li>
  )
}

/** AICTE view of bank verification for one FDR: assign, reassign and full history. */
export default function VerificationPanel({ history, onChanged }: {
  history: ReturnType<typeof useApiQuery<VerificationHistory>>
  onChanged: () => void
}) {
  const officers = useApiQuery<UserBrief[]>('/verification/officers')
  const data = history.data

  return (
    <Card className="p-5 sm:p-6">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
        <BadgeCheck className="size-4 text-navy-500" /> Bank verification
      </h3>
      {history.status === 'loading' && !data && <Spinner />}
      {history.status === 'error' && <p className="mt-3 text-sm text-red-700">{history.error.message}</p>}
      {data && (
        <>
          <p className="mt-1 text-xs text-slate-600">
            {data.fdr_status === 'ACCEPTED'
              ? 'Accepted by AICTE on the basis of the bank officer’s recorded confirmation.'
              : `${VERIFICATION_STATE_LABELS[data.state]}.`}
          </p>

          {data.active_assignment && (
            <div className="mt-4 rounded-md border border-sky-200 bg-sky-50 p-4 text-sm">
              <p className="font-medium text-sky-900">With {data.active_assignment.bank_officer.full_name}</p>
              <p className="text-xs text-sky-800">
                Since {formatDateTime(data.active_assignment.assigned_at)} · assignment #{data.active_assignment.id}
              </p>
              <ReassignForm assignment={data.active_assignment} officers={officers.data} onDone={onChanged} />
            </div>
          )}

          {data.can_assign && <AssignForm history={data} officers={officers.data} onDone={onChanged} />}
          {officers.data?.length === 0 && data.can_assign && (
            <p className="mt-2 text-xs text-amber-800">No active bank officer accounts exist.</p>
          )}

          {data.assignments.length > 0 && (
            <>
              <h4 className="mt-5 text-xs font-semibold tracking-wide text-slate-500 uppercase">Assignment history</h4>
              <ul className="divide-y divide-slate-100">
                {data.assignments.map((assignment) => <AssignmentEntry key={assignment.id} assignment={assignment} />)}
              </ul>
            </>
          )}

          {data.decisions.length > 0 && (
            <>
              <h4 className="mt-5 text-xs font-semibold tracking-wide text-slate-500 uppercase">AICTE decisions</h4>
              <ul className="divide-y divide-slate-100">
                {data.decisions.map((decision) => (
                  <li key={decision.id} className="py-3 text-xs text-slate-700">
                    <p className="text-sm font-medium text-slate-900">
                      {STATUS_LABELS[decision.previous_status]} → {STATUS_LABELS[decision.new_status]}
                    </p>
                    <p className="text-slate-500">{formatDateTime(decision.decided_at)} · {decision.decided_by.full_name}</p>
                    {decision.message_to_institution && <p className="mt-1">To institution: {decision.message_to_institution}</p>}
                    {decision.internal_notes && <p className="mt-1">Internal notes: {decision.internal_notes}</p>}
                    {decision.reviewed_outcome_id && <p className="mt-1 text-slate-500">Based on bank outcome #{decision.reviewed_outcome_id}</p>}
                  </li>
                ))}
              </ul>
            </>
          )}
          {data.assignments.length === 0 && !data.can_assign && (
            <p className="mt-3 text-sm text-slate-600">This record is not eligible for assignment in its current status.</p>
          )}
        </>
      )}
    </Card>
  )
}
