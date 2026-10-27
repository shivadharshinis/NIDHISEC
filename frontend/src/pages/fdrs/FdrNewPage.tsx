import { useNavigate } from 'react-router'
import FdrForm, { EMPTY_FDR_FORM, toPayload } from '../../components/fdrs/FdrForm'
import { PageHeader } from '../../components/ui'
import { useCurrentUser } from '../../auth/AuthContext'
import { apiRequest } from '../../lib/api'
import type { FdrDetail, FdrFormValues } from '../../types'

export default function FdrNewPage() {
  const user = useCurrentUser()
  const navigate = useNavigate()

  async function handleSubmit(values: FdrFormValues) {
    const created = await apiRequest<FdrDetail>('/fdrs', { method: 'POST', body: toPayload(values) })
    navigate(`/fdr-records/${created.id}`, { state: { justSaved: 'created' } })
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader
        title="Submit an FDR"
        description={`The record will be filed under ${user.institution?.name ?? 'your institution'} (${user.institution?.code ?? ''}).`}
      />
      <FdrForm initialValues={EMPTY_FDR_FORM} submitLabel="Submit FDR" cancelTo="/fdr-records" onSubmit={handleSubmit} />
    </div>
  )
}
