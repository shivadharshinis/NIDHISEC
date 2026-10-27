import { ChevronLeft, ChevronRight, Filter, X } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Alert, Card, Field, PageHeader, Spinner, buttonStyles, inputStyles } from '../components/ui'
import { useApiQuery } from '../hooks/useApiQuery'
import { toQuery } from '../lib/api'
import { AUDIT_ACTION_LABELS, formatDateTime, ROLE_LABELS } from '../lib/format'
import type { AuditLogEntry, Page } from '../types'

const PAGE_SIZE = 50

// Entity types written by the backend's audit calls.
const ENTITY_TYPES: Record<string, string> = {
  fdr: 'FDR record',
  user: 'User / sign-in',
  verification_assignment: 'Verification case',
  lifecycle: 'Lifecycle (access attempts)',
  lifecycle_check: 'Maturity check',
  screening: 'Screening (access attempts)',
}

const FILTER_KEYS = ['action', 'entity_type', 'entity_id', 'actor_email', 'date_from', 'date_to'] as const
type Filters = Record<(typeof FILTER_KEYS)[number], string>

function validate(f: Filters): Partial<Filters> {
  const errors: Partial<Filters> = {}
  if (f.entity_id && !/^[1-9]\d{0,9}$/.test(f.entity_id)) errors.entity_id = 'Enter a positive whole number.'
  if (f.entity_id && !f.entity_type) errors.entity_type = 'Choose the record type for this ID.'
  if (f.actor_email && (f.actor_email.length > 254 || !/^\S+@\S+$/.test(f.actor_email))) errors.actor_email = 'Enter a full email address.'
  if (f.date_from && f.date_to && f.date_from > f.date_to) errors.date_to = '“To” must be on or after “From”.'
  return errors
}

export default function AuditLogPage() {
  const [params, setParams] = useSearchParams()
  const applied = Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ''])) as Filters
  const page = Math.max(1, Number(params.get('page')) || 1)
  const [draft, setDraft] = useState<Filters>(applied)
  const [errors, setErrors] = useState<Partial<Filters>>({})
  // Never send a query the form considers invalid (e.g. from an edited URL).
  const appliedValid = Object.keys(validate(applied)).length === 0
  const result = useApiQuery<Page<AuditLogEntry>>(appliedValid ? `/audit-logs${toQuery({ ...applied, page, page_size: PAGE_SIZE })}` : null)
  const data = result.data
  const activeCount = FILTER_KEYS.filter((k) => applied[k]).length

  function apply(event: FormEvent) {
    event.preventDefault()
    const cleaned = Object.fromEntries(FILTER_KEYS.map((k) => [k, draft[k].trim()])) as Filters
    const found = validate(cleaned)
    setErrors(found)
    if (Object.keys(found).length) return
    setParams(Object.fromEntries(Object.entries(cleaned).filter(([, v]) => v)), { replace: true })
  }

  function reset() {
    const empty = Object.fromEntries(FILTER_KEYS.map((k) => [k, ''])) as Filters
    setDraft(empty)
    setErrors({})
    setParams({}, { replace: true })
  }

  const goTo = (p: number) => setParams({ ...Object.fromEntries(Object.entries(applied).filter(([, v]) => v)), page: String(p) }, { replace: true })
  const set = (key: keyof Filters) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [key]: e.target.value }))

  return (
    <div className="space-y-5">
      <PageHeader title="Audit Logs" description="Append-only record of sign-ins, record changes and review actions, newest first. Entries cannot be edited or deleted." />

      <Card className="p-4">
        <form onSubmit={apply} noValidate className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field id="f-action" label="Action">
            <select id="f-action" className={inputStyles} value={draft.action} onChange={set('action')}>
              <option value="">All actions</option>
              {Object.entries(AUDIT_ACTION_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </Field>
          <Field id="f-entity-type" label="Record type" error={errors.entity_type}>
            <select id="f-entity-type" className={inputStyles} value={draft.entity_type} onChange={set('entity_type')} aria-invalid={Boolean(errors.entity_type)}>
              <option value="">Any</option>
              {Object.entries(ENTITY_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </Field>
          <Field id="f-entity-id" label="Record ID" error={errors.entity_id} hint="e.g. an FDR’s number in its page address">
            <input id="f-entity-id" inputMode="numeric" className={inputStyles} value={draft.entity_id} onChange={set('entity_id')} aria-invalid={Boolean(errors.entity_id)} />
          </Field>
          <Field id="f-actor" label="Actor email" error={errors.actor_email} hint="Exact address (not case-sensitive)">
            <input id="f-actor" type="email" className={inputStyles} value={draft.actor_email} onChange={set('actor_email')} aria-invalid={Boolean(errors.actor_email)} />
          </Field>
          <Field id="f-from" label="From (IST)">
            <input id="f-from" type="date" className={inputStyles} value={draft.date_from} onChange={set('date_from')} />
          </Field>
          <Field id="f-to" label="To (IST, inclusive)" error={errors.date_to}>
            <input id="f-to" type="date" className={inputStyles} value={draft.date_to} onChange={set('date_to')} aria-invalid={Boolean(errors.date_to)} />
          </Field>
          <div className="flex flex-wrap gap-2 sm:col-span-2 lg:col-span-3">
            <button type="submit" className={buttonStyles.primary}><Filter className="size-4" /> Apply filters</button>
            {activeCount > 0 && <button type="button" className={buttonStyles.secondary} onClick={reset}><X className="size-4" /> Clear ({activeCount})</button>}
          </div>
        </form>
      </Card>

      {!appliedValid && <Alert tone="error" title="Invalid filters">Correct the filters above and apply them again.</Alert>}
      {result.status === 'error' && (
        <Alert tone="error" title="Could not load audit logs"
          action={<button type="button" className={buttonStyles.secondary} onClick={result.reload}>Try again</button>}>
          {result.error.message}
        </Alert>
      )}
      {appliedValid && result.status === 'loading' && !data && <Spinner label="Loading audit logs…" />}
      {data && data.total === 0 && (
        <Card className="p-10 text-center text-sm text-slate-600">
          No audit entries match{activeCount > 0 ? ' these filters' : ''}.
        </Card>
      )}

      {data && data.total > 0 && (
        <Card className={result.status === 'loading' ? 'opacity-60' : ''}>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold tracking-wide text-slate-600 uppercase">
                <tr>
                  <th scope="col" className="px-4 py-3">When</th>
                  <th scope="col" className="px-4 py-3">Actor</th>
                  <th scope="col" className="px-4 py-3">Action</th>
                  <th scope="col" className="px-4 py-3">Record</th>
                  <th scope="col" className="px-4 py-3">Details</th>
                  <th scope="col" className="px-4 py-3">IP</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((entry) => (
                  <tr key={entry.id} className="align-top">
                    <td className="px-4 py-3 whitespace-nowrap text-slate-700">{formatDateTime(entry.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="text-slate-900">{entry.actor_name ?? entry.actor_email ?? '—'}</div>
                      <div className="text-xs text-slate-500">
                        {entry.actor_role ? ROLE_LABELS[entry.actor_role] : 'Unauthenticated'}
                        {entry.actor_name && entry.actor_email && ` · ${entry.actor_email}`}
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-slate-900">{AUDIT_ACTION_LABELS[entry.action] ?? entry.action}</td>
                    <td className="px-4 py-3 text-xs whitespace-nowrap text-slate-600">
                      {ENTITY_TYPES[entry.entity_type] ?? entry.entity_type}{entry.entity_id ? ` #${entry.entity_id}` : ''}
                    </td>
                    <td className="px-4 py-3 text-slate-700">
                      {entry.summary}
                      {entry.entity_type === 'fdr' && entry.entity_id && (
                        <Link to={`/fdr-records/${entry.entity_id}`} className="ml-1 text-xs font-medium text-navy-600 hover:underline">
                          View record
                        </Link>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs whitespace-nowrap text-slate-500">{entry.ip_address ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3 text-sm text-slate-600">
            <span>Page {data.page} of {data.pages} · {data.total} entries</span>
            <div className="flex gap-2">
              <button type="button" className={buttonStyles.secondary} disabled={page <= 1} onClick={() => goTo(page - 1)}>
                <ChevronLeft className="size-4" /> Previous
              </button>
              <button type="button" className={buttonStyles.secondary} disabled={page >= data.pages} onClick={() => goTo(page + 1)}>
                Next <ChevronRight className="size-4" />
              </button>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
