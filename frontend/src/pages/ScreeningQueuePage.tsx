import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { PriorityBadge } from '../components/screening/ScreeningPanel'
import { Alert, Card, PageHeader, Spinner, StatusBadge, buttonStyles, inputStyles } from '../components/ui'
import { useApiQuery } from '../hooks/useApiQuery'
import { toQuery } from '../lib/api'
import { formatDateTime } from '../lib/format'
import type { Page, ReviewPriority, ScreeningQueueItem } from '../types'

const PAGE_SIZE = 20

export default function ScreeningQueuePage() {
  const [priority, setPriority] = useState<ReviewPriority | ''>('')
  const [page, setPage] = useState(1)
  const result = useApiQuery<Page<ScreeningQueueItem>>(`/screening/queue${toQuery({ priority, page, page_size: PAGE_SIZE })}`)
  const data = result.data

  return (
    <div className="space-y-5">
      <PageHeader
        title="Screening"
        description="Latest advisory screening result for each screened FDR, highest review priority first. Run screening from an FDR’s record page."
        actions={
          <select aria-label="Review priority" className={inputStyles} value={priority} onChange={(e) => { setPriority(e.target.value as ReviewPriority | ''); setPage(1) }}>
            <option value="">All priorities</option>
            <option value="HIGH">High</option>
            <option value="MEDIUM">Medium</option>
            <option value="LOW">Low</option>
          </select>
        }
      />
      <Alert tone="info">
        Screening is advisory. It orders records for human review; it does not reject, accept or verify anything, and a
        duplicate match is not proof of fraud.
      </Alert>

      {result.status === 'error' && (
        <Alert tone="error" title="Could not load the screening queue" action={<button type="button" className={buttonStyles.secondary} onClick={result.reload}>Try again</button>}>
          {result.error.message}
        </Alert>
      )}
      {result.status === 'loading' && !data && <Spinner label="Loading screening results…" />}
      {data && data.total === 0 && (
        <Card className="p-10 text-center text-sm text-slate-600">
          No screened records{priority ? ' with this priority' : ''} yet.
        </Card>
      )}
      {data && data.total > 0 && (
        <Card className={result.status === 'loading' ? 'opacity-60' : ''}>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold tracking-wide text-slate-600 uppercase">
                <tr>
                  <th scope="col" className="px-4 py-3">FDR</th>
                  <th scope="col" className="px-4 py-3">Institution</th>
                  <th scope="col" className="px-4 py-3">Priority</th>
                  <th scope="col" className="px-4 py-3">Findings</th>
                  <th scope="col" className="px-4 py-3">Not yet reviewed</th>
                  <th scope="col" className="px-4 py-3">Screened</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((item) => (
                  <tr key={item.run_id} className="align-top hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <Link to={`/fdr-records/${item.fdr_id}`} className="font-medium text-navy-700 hover:underline">{item.fdr_number}</Link>
                      <div className="text-xs text-slate-500">{item.bank_name}</div>
                      <div className="mt-1"><StatusBadge status={item.fdr_status} /></div>
                    </td>
                    <td className="px-4 py-3 text-slate-700">{item.institution.code}</td>
                    <td className="px-4 py-3">
                      {item.run_status === 'FAILED' ? <span className="text-xs text-red-700">Last run failed</span> : <PriorityBadge priority={item.review_priority} />}
                    </td>
                    <td className="px-4 py-3 text-xs whitespace-nowrap text-slate-700">
                      {item.high_count} high · {item.warning_count} warning · {item.info_count} info
                    </td>
                    <td className="px-4 py-3 text-xs whitespace-nowrap text-slate-700">
                      {item.unreviewed_high} high · {item.unreviewed_warning} warning
                    </td>
                    <td className="px-4 py-3 text-xs whitespace-nowrap text-slate-700">
                      Run #{item.run_number}, {formatDateTime(item.completed_at)}
                      {item.is_stale && <div className="text-amber-700">Record changed since</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3 text-sm text-slate-600">
            <span>{data.total} record{data.total === 1 ? '' : 's'} · page {data.page} of {Math.max(data.pages, 1)}</span>
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
