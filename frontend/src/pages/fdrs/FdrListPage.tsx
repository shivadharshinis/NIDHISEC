import { ChevronLeft, ChevronRight, FilePlus2, Search, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useCurrentUser } from '../../auth/AuthContext'
import { Alert, Card, DuplicateBadge, PageHeader, Spinner, StatusBadge, buttonStyles, inputStyles } from '../../components/ui'
import { useApiQuery } from '../../hooks/useApiQuery'
import { toQuery } from '../../lib/api'
import { formatDate, formatINR, STATUS_LABELS } from '../../lib/format'
import type { FdrListItem, FdrStatus, InstitutionBrief, Page } from '../../types'

const PAGE_SIZE = 20
const STATUSES = Object.keys(STATUS_LABELS) as FdrStatus[]
const SORTS = {
  newest: 'Newest first',
  oldest: 'Oldest first',
  maturity_asc: 'Maturity: soonest',
  maturity_desc: 'Maturity: latest',
  amount_desc: 'Amount: highest',
  amount_asc: 'Amount: lowest',
} as const

export default function FdrListPage() {
  const user = useCurrentUser()
  const isAicte = user.role === 'AICTE_OFFICIAL'
  const [params, setParams] = useSearchParams()

  const q = params.get('q') ?? ''
  const status = params.get('status') ?? ''
  const institutionId = params.get('institution_id') ?? ''
  const duplicatesOnly = params.get('duplicates') === '1'
  const maturityFrom = params.get('maturity_from') ?? ''
  const maturityTo = params.get('maturity_to') ?? ''
  const sort = params.get('sort') ?? 'newest'
  const page = Math.max(1, Number(params.get('page')) || 1)

  // Debounce the search box so we don't query on every keystroke.
  const [searchInput, setSearchInput] = useState(q)
  useEffect(() => setSearchInput(q), [q])
  useEffect(() => {
    if (searchInput === q) return
    const timer = window.setTimeout(() => updateParams({ q: searchInput }), 350)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  function updateParams(changes: Record<string, string>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    if (!('page' in changes)) next.delete('page')
    setParams(next, { replace: true })
  }

  const path = `/fdrs${toQuery({
    page,
    page_size: PAGE_SIZE,
    q,
    status,
    institution_id: isAicte ? institutionId : '',
    duplicates_only: duplicatesOnly,
    maturity_from: maturityFrom,
    maturity_to: maturityTo,
    sort,
  })}`
  const result = useApiQuery<Page<FdrListItem>>(path)
  const institutions = useApiQuery<InstitutionBrief[]>(isAicte ? '/institutions' : null)

  const hasFilters = Boolean(q || status || institutionId || duplicatesOnly || maturityFrom || maturityTo)
  const data = result.data

  return (
    <div className="space-y-5">
      <PageHeader
        title="FDR Records"
        description={
          isAicte
            ? 'FDRs submitted by all institutions. Search, filter and open a record to review it.'
            : `FDRs submitted by ${user.institution?.name ?? 'your institution'}.`
        }
        actions={
          user.role === 'INSTITUTION' && (
            <Link to="/fdr-records/new" className={buttonStyles.primary}>
              <FilePlus2 className="size-4" /> Submit FDR
            </Link>
          )
        }
      />

      <Card className="p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="relative sm:col-span-2">
            <label htmlFor="fdr-search" className="sr-only">Search</label>
            <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-slate-400" />
            <input
              id="fdr-search"
              type="search"
              placeholder={isAicte ? 'FDR number, bank, branch or institution' : 'FDR number, bank or branch'}
              className={`${inputStyles} pl-9`}
              value={searchInput}
              maxLength={100}
              onChange={(e) => setSearchInput(e.target.value)}
            />
          </div>
          <select
            aria-label="Status"
            className={inputStyles}
            value={status}
            onChange={(e) => updateParams({ status: e.target.value })}
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{STATUS_LABELS[s]}</option>
            ))}
          </select>
          <select aria-label="Sort by" className={inputStyles} value={sort} onChange={(e) => updateParams({ sort: e.target.value })}>
            {Object.entries(SORTS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          {isAicte && (
            <select
              aria-label="Institution"
              className={`${inputStyles} sm:col-span-2`}
              value={institutionId}
              onChange={(e) => updateParams({ institution_id: e.target.value })}
            >
              <option value="">All institutions</option>
              {institutions.data?.map((inst) => (
                <option key={inst.id} value={inst.id}>{inst.code} — {inst.name}</option>
              ))}
            </select>
          )}
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              className="size-4 rounded border-slate-300 text-navy-700"
              checked={duplicatesOnly}
              onChange={(e) => updateParams({ duplicates: e.target.checked ? '1' : '' })}
            />
            Possible duplicates only
          </label>
          {hasFilters && (
            <button
              type="button"
              className="inline-flex items-center gap-1 justify-self-start text-sm font-medium text-navy-600 hover:text-navy-800"
              onClick={() => setParams(sort !== 'newest' ? { sort } : {}, { replace: true })}
            >
              <X className="size-4" /> Clear filters
            </button>
          )}
        </div>
        {(maturityFrom || maturityTo) && (
          <p className="mt-3 text-xs text-slate-600">
            Maturity {maturityFrom && `from ${formatDate(maturityFrom)}`} {maturityTo && `to ${formatDate(maturityTo)}`}
          </p>
        )}
      </Card>

      {result.status === 'error' && (
        <Alert
          tone="error"
          title="Could not load FDR records"
          action={<button type="button" className={buttonStyles.secondary} onClick={result.reload}>Try again</button>}
        >
          {result.error.message}
        </Alert>
      )}

      {result.status === 'loading' && !data && <Spinner label="Loading FDR records…" />}

      {data && data.total === 0 && result.status === 'success' && (
        <Card className="p-10 text-center">
          <p className="text-sm font-semibold text-slate-900">
            {hasFilters ? 'No records match these filters' : 'No FDR records yet'}
          </p>
          <p className="mt-1 text-sm text-slate-600">
            {hasFilters
              ? 'Try a different search or clear the filters.'
              : user.role === 'INSTITUTION'
                ? 'Submit your institution’s first FDR to start tracking it.'
                : 'Records will appear here once institutions submit them.'}
          </p>
          {!hasFilters && user.role === 'INSTITUTION' && (
            <Link to="/fdr-records/new" className={`${buttonStyles.primary} mt-5`}>
              <FilePlus2 className="size-4" /> Submit FDR
            </Link>
          )}
        </Card>
      )}

      {data && data.total > 0 && (
        <Card className={result.status === 'loading' ? 'opacity-60 transition-opacity' : ''}>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold tracking-wide text-slate-600 uppercase">
                <tr>
                  <th scope="col" className="px-4 py-3">FDR number</th>
                  {isAicte && <th scope="col" className="px-4 py-3">Institution</th>}
                  <th scope="col" className="px-4 py-3">Bank</th>
                  <th scope="col" className="px-4 py-3 text-right">Amount</th>
                  <th scope="col" className="px-4 py-3">Maturity</th>
                  <th scope="col" className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((fdr) => (
                  <tr key={fdr.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 align-top">
                      <Link to={`/fdr-records/${fdr.id}`} className="font-medium text-navy-700 hover:underline">
                        {fdr.fdr_number}
                      </Link>
                      {fdr.possible_duplicate && <div className="mt-1"><DuplicateBadge /></div>}
                    </td>
                    {isAicte && (
                      <td className="px-4 py-3 align-top">
                        <div className="text-slate-900">{fdr.institution.code}</div>
                        <div className="max-w-56 truncate text-xs text-slate-500">{fdr.institution.name}</div>
                      </td>
                    )}
                    <td className="px-4 py-3 align-top">
                      <div className="text-slate-900">{fdr.bank_name}</div>
                      {fdr.branch_name && <div className="text-xs text-slate-500">{fdr.branch_name}</div>}
                    </td>
                    <td className="px-4 py-3 text-right align-top whitespace-nowrap text-slate-900 tabular-nums">
                      {formatINR(fdr.amount)}
                    </td>
                    <td className="px-4 py-3 align-top whitespace-nowrap text-slate-700">{formatDate(fdr.maturity_date)}</td>
                    <td className="px-4 py-3 align-top"><StatusBadge status={fdr.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3 text-sm text-slate-600">
            <span>
              Showing {(data.page - 1) * data.page_size + 1}–{Math.min(data.page * data.page_size, data.total)} of {data.total}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                className={buttonStyles.secondary}
                disabled={data.page <= 1 || result.status === 'loading'}
                onClick={() => updateParams({ page: String(data.page - 1) })}
              >
                <ChevronLeft className="size-4" /> Previous
              </button>
              <button
                type="button"
                className={buttonStyles.secondary}
                disabled={data.page >= data.pages || result.status === 'loading'}
                onClick={() => updateParams({ page: String(data.page + 1) })}
              >
                Next <ChevronRight className="size-4" />
              </button>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
