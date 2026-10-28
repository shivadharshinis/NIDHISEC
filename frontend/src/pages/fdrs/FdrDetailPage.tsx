import { ArrowLeft, CheckCircle2, History, Loader2, Pencil, XCircle } from 'lucide-react'
import { type FormEvent, type ReactNode, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { useCurrentUser } from '../../auth/AuthContext'
import DocumentsPanel from '../../components/fdrs/DocumentsPanel'
import LifecyclePanel from '../../components/lifecycle/LifecyclePanel'
import ScreeningPanel from '../../components/screening/ScreeningPanel'
import VerificationPanel, { OutcomeBadge } from '../../components/verification/VerificationPanel'
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
  OUTCOME_LABELS,
  STATUS_LABELS,
  VERIFICATION_STATE_LABELS,
} from '../../lib/format'
import type { FdrDetail, FdrHistoryEntry, FdrStatus, OutcomeRead, ScreeningOverview, VerificationHistory } from '../../types'

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

type DecisionAction = Exclude<FdrStatus, 'SUBMITTED'>

const ACTION_COPY: Record<DecisionAction, { title: string; confirm: string; message: string; messageRequired: boolean }> = {
  ACCEPTED: { title: 'Accept this FDR', confirm: 'Confirm acceptance', message: 'Message to the institution', messageRequired: false },
  REJECTED: { title: 'Reject this FDR', confirm: 'Confirm rejection', message: 'Reason for rejection', messageRequired: true },
  CLARIFICATION_REQUESTED: {
    title: 'Request clarification', confirm: 'Send to institution', message: 'What the institution must clarify or correct', messageRequired: true,
  },
  UNDER_REVIEW: { title: 'Mark as under review', confirm: 'Mark under review', message: 'Message to the institution', messageRequired: false },
}

function latestOutcome(verification: VerificationHistory | undefined): OutcomeRead | null {
  const outcomes = (verification?.assignments ?? []).flatMap((a) => (a.outcome ? [a.outcome] : []))
  return outcomes.sort((a, b) => b.submitted_at.localeCompare(a.submitted_at))[0] ?? null
}

/** Why AICTE cannot accept yet, phrased as the next step; null when it can. Mirrors can_accept in the backend. */
function acceptBlocker(fdr: FdrDetail, verification: VerificationHistory | undefined): string | null {
  if (!verification) return 'Checking bank verification…'
  if (verification.can_accept) return null
  if (verification.active_assignment) {
    return `Waiting for ${verification.active_assignment.bank_officer.full_name} to record the bank verification outcome.`
  }
  if (fdr.status === 'SUBMITTED') return 'Assign the record for bank verification first. Acceptance needs a bank officer’s confirmation.'
  if (fdr.status === 'CLARIFICATION_REQUESTED') return 'The record is with the institution for clarification.'
  const outcome = latestOutcome(verification)
  if (!outcome) return 'No bank officer outcome has been recorded. Assign the record for bank verification.'
  return `The latest bank outcome is “${OUTCOME_LABELS[outcome.outcome]}”. Acceptance needs a confirmation; you can reject, request clarification or assign another check.`
}

/** The evidence to look at before deciding. Flags inform the decision; none of them makes it. */
function EvidenceSummary({ fdr, verification, screening }: {
  fdr: FdrDetail
  verification: VerificationHistory | undefined
  screening: ScreeningOverview | undefined
}) {
  const outcome = latestOutcome(verification)
  const documents = fdr.documents.filter((doc) => !doc.is_withdrawn)
  const hasCopy = documents.some((doc) => doc.document_type === 'FDR_COPY')
  const run = screening?.latest
  const row = 'flex flex-wrap items-start justify-between gap-x-3 gap-y-1 py-2'
  return (
    <dl className="mt-3 divide-y divide-slate-100 text-xs">
      <div className={row}>
        <dt className="text-slate-500">Bank outcome</dt>
        <dd className="text-right">
          {verification?.active_assignment ? (
            <span className="text-sky-800">In progress with {verification.active_assignment.bank_officer.full_name}</span>
          ) : outcome ? (
            <>
              <OutcomeBadge outcome={outcome.outcome} />
              <span className="mt-0.5 block text-slate-500">{outcome.submitted_by.full_name}, {formatDateTime(outcome.submitted_at)}</span>
            </>
          ) : (
            <span className="text-slate-600">{verification ? 'None recorded' : '…'}</span>
          )}
        </dd>
      </div>
      <div className={row}>
        <dt className="text-slate-500">Possible duplicates</dt>
        <dd className={fdr.duplicate_review.flagged ? 'font-medium text-amber-800' : 'text-slate-600'}>
          {fdr.duplicate_review.flagged
            ? `Matches ${fdr.duplicate_review.match_count} record${fdr.duplicate_review.match_count === 1 ? '' : 's'}`
            : 'None found'}
        </dd>
      </div>
      <div className={row}>
        <dt className="text-slate-500">Screening</dt>
        <dd className="text-right text-slate-600">
          {!screening ? '…' : !run ? 'Not run' : run.status === 'FAILED' ? <span className="text-red-700">Last run failed</span> : (
            <span className={run.high_count > 0 ? 'font-medium text-red-700' : run.warning_count > 0 ? 'font-medium text-amber-800' : ''}>
              {run.high_count} high · {run.warning_count} warning · {run.info_count} info
            </span>
          )}
          {run?.is_stale && <span className="block text-amber-800">Record changed since this run</span>}
        </dd>
      </div>
      <div className={row}>
        <dt className="text-slate-500">Documents</dt>
        <dd className={hasCopy ? 'text-slate-600' : 'font-medium text-amber-800'}>
          {documents.length} attached{hasCopy ? '' : ' · no FDR copy'}
        </dd>
      </div>
    </dl>
  )
}

function ReviewPanel({ fdr, verification, screening, onUpdated, onReload }: {
  fdr: FdrDetail
  verification: VerificationHistory | undefined
  screening: ScreeningOverview | undefined
  onUpdated: (fdr: FdrDetail) => void
  onReload: () => void
}) {
  const options = REVIEW_TRANSITIONS[fdr.status]
  const [action, setAction] = useState<DecisionAction | null>(null)
  const [remarks, setRemarks] = useState('')
  const [internalNotes, setInternalNotes] = useState('')
  const [error, setError] = useState<{ message: string; stale: boolean } | null>(null)
  const [saving, setSaving] = useState(false)
  const blocker = acceptBlocker(fdr, verification)
  const canReject = options.includes('REJECTED')
  const otherActions = (['UNDER_REVIEW', 'CLARIFICATION_REQUESTED'] as const).filter((a) => options.includes(a))

  function choose(next: DecisionAction | null) {
    setAction(next)
    setError(null)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!action || saving) return
    const copy = ACTION_COPY[action]
    if (copy.messageRequired && remarks.trim().length === 0) return setError({ message: `${copy.message} is required.`, stale: false })
    setSaving(true)
    setError(null)
    try {
      const updated = await apiRequest<FdrDetail>(`/fdrs/${fdr.id}/review`, {
        method: 'POST',
        body: { version: fdr.version, status: action, review_remarks: remarks.trim() || null, internal_notes: internalNotes.trim() || null },
      })
      setAction(null)
      setRemarks('')
      setInternalNotes('')
      onUpdated(updated)
    } catch (err) {
      setError(err instanceof ApiError
        ? { message: err.fieldErrors.review_remarks ?? err.message, stale: err.status === 409 }
        : { message: 'Could not save the decision.', stale: false })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="p-5">
      <h3 className="text-sm font-semibold text-slate-900">AICTE decision</h3>
      <EvidenceSummary fdr={fdr} verification={verification} screening={screening} />

      {!action && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <button type="button" className={buttonStyles.primary} disabled={blocker !== null} onClick={() => choose('ACCEPTED')}>
              <CheckCircle2 className="size-4" /> Accept
            </button>
            <button type="button" className={`${buttonStyles.secondary} text-red-700`} disabled={!canReject} onClick={() => choose('REJECTED')}>
              <XCircle className="size-4" /> Reject
            </button>
          </div>
          {blocker && <p className="text-xs text-slate-600">{blocker}</p>}
          {otherActions.length > 0 && (
            <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-100 pt-3">
              {otherActions.map((a) => (
                <button key={a} type="button" className="text-xs font-medium text-navy-600 hover:text-navy-800" onClick={() => choose(a)}>
                  {ACTION_COPY[a].title}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {action && (
        <form onSubmit={handleSubmit} className="mt-4 space-y-3 border-t border-slate-100 pt-4" noValidate>
          <p className="text-sm font-medium text-slate-900">{ACTION_COPY[action].title}</p>
          {error && (
            <Alert tone="error" action={error.stale && (
              <button type="button" className={buttonStyles.secondary} onClick={() => { choose(null); onReload() }}>Reload record</button>
            )}>
              {error.message}
            </Alert>
          )}
          <Field id="review-remarks" label={ACTION_COPY[action].message} required={ACTION_COPY[action].messageRequired} hint="Visible to the institution">
            <textarea id="review-remarks" rows={3} maxLength={1000} className={inputStyles} value={remarks} onChange={(e) => setRemarks(e.target.value)} />
          </Field>
          <Field id="review-internal" label="Internal notes" hint="AICTE only">
            <textarea id="review-internal" rows={2} maxLength={2000} className={inputStyles} value={internalNotes} onChange={(e) => setInternalNotes(e.target.value)} />
          </Field>
          <div className="flex gap-2">
            <button type="submit" className={`${buttonStyles.primary} flex-1`} disabled={saving}>
              {saving && <Loader2 className="size-4 animate-spin" />} {ACTION_COPY[action].confirm}
            </button>
            <button type="button" className={buttonStyles.secondary} disabled={saving} onClick={() => choose(null)}>Cancel</button>
          </div>
        </form>
      )}
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
  const [decided, setDecided] = useState<FdrStatus | null>(null)
  const [activityKey, setActivityKey] = useState(0)
  const isAicte = user.role === 'AICTE_OFFICIAL'
  const verification = useApiQuery<VerificationHistory>(isAicte ? `/fdrs/${Number(fdrId)}/verification?a=${activityKey}` : null)
  const screening = useApiQuery<ScreeningOverview>(isAicte ? `/fdrs/${Number(fdrId)}/screening?a=${activityKey}` : null)
  const refreshAll = () => {
    result.reload()
    setActivityKey((key) => key + 1)
  }
  const navState = location.state as { justSaved?: string; backTo?: string; backLabel?: string } | null
  const justSaved = navState?.justSaved
  const back = (
    <Link to={navState?.backTo ?? '/fdr-records'} className="inline-flex items-center gap-1 text-sm font-medium text-navy-600 hover:text-navy-800">
      <ArrowLeft className="size-4" /> {navState?.backLabel ?? 'FDR Records'}
    </Link>
  )

  if (result.status === 'loading' && !result.data) return <Spinner label="Loading record…" />
  if (result.status === 'error') {
    return (
      <div className="space-y-4">
        {back}
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
      {back}

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
      {decided && decided === fdr.status && (
        <Alert tone="info" title="Decision saved">Status is now “{STATUS_LABELS[fdr.status]}”. It is recorded in the record history and audit log.</Alert>
      )}

      {fdr.status === 'ACCEPTED' ? (
        <Alert tone="info" title="Accepted by AICTE">
          Accepted after a bank officer recorded a confirmation. That outcome is the officer’s attestation, not a direct check of bank systems.
        </Alert>
      ) : fdr.status !== 'REJECTED' && (
        <Alert tone="warning" title={VERIFICATION_STATE_LABELS[fdr.verification_state]}>
          Details as entered by the institution. They are not confirmed until a bank officer checks them and AICTE decides.
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
              verification={verification.data}
              screening={screening.data}
              onReload={refreshAll}
              onUpdated={(updated) => {
                setOverride(updated)
                setDecided(updated.status)
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
