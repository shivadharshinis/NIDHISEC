import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { Alert, Card, PageHeader, Spinner, buttonStyles, inputStyles } from '../components/ui'
import { useApiQuery } from '../hooks/useApiQuery'
import { toQuery } from '../lib/api'
import { AUDIT_ACTION_LABELS, formatDateTime, ROLE_LABELS } from '../lib/format'
import type { AuditLogEntry, Page } from '../types'

const PAGE_SIZE = 50

export default function AuditLogPage() {
  const [action, setAction] = useState('')
  const [page, setPage] = useState(1)
  const result = useApiQuery<Page<AuditLogEntry>>(`/audit-logs${toQuery({ action, page, page_size: PAGE_SIZE })}`)
  const data = result.data

  return (
    <div className="space-y-5">
      <PageHeader
        title="Audit Logs"
        description="Append-only record of sign-ins and FDR changes. Entries cannot be edited or deleted."
        actions={
          <select
            aria-label="Filter by action"
            className={inputStyles}
            value={action}
            onChange={(e) => {
              setAction(e.target.value)
              setPage(1)
            }}
          >
            <option value="">All actions</option>
            {Object.entries(AUDIT_ACTION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        }
      />

      {result.status === 'error' && (
        <Alert tone="error" title="Could not load audit logs"
          action={<button type="button" className={buttonStyles.secondary} onClick={result.reload}>Try again</button>}>
          {result.error.message}
        </Alert>
      )}
      {result.status === 'loading' && !data && <Spinner label="Loading audit logs…" />}
      {data && data.total === 0 && <Card className="p-10 text-center text-sm text-slate-600">No audit entries match.</Card>}

      {data && data.total > 0 && (
        <Card className={result.status === 'loading' ? 'opacity-60' : ''}>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold tracking-wide text-slate-600 uppercase">
                <tr>
                  <th scope="col" className="px-4 py-3">When</th>
                  <th scope="col" className="px-4 py-3">Actor</th>
                  <th scope="col" className="px-4 py-3">Action</th>
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
              <button type="button" className={buttonStyles.secondary} disabled={page <= 1} onClick={() => setPage(page - 1)}>
                <ChevronLeft className="size-4" /> Previous
              </button>
              <button type="button" className={buttonStyles.secondary} disabled={page >= data.pages} onClick={() => setPage(page + 1)}>
                Next <ChevronRight className="size-4" />
              </button>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
