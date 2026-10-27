import { useNavigate, useParams } from 'react-router'
import FdrForm, { toPayload } from '../../components/fdrs/FdrForm'
import { Alert, PageHeader, Spinner, buttonStyles } from '../../components/ui'
import { useApiQuery } from '../../hooks/useApiQuery'
import { apiRequest } from '../../lib/api'
import type { FdrDetail, FdrFormValues } from '../../types'

function toFormValues(fdr: FdrDetail): FdrFormValues {
  return {
    bank_name: fdr.bank_name,
    branch_name: fdr.branch_name ?? '',
    ifsc_code: fdr.ifsc_code ?? '',
    fdr_number: fdr.fdr_number,
    amount: fdr.amount,
    issue_date: fdr.issue_date,
    maturity_date: fdr.maturity_date,
    remarks: fdr.remarks ?? '',
  }
}

export default function FdrEditPage() {
  const { fdrId } = useParams()
  const navigate = useNavigate()
  const result = useApiQuery<FdrDetail>(`/fdrs/${Number(fdrId)}`)

  if (result.status === 'loading') return <Spinner />
  if (result.status === 'error') {
    return (
      <Alert tone="error" title="Could not load this record" action={
        <button type="button" className={buttonStyles.secondary} onClick={result.reload}>Try again</button>
      }>
        {result.error.message}
      </Alert>
    )
  }

  const fdr = result.data
  if (!fdr.can_edit) {
    return <Alert tone="warning" title="This record cannot be edited">Records can only be corrected while they are Submitted or when AICTE has requested clarification.</Alert>
  }

  async function handleSubmit(values: FdrFormValues) {
    const original = toPayload(toFormValues(fdr))
    const updated = toPayload(values)
    // Send only the fields that changed, plus the version we edited.
    const changes = Object.fromEntries(
      Object.entries(updated).filter(([key, value]) => original[key as keyof typeof original] !== value),
    )
    if (Object.keys(changes).length === 0) {
      navigate(`/fdr-records/${fdr.id}`)
      return
    }
    await apiRequest<FdrDetail>(`/fdrs/${fdr.id}`, { method: 'PATCH', body: { version: fdr.version, ...changes } })
    navigate(`/fdr-records/${fdr.id}`, { state: { justSaved: 'updated' } })
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader title={`Edit FDR ${fdr.fdr_number}`} description="Changes are recorded in the audit trail." />
      {fdr.status === 'CLARIFICATION_REQUESTED' && fdr.review_remarks && (
        <Alert tone="warning" title="AICTE requested clarification">
          {fdr.review_remarks}
          <p className="mt-1 text-xs">Saving your corrections returns the record to Submitted.</p>
        </Alert>
      )}
      <FdrForm
        initialValues={toFormValues(fdr)}
        submitLabel="Save changes"
        cancelTo={`/fdr-records/${fdr.id}`}
        onSubmit={handleSubmit}
      />
    </div>
  )
}
