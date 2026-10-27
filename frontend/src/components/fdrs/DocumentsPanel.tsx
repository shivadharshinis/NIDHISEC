import { Download, FileText, FileX2, Image, Loader2, ShieldCheck, ShieldAlert, Upload, Undo2 } from 'lucide-react'
import { type FormEvent, useRef, useState } from 'react'
import { useApiQuery } from '../../hooks/useApiQuery'
import { ApiError, apiDownload, apiRequest, apiUpload } from '../../lib/api'
import { DOCUMENT_TYPE_LABELS, formatBytes, formatDateTime } from '../../lib/format'
import type { DocumentList, DocumentRead, DocumentType, IntegrityReport } from '../../types'
import { Alert, Card, Field, Spinner, buttonStyles, inputStyles } from '../ui'

const DOCUMENT_TYPES = Object.keys(DOCUMENT_TYPE_LABELS) as DocumentType[]

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.fieldErrors.file ?? error.message
  return fallback
}

function UploadForm({ fdrId, policy, onUploaded }: { fdrId: number; policy: DocumentList; onUploaded: (doc: DocumentRead) => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [documentType, setDocumentType] = useState<DocumentType>('FDR_COPY')
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const maxMb = Math.floor(policy.max_upload_bytes / (1024 * 1024))
  const accept = [...policy.allowed_extensions, 'application/pdf', 'image/png', 'image/jpeg'].join(',')

  function validate(candidate: File): string | null {
    const extension = candidate.name.includes('.') ? `.${candidate.name.split('.').pop()!.toLowerCase()}` : ''
    if (!policy.allowed_extensions.includes(extension)) return 'Only PDF, PNG and JPEG files are accepted.'
    if (candidate.size === 0) return 'The file is empty.'
    if (candidate.size > policy.max_upload_bytes) return `The file exceeds the ${maxMb} MB limit.`
    return null
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!file) return setError('Choose a file to upload.')
    const problem = validate(file)
    if (problem) return setError(problem)
    setError(null)
    setProgress(0)
    const form = new FormData()
    form.append('file', file)
    form.append('document_type', documentType)
    try {
      const uploaded = await apiUpload<DocumentRead>(`/fdrs/${fdrId}/documents`, form, { onProgress: setProgress })
      setFile(null)
      if (inputRef.current) inputRef.current.value = ''
      onUploaded(uploaded)
    } catch (err) {
      setError(errorMessage(err, 'Upload failed. Please try again.'))
    } finally {
      setProgress(null)
    }
  }

  const uploading = progress !== null
  return (
    <form onSubmit={handleSubmit} noValidate className="mt-4 rounded-md border border-dashed border-slate-300 bg-slate-50 p-4">
      <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
        <Field id="document-file" label="Add a document" hint={`PDF, PNG or JPEG, up to ${maxMb} MB`}>
          <input
            ref={inputRef}
            id="document-file"
            type="file"
            accept={accept}
            disabled={uploading}
            onChange={(e) => {
              const chosen = e.target.files?.[0] ?? null
              setFile(chosen)
              setError(chosen ? validate(chosen) : null)
            }}
            className="block w-full text-sm text-slate-700 file:mr-3 file:rounded-md file:border-0 file:bg-navy-700 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-navy-800"
          />
        </Field>
        <Field id="document-type" label="Type">
          <select
            id="document-type"
            className={inputStyles}
            value={documentType}
            disabled={uploading}
            onChange={(e) => setDocumentType(e.target.value as DocumentType)}
          >
            {DOCUMENT_TYPES.map((type) => (
              <option key={type} value={type}>{DOCUMENT_TYPE_LABELS[type]}</option>
            ))}
          </select>
        </Field>
      </div>

      {error && <p className="mt-3 text-sm text-red-700" role="alert">{error}</p>}

      {uploading ? (
        <div className="mt-3" role="status" aria-live="polite">
          <div className="h-2 overflow-hidden rounded-full bg-slate-200">
            <div className="h-full bg-navy-600 transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} />
          </div>
          <p className="mt-1 text-xs text-slate-600">
            {progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : 'Checking file…'}
          </p>
        </div>
      ) : (
        <button type="submit" className={`${buttonStyles.primary} mt-3`} disabled={!file}>
          <Upload className="size-4" /> Upload
        </button>
      )}
    </form>
  )
}

function DocumentRow({
  fdrId,
  doc,
  canWithdraw,
  canCheckIntegrity,
  onChanged,
}: {
  fdrId: number
  doc: DocumentRead
  canWithdraw: boolean
  canCheckIntegrity: boolean
  onChanged: () => void
}) {
  const [busy, setBusy] = useState<'download' | 'integrity' | 'withdraw' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [integrity, setIntegrity] = useState<IntegrityReport | null>(null)
  const [withdrawing, setWithdrawing] = useState(false)
  const [reason, setReason] = useState('')
  const base = `/fdrs/${fdrId}/documents/${doc.id}`
  const Icon = doc.content_type === 'application/pdf' ? FileText : Image

  async function run(kind: 'download' | 'integrity' | 'withdraw', action: () => Promise<void>, fallback: string) {
    setBusy(kind)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(errorMessage(err, fallback))
      if (kind === 'download') onChanged() // a blocked download is audited; refresh history
    } finally {
      setBusy(null)
    }
  }

  return (
    <li className={`py-4 ${doc.is_withdrawn ? 'opacity-75' : ''}`}>
      <div className="flex flex-wrap items-start gap-3">
        <Icon className="mt-0.5 size-5 shrink-0 text-navy-500" />
        <div className="min-w-0 flex-1">
          <p className={`text-sm font-medium break-all text-slate-900 ${doc.is_withdrawn ? 'line-through' : ''}`}>
            {doc.original_filename}
          </p>
          <p className="mt-0.5 text-xs text-slate-600">
            {DOCUMENT_TYPE_LABELS[doc.document_type]} · {doc.content_type === 'application/pdf' ? 'PDF' : doc.content_type.replace('image/', '').toUpperCase()} ·{' '}
            {formatBytes(doc.size_bytes)} · uploaded {formatDateTime(doc.uploaded_at)} by {doc.uploaded_by_name}
          </p>
          <p className="mt-0.5 font-mono text-[11px] break-all text-slate-500" title="SHA-256 recorded at upload">
            SHA-256 {doc.sha256}
          </p>
          {doc.is_withdrawn && (
            <p className="mt-1 text-xs text-amber-800">
              Withdrawn {doc.withdrawn_at && formatDateTime(doc.withdrawn_at)} by {doc.withdrawn_by_name}: “{doc.withdrawal_reason}”. Kept on
              record.
            </p>
          )}
          {integrity && (
            <p
              className={`mt-1 inline-flex items-center gap-1 text-xs font-medium ${integrity.status === 'intact' ? 'text-emerald-700' : 'text-red-700'}`}
              role="status"
            >
              {integrity.status === 'intact' ? <ShieldCheck className="size-3.5" /> : <ShieldAlert className="size-3.5" />}
              {integrity.status === 'intact'
                ? 'Stored file unchanged since upload (hash matches)'
                : integrity.status === 'missing'
                  ? 'Stored file is missing'
                  : 'Stored file does not match the recorded hash'}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className={buttonStyles.secondary}
            disabled={busy !== null}
            onClick={() => run('download', async () => { await apiDownload(`${base}/download`, doc.original_filename); onChanged() }, 'Download failed.')}
          >
            {busy === 'download' ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />} Download
          </button>
          {canCheckIntegrity && (
            <button
              type="button"
              className={buttonStyles.secondary}
              disabled={busy !== null}
              onClick={() =>
                run('integrity', async () => {
                  setIntegrity(await apiRequest<IntegrityReport>(`${base}/integrity-check`, { method: 'POST' }))
                  onChanged()
                }, 'Integrity check failed.')
              }
            >
              {busy === 'integrity' ? <Loader2 className="size-4 animate-spin" /> : <ShieldCheck className="size-4" />} Check integrity
            </button>
          )}
          {canWithdraw && !doc.is_withdrawn && !withdrawing && (
            <button type="button" className={buttonStyles.secondary} disabled={busy !== null} onClick={() => setWithdrawing(true)}>
              <Undo2 className="size-4" /> Withdraw
            </button>
          )}
        </div>
      </div>

      {withdrawing && (
        <form
          className="mt-3 ml-8 space-y-2"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            if (reason.trim().length < 5) return setError('Give a reason of at least 5 characters.')
            run('withdraw', async () => {
              await apiRequest<DocumentRead>(`${base}/withdraw`, { method: 'POST', body: { reason: reason.trim() } })
              setWithdrawing(false)
              setReason('')
              onChanged()
            }, 'Could not withdraw the document.')
          }}
        >
          <Field id={`withdraw-${doc.id}`} label="Reason for withdrawal" required hint="The document stays on record; withdrawal is logged and cannot be undone.">
            <input id={`withdraw-${doc.id}`} className={inputStyles} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <div className="flex gap-2">
            <button type="submit" className={buttonStyles.primary} disabled={busy !== null}>
              {busy === 'withdraw' && <Loader2 className="size-4 animate-spin" />} Confirm withdrawal
            </button>
            <button type="button" className={buttonStyles.secondary} onClick={() => { setWithdrawing(false); setError(null) }}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {error && <p className="mt-2 ml-8 text-sm text-red-700" role="alert">{error}</p>}
    </li>
  )
}

export default function DocumentsPanel({ fdrId, onChanged }: { fdrId: number; onChanged: () => void }) {
  const result = useApiQuery<DocumentList>(`/fdrs/${fdrId}/documents`)
  const [justUploaded, setJustUploaded] = useState<DocumentRead | null>(null)
  const data = result.data

  function refresh() {
    result.reload()
    onChanged()
  }

  return (
    <Card className="p-5 sm:p-6">
      <h3 className="text-sm font-semibold text-slate-900">Supporting documents</h3>
      <p className="mt-1 text-xs text-slate-600">
        Each file’s SHA-256 hash is recorded at upload so later changes to the stored file can be detected. This does
        not confirm that a document is genuine.
      </p>

      {result.status === 'loading' && !data && <Spinner label="Loading documents…" />}
      {result.status === 'error' && (
        <div className="mt-4">
          <Alert tone="error" title="Could not load documents" action={
            <button type="button" className={buttonStyles.secondary} onClick={result.reload}>Try again</button>
          }>
            {result.error.message}
          </Alert>
        </div>
      )}

      {data && (
        <>
          {justUploaded && (
            <div className="mt-4">
              <Alert tone="info" title="Document uploaded">
                {justUploaded.original_filename} was stored and its hash recorded. It has not been reviewed or verified.
              </Alert>
            </div>
          )}

          {data.items.length === 0 ? (
            <div className="mt-4 flex gap-3 text-sm text-slate-600">
              <FileX2 className="size-5 shrink-0 text-slate-400" />
              <p>
                No documents attached yet.
                {data.can_upload ? ' Upload a copy of the FDR and any bank correspondence below.' : ''}
              </p>
            </div>
          ) : (
            <ul className="mt-2 divide-y divide-slate-100">
              {data.items.map((doc) => (
                <DocumentRow
                  key={doc.id}
                  fdrId={fdrId}
                  doc={doc}
                  canWithdraw={data.can_withdraw}
                  canCheckIntegrity={data.can_check_integrity}
                  onChanged={refresh}
                />
              ))}
            </ul>
          )}

          {data.can_upload && (
            <UploadForm
              fdrId={fdrId}
              policy={data}
              onUploaded={(doc) => {
                setJustUploaded(doc)
                refresh()
              }}
            />
          )}
        </>
      )}
    </Card>
  )
}
