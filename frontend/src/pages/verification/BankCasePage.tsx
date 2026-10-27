import { ArrowLeft, Download, Loader2, Send } from 'lucide-react'
import { type FormEvent, type ReactNode, useState } from 'react'
import { Link, useParams } from 'react-router'
import { Alert, Card, Field, Spinner, buttonStyles, inputStyles } from '../../components/ui'
import { AssignmentStatusBadge, OUTCOME_DISCLAIMER, OutcomeDetails } from '../../components/verification/VerificationPanel'
import { useApiQuery } from '../../hooks/useApiQuery'
import { ApiError, apiDownload, apiRequest } from '../../lib/api'
import {
  DOCUMENT_TYPE_LABELS,
  formatBytes,
  formatDate,
  formatDateTime,
  formatINR,
  OUTCOME_DESCRIPTIONS,
  OUTCOME_LABELS,
} from '../../lib/format'
import type { BankCase, DocumentRead, OutcomeType } from '../../types'

const OUTCOME_TYPES = Object.keys(OUTCOME_LABELS) as OutcomeType[]
const MIN_NOTES = 20

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-900">{children}</dd>
    </div>
  )
}

function CaseDocuments({ fdrId, documents }: { fdrId: number; documents: DocumentRead[] }) {
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function download(doc: DocumentRead) {
    setBusy(doc.id)
    setError(null)
    try {
      await apiDownload(`/fdrs/${fdrId}/documents/${doc.id}/download`, doc.original_filename)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Download failed.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card className="p-5 sm:p-6">
      <h3 className="text-sm font-semibold text-slate-900">Supporting documents</h3>
      <p className="mt-1 text-xs text-slate-600">Downloads are permission-checked, integrity-checked and logged.</p>
      {error && <div className="mt-3"><Alert tone="error">{error}</Alert></div>}
      {documents.length === 0 ? (
        <p className="mt-3 text-sm text-slate-600">The institution has not attached any documents.</p>
      ) : (
        <ul className="mt-2 divide-y divide-slate-100">
          {documents.map((doc) => (
            <li key={doc.id} className={`flex flex-wrap items-center gap-3 py-3 ${doc.is_withdrawn ? 'opacity-70' : ''}`}>
              <div className="min-w-0 flex-1">
                <p className={`text-sm font-medium break-all text-slate-900 ${doc.is_withdrawn ? 'line-through' : ''}`}>{doc.original_filename}</p>
                <p className="text-xs text-slate-600">
                  {DOCUMENT_TYPE_LABELS[doc.document_type]} · {formatBytes(doc.size_bytes)} · uploaded {formatDateTime(doc.uploaded_at)}
                  {doc.is_withdrawn && ' · withdrawn by the institution'}
                </p>
                <p className="font-mono text-[11px] break-all text-slate-500">SHA-256 {doc.sha256}</p>
              </div>
              <button type="button" className={buttonStyles.secondary} disabled={busy !== null} onClick={() => download(doc)}>
                {busy === doc.id ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />} Download
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function OutcomeForm({ bankCase, onSubmitted }: { bankCase: BankCase; onSubmitted: (updated: BankCase) => void }) {
  const [outcome, setOutcome] = useState<OutcomeType | ''>('')
  const [notes, setNotes] = useState('')
  const [reference, setReference] = useState('')
  const [evidence, setEvidence] = useState<number[]>([])
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const usableDocs = bankCase.documents.filter((doc) => !doc.is_withdrawn)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const errors: Record<string, string> = {}
    if (!outcome) errors.outcome = 'Choose an outcome.'
    if (notes.trim().length < MIN_NOTES) errors.notes = `Explain the outcome in at least ${MIN_NOTES} characters.`
    if (reference && !/^[A-Za-z0-9 /.-]*$/.test(reference)) errors.bank_reference = 'Use letters, numbers, spaces and / . - only.'
    setFieldErrors(errors)
    if (Object.keys(errors).length) return setError('Please correct the highlighted fields.')
    setSaving(true)
    setError(null)
    try {
      const updated = await apiRequest<BankCase>(`/verification/cases/${bankCase.id}/outcome`, {
        method: 'POST',
        body: {
          version: bankCase.version,
          outcome,
          notes: notes.trim(),
          bank_reference: reference.trim() || null,
          evidence_document_ids: evidence,
        },
      })
      onSubmitted(updated)
    } catch (err) {
      if (err instanceof ApiError) {
        setFieldErrors(err.fieldErrors)
        setError(err.message)
      } else {
        setError('Could not record the outcome.')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="p-5 sm:p-6">
      <h3 className="text-sm font-semibold text-slate-900">Record your outcome</h3>
      <p className="mt-1 text-xs text-slate-600">
        Check the details above against your bank’s own records. You can submit one outcome; it closes the case and cannot be changed.
      </p>
      <form onSubmit={handleSubmit} noValidate className="mt-4 space-y-4">
        {error && <Alert tone="error">{error}</Alert>}
        <fieldset>
          <legend className="text-sm font-medium text-slate-700">Outcome <span className="text-red-600">*</span></legend>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {OUTCOME_TYPES.map((type) => (
              <label
                key={type}
                className={`flex cursor-pointer gap-3 rounded-md border p-3 text-sm ${outcome === type ? 'border-navy-500 bg-navy-50' : 'border-slate-200 hover:bg-slate-50'}`}
              >
                <input type="radio" name="outcome" value={type} checked={outcome === type} onChange={() => setOutcome(type)} className="mt-0.5" />
                <span>
                  <span className="block font-medium text-slate-900">{OUTCOME_LABELS[type]}</span>
                  <span className="block text-xs text-slate-600">{OUTCOME_DESCRIPTIONS[type]}</span>
                </span>
              </label>
            ))}
          </div>
          {fieldErrors.outcome && <p className="mt-1 text-xs text-red-700">{fieldErrors.outcome}</p>}
        </fieldset>
        <Field id="outcome-notes" label="Reason and notes" required error={fieldErrors.notes} hint={`At least ${MIN_NOTES} characters. Visible to AICTE, not to the institution.`}>
          <textarea id="outcome-notes" rows={4} maxLength={2000} className={inputStyles} value={notes}
            aria-invalid={Boolean(fieldErrors.notes)} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <Field id="outcome-reference" label="Bank record reference" error={fieldErrors.bank_reference} hint="Optional, e.g. a ledger or letter number">
          <input id="outcome-reference" className={inputStyles} maxLength={100} value={reference}
            aria-invalid={Boolean(fieldErrors.bank_reference)} onChange={(e) => setReference(e.target.value)} />
        </Field>
        {usableDocs.length > 0 && (
          <fieldset>
            <legend className="text-sm font-medium text-slate-700">Documents you relied on</legend>
            <div className="mt-2 space-y-1">
              {usableDocs.map((doc) => (
                <label key={doc.id} className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={evidence.includes(doc.id)}
                    onChange={(e) => setEvidence((ids) => (e.target.checked ? [...ids, doc.id] : ids.filter((id) => id !== doc.id)))}
                  />
                  <span className="break-all">{doc.original_filename}</span>
                </label>
              ))}
            </div>
            {fieldErrors.evidence_document_ids && <p className="mt-1 text-xs text-red-700">{fieldErrors.evidence_document_ids}</p>}
          </fieldset>
        )}
        <Alert tone="warning">{OUTCOME_DISCLAIMER}</Alert>
        <button type="submit" className={buttonStyles.primary} disabled={saving}>
          {saving ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />} Submit outcome
        </button>
      </form>
    </Card>
  )
}

export default function BankCasePage() {
  const { assignmentId } = useParams()
  const result = useApiQuery<BankCase>(`/verification/cases/${Number(assignmentId)}`)
  const [submitted, setSubmitted] = useState<BankCase | null>(null)

  const back = (
    <Link to="/verification" className="inline-flex items-center gap-1 text-sm font-medium text-navy-600 hover:text-navy-800">
      <ArrowLeft className="size-4" /> My verification cases
    </Link>
  )
  if (result.status === 'loading' && !result.data) return <Spinner label="Loading case…" />
  if (result.status === 'error') {
    return (
      <div className="space-y-4">
        {back}
        <Alert tone="error" title={result.error.status === 404 ? 'Case not found' : 'Could not load this case'}>
          {result.error.status === 404 ? 'It does not exist or is not assigned to you.' : result.error.message}
        </Alert>
      </div>
    )
  }
  const bankCase = submitted ?? result.data
  if (!bankCase) return null

  return (
    <div className="space-y-5">
      {back}
      <div>
        <p className="text-xs font-medium text-slate-500">Verification case #{bankCase.id}</p>
        <h2 className="text-2xl font-semibold break-all text-slate-900">{bankCase.fdr_number}</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-600">
          <AssignmentStatusBadge status={bankCase.status} />
          <span>Assigned {formatDateTime(bankCase.assigned_at)}</span>
        </div>
      </div>

      {submitted && <Alert tone="info" title="Outcome recorded">AICTE will review it. The case is now closed to you.</Alert>}
      {bankCase.assignment_note && <Alert tone="info" title="Instructions from AICTE">{bankCase.assignment_note}</Alert>}
      {!bankCase.fdr && !bankCase.outcome && (
        <Alert tone="warning" title="This case is no longer assigned to you">
          It was reassigned or closed by AICTE, so its details and documents are no longer available to you.
        </Alert>
      )}

      {bankCase.fdr && (
        <>
          <Card className="p-5 sm:p-6">
            <h3 className="text-sm font-semibold text-slate-900">FDR details submitted by the institution</h3>
            <dl className="mt-4 grid gap-4 sm:grid-cols-2">
              <Detail label="Institution">{bankCase.fdr.institution.name} ({bankCase.fdr.institution.code})</Detail>
              <Detail label="Deposit amount"><span className="tabular-nums">{formatINR(bankCase.fdr.amount)}</span></Detail>
              <Detail label="Issuing bank">{bankCase.fdr.bank_name}</Detail>
              <Detail label="Branch">{bankCase.fdr.branch_name ?? '—'}</Detail>
              <Detail label="Branch IFSC">{bankCase.fdr.ifsc_code ?? '—'}</Detail>
              <Detail label="FDR / reference number">{bankCase.fdr.fdr_number}</Detail>
              <Detail label="Issue date">{formatDate(bankCase.fdr.issue_date)}</Detail>
              <Detail label="Maturity date">{formatDate(bankCase.fdr.maturity_date)}</Detail>
            </dl>
          </Card>
          <CaseDocuments fdrId={bankCase.fdr.id} documents={bankCase.documents} />
        </>
      )}

      {bankCase.can_submit_outcome && <OutcomeForm bankCase={bankCase} onSubmitted={setSubmitted} />}

      {bankCase.outcome && (
        <Card className="p-5 sm:p-6">
          <h3 className="text-sm font-semibold text-slate-900">Your recorded outcome</h3>
          <OutcomeDetails outcome={bankCase.outcome} />
        </Card>
      )}
    </div>
  )
}
