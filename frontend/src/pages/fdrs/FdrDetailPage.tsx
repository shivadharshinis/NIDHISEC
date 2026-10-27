import { ArrowLeft, History, Loader2, Pencil } from 'lucide-react'
import { type FormEvent, type ReactNode, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { useCurrentUser } from '../../auth/AuthContext'
import DocumentsPanel from '../../components/fdrs/DocumentsPanel'
import LifecyclePanel from '../../components/lifecycle/LifecyclePanel'
import ScreeningPanel from '../../components/screening/ScreeningPanel'
import VerificationPanel from '../../components/verification/VerificationPanel'
import { Alert, Card, DuplicateBadge, Field, Spinner, StatusBadge, buttonStyles, inputStyles } from '../../components/ui'
import { useApiQuery } from '../../hooks/useApiQuery'
import { ApiError, apiRequest } from '../../lib/api'
import {
  AUDIT_ACTION_LABELS,
  formatDate,
  formatDateTime,
  formatINR,
  REVIEW_TRANSITIONS,
  ROLE_LABELS,
  LIFECYCLE_STATUS_LABELS,
  STATUS_LABELS,
  VERIFICATION_STATE_LABELS,
} from '../../lib/format'
import type { FdrDetail, FdrHistoryEntry, FdrStatus, VerificationHistory } from '../../types'

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-900">{children}</dd>
    </div>
  )
}

function DuplicatePanel({ fdr }: { fdr: FdrDetail }) {
  const review = fdr.duplicate_review
  if (!review.flagged) return null
  return (
    <Alert tone="warning" title={`Possible duplicate — matches ${review.match_count} other record${review.match_count === 1 ? '' : 's'}`}>
      <p>
        Another record has the same issuing bank and FDR reference after normalisation. This has been flagged for AICTE
        review. It is <strong>not</strong> a finding of fraud or error, and neither record has been changed.
      </p>
      {review.matches.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {review.matches.map((match) => (
            <li key={match.id} className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <Link to={`/fdr-records/${match.id}`} className="font-medium text-amber-950 underline">
                {match.fdr_number}
              </Link>
              <span>· {match.bank_name}</span>
              <span>· {match.same_institution ? 'same institution' : `${match.institution.code} — ${match.institution.name}`}</span>
              <StatusBadge status={match.status} />
            </li>
          ))}
        </ul>
      )}
      {review.hidden_match_count > 0 && (
        <p className="mt-2 text-xs">
          {review.hidden_match_count} matching record{review.hidden_match_count === 1 ? ' belongs' : 's belong'} to another
          institution; details are visible to AICTE officials only.
        </p>
      )}
    </Alert>
  )
}

const REVIEW_ACTION_LABELS: Record<FdrStatus, string> = {
  SUBMITTED: 'Return to submitted',
  UNDER_REVIEW: 'Mark as under review',
  CLARIFICATION_REQUESTED: 'Request clarification from the institution',
  REJECTED: 'Reject',
  ACCEPTED: 'Accept (bank officer recorded a confirmation)',
}

function ReviewPanel({ fdr, canAccept, onUpdated }: { fdr: FdrDetail; canAccept: boolean; onUpdated: (fdr: FdrDetail) => void }) {
  const options = REVIEW_TRANSITIONS[fdr.status]
  const [status, setStatus] = useState<FdrStatus | ''>('')
  const [remarks, setRemarks] = useState('')
  const [internalNotes, setInternalNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const needsRemarks = status === 'CLARIFICATION_REQUESTED' || status === 'REJECTED'

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!status) return setError('Choose a review action.')
    if (needsRemarks && remarks.trim().length === 0) return setError('Remarks are required for this action.')
    setSaving(true)
    setError(null)
    try {
      const updated = await apiRequest<FdrDetail>(`/fdrs/${fdr.id}/review`, {
        method: 'POST',
        body: { version: fdr.version, status, review_remarks: remarks.trim() || null, internal_notes: internalNotes.trim() || null },
      })
      setStatus('')
      setRemarks('')
      setInternalNotes('')
      onUpdated(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save the review.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="p-5">
      <h3 className="text-sm font-semibold text-slate-900">AICTE review</h3>
      <p className="mt-1 text-xs text-slate-600">
        Records an AICTE decision, kept separately from the bank officer’s outcome. Earlier decisions are never overwritten.
      </p>
      <form onSubmit={handleSubmit} className="mt-4 space-y-3" noValidate>
        {error && <Alert tone="error">{error}</Alert>}
        <Field id="review-status" label="Action" required>
          <select id="review-status" className={inputStyles} value={status} onChange={(e) => setStatus(e.target.value as FdrStatus | '')}>
            <option value="">Choose…</option>
            {options.map((option) => (
              <option key={option} value={option} disabled={option === 'ACCEPTED' && !canAccept}>
                {REVIEW_ACTION_LABELS[option]}
                {option === 'ACCEPTED' && !canAccept ? ' — needs a confirmed bank outcome' : ''}
              </option>
            ))}
          </select>
        </Field>
        <Field id="review-remarks" label="Message to the institution" required={needsRemarks} hint="Visible to the institution">
          <textarea id="review-remarks" rows={3} maxLength={1000} className={inputStyles} value={remarks} onChange={(e) => setRemarks(e.target.value)} />
        </Field>
        <Field id="review-internal" label="Internal notes" hint="AICTE officials only; never shown to the institution or bank">
          <textarea id="review-internal" rows={2} maxLength={2000} className={inputStyles} value={internalNotes} onChange={(e) => setInternalNotes(e.target.value)} />
        </Field>
        <button type="submit" className={`${buttonStyles.primary} w-full`} disabled={saving}>
          {saving && <Loader2 className="size-4 animate-spin" />} Save review
        </button>
      </form>
    </Card>
  )
}

function HistoryPanel({ fdrId, version, activityKey }: { fdrId: number; version: number; activityKey: number }) {
  // Changing the path re-fetches: after record changes (version) and document activity.
  const history = useApiQuery<FdrHistoryEntry[]>(`/fdrs/${fdrId}/history?v=${version}&a=${activityKey}`)
  return (
    <Card className="p-5">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
        <History className="size-4 text-navy-500" /> Record history
      </h3>
      {history.status === 'loading' && !history.data && <Spinner />}
      {history.status === 'error' && <p className="mt-3 text-sm text-red-700">{history.error.message}</p>}
      {history.data && (
        <ol className="mt-4 space-y-4 border-l border-slate-200 pl-4">
          {history.data.map((entry) => (
            <li key={entry.id} className="relative">
              <span className="absolute top-1.5 -left-[21px] size-2 rounded-full bg-navy-400" aria-hidden="true" />
              <p className="text-sm font-medium text-slate-900">{AUDIT_ACTION_LABELS[entry.action] ?? entry.action}</p>
              <p className="text-xs text-slate-600">{entry.summary}</p>
              <p className="mt-0.5 text-[11px] text-slate-500">
                {formatDateTime(entry.created_at)}
                {entry.actor_name && ` · ${entry.actor_name}`}
                {entry.actor_role && ` (${ROLE_LABELS[entry.actor_role]})`}
              </p>
            </li>
          ))}
        </ol>
      )}
    </Card>
  )
}

export default function FdrDetailPage() {
  const { fdrId } = useParams()
  const location = useLocation()
  const user = useCurrentUser()
  const result = useApiQuery<FdrDetail>(`/fdrs/${Number(fdrId)}`)
  const [override, setOverride] = useState<FdrDetail | null>(null)
  const [activityKey, setActivityKey] = useState(0)
  const isAicte = user.role === 'AICTE_OFFICIAL'
  const verification = useApiQuery<VerificationHistory>(isAicte ? `/fdrs/${Number(fdrId)}/verification?a=${activityKey}` : null)
  const refreshAll = () => {
    result.reload()
    setActivityKey((key) => key + 1)
  }
  const justSaved = (location.state as { justSaved?: string } | null)?.justSaved

  if (result.status === 'loading' && !result.data) return <Spinner label="Loading record…" />
  if (result.status === 'error') {
    return (
      <div className="space-y-4">
        <Link to="/fdr-records" className="inline-flex items-center gap-1 text-sm font-medium text-navy-600 hover:text-navy-800">
          <ArrowLeft className="size-4" /> FDR Records
        </Link>
        <Alert tone="error" title={result.error.status === 404 ? 'Record not found' : 'Could not load this record'}
          action={result.error.status !== 404 && <button type="button" className={buttonStyles.secondary} onClick={result.reload}>Try again</button>}>
          {result.error.status === 404 ? 'It does not exist or you do not have access to it.' : result.error.message}
        </Alert>
      </div>
    )
  }

  const fdr = override && override.id === result.data?.id && override.version >= (result.data?.version ?? 0) ? override : result.data
  if (!fdr) return null

  return (
    <div className="space-y-5">
      <Link to="/fdr-records" className="inline-flex items-center gap-1 text-sm font-medium text-navy-600 hover:text-navy-800">
        <ArrowLeft className="size-4" /> FDR Records
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-500">FDR / reference number</p>
          <h2 className="text-2xl font-semibold break-all text-slate-900">{fdr.fdr_number}</h2>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge status={fdr.status} />
            {fdr.possible_duplicate && <DuplicateBadge />}
          </div>
        </div>
        {fdr.can_edit && (
          <Link to={`/fdr-records/${fdr.id}/edit`} className={buttonStyles.secondary}>
            <Pencil className="size-4" /> Edit details
          </Link>
        )}
      </div>

      {justSaved && !override && (
        <Alert tone="info">{justSaved === 'created' ? 'FDR submitted.' : 'Changes saved.'} It is now awaiting AICTE review.</Alert>
      )}

      {fdr.status === 'ACCEPTED' ? (
        <Alert tone="info" title="Accepted by AICTE">
          AICTE accepted this record after a bank officer recorded that it matches their bank’s records. That outcome is
          the officer’s attestation; NidhiSec has no direct connection to bank systems.
        </Alert>
      ) : (
        <Alert tone="warning" title={VERIFICATION_STATE_LABELS[fdr.verification_state]}>
          These are the details entered by the institution. NidhiSec does not itself confirm that an FDR is genuine;
          bank officers check assigned records against their bank’s records, and AICTE reviews the result.
        </Alert>
      )}

      {!['ACTIVE', 'PROPOSED'].includes(fdr.lifecycle_status) && (
        <Alert tone="info" title={LIFECYCLE_STATUS_LABELS[fdr.lifecycle_status]}>
          This instrument is kept as history. It can no longer be edited, reviewed, verified or receive documents.
        </Alert>
      )}

      <DuplicatePanel fdr={fdr} />

      {fdr.review_remarks && (
        <Alert tone={fdr.status === 'REJECTED' ? 'error' : 'info'} title={`AICTE remarks (${STATUS_LABELS[fdr.status]})`}>
          {fdr.review_remarks}
        </Alert>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card className="p-5 sm:p-6">
            <h3 className="text-sm font-semibold text-slate-900">Record details</h3>
            <dl className="mt-4 grid gap-4 sm:grid-cols-2">
              <Detail label="Institution">{fdr.institution.name} ({fdr.institution.code})</Detail>
              <Detail label="Deposit amount"><span className="tabular-nums">{formatINR(fdr.amount)}</span></Detail>
              <Detail label="Issuing bank">{fdr.bank_name}</Detail>
              <Detail label="Branch">{fdr.branch_name ?? '—'}</Detail>
              <Detail label="Branch IFSC">{fdr.ifsc_code ?? '—'}</Detail>
              <Detail label="Status">{STATUS_LABELS[fdr.status]}</Detail>
              <Detail label="Issue date">{formatDate(fdr.issue_date)}</Detail>
              <Detail label="Maturity date">{formatDate(fdr.maturity_date)}</Detail>
              <Detail label="Submitted by">{fdr.created_by_name} on {formatDateTime(fdr.created_at)}</Detail>
              <Detail label="Last updated">{formatDateTime(fdr.updated_at)}</Detail>
              {fdr.remarks && (
                <div className="sm:col-span-2">
                  <Detail label="Institution remarks"><span className="whitespace-pre-line">{fdr.remarks}</span></Detail>
                </div>
              )}
            </dl>
          </Card>

          <DocumentsPanel fdrId={fdr.id} onChanged={() => setActivityKey((key) => key + 1)} />
          <LifecyclePanel fdr={fdr} refreshKey={activityKey} />
          {isAicte && <VerificationPanel history={verification} onChanged={refreshAll} />}
          {isAicte && <ScreeningPanel fdrId={fdr.id} onActivity={() => setActivityKey((key) => key + 1)} />}
        </div>

        <div className="space-y-5">
          {fdr.can_review && isAicte && (
            <ReviewPanel
              fdr={fdr}
              canAccept={verification.data?.can_accept ?? false}
              onUpdated={(updated) => {
                setOverride(updated)
                setActivityKey((key) => key + 1)
              }}
            />
          )}
          <HistoryPanel fdrId={fdr.id} version={fdr.version} activityKey={activityKey} />
        </div>
      </div>
    </div>
  )
}
