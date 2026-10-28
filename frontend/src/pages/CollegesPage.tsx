import { Building2, ChevronLeft, ChevronRight, Mail, MapPin, Phone, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Alert, Card, DuplicateBadge, PageHeader, Spinner, StatusBadge, buttonStyles, inputStyles } from '../components/ui'
import { useApiQuery } from '../hooks/useApiQuery'
import { toQuery } from '../lib/api'
import { formatDate, formatDateTime, formatINR, LIFECYCLE_STATUS_LABELS, STATUS_LABELS } from '../lib/format'
import type { FdrListItem, FdrStatus, InstitutionSummary, Page } from '../types'

const PAGE_SIZE = 20
const STATUSES = Object.keys(STATUS_LABELS) as FdrStatus[]

function Pager({ page, pages, onPage, disabled }: { page: number; pages: number; onPage: (p: number) => void; disabled: boolean }) {
  if (pages <= 1) return null
  return (
    <div className="flex items-center justify-between gap-2 border-t border-slate-200 px-4 py-3 text-sm text-slate-600">
      <span>Page {page} of {pages}</span>
      <div className="flex gap-2">
        <button type="button" className={buttonStyles.secondary} disabled={disabled || page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft className="size-4" /> Previous
        </button>
        <button type="button" className={buttonStyles.secondary} disabled={disabled || page >= pages} onClick={() => onPage(page + 1)}>
          Next <ChevronRight className="size-4" />
        </button>
      </div>
    </div>
  )
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-slate-50 px-3 py-2">
      <p className="text-lg font-semibold text-slate-900 tabular-nums">{value}</p>
      <p className="text-xs text-slate-600">{label}</p>
    </div>
  )
}

/** The selected college's details and its FDRs. */
function CollegeRecords({ institutionId, backTo }: { institutionId: string; backTo: string }) {
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  useEffect(() => { setStatus(''); setPage(1) }, [institutionId])
  const college = useApiQuery<InstitutionSummary>(`/institutions/${institutionId}`)
  const fdrs = useApiQuery<Page<FdrListItem>>(
    `/fdrs${toQuery({ institution_id: institutionId, status, page, page_size: PAGE_SIZE, sort: 'newest' })}`,
  )

  if (college.status === 'error') {
    return (
      <Alert tone="error" title={college.error.status === 404 ? 'College not found' : 'Could not load this college'}
        action={college.error.status !== 404 && <button type="button" className={buttonStyles.secondary} onClick={college.reload}>Try again</button>}>
        {college.error.status === 404 ? 'Search again and choose a college from the results.' : college.error.message}
      </Alert>
    )
  }
  const c = college.data
  if (!c) return <Spinner label="Loading college…" />
  const data = fdrs.data

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <p className="text-xs font-medium text-slate-500">{c.code}</p>
        <h3 className="text-lg font-semibold text-slate-900">{c.name}</h3>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
          {c.state && <span className="inline-flex items-center gap-1"><MapPin className="size-3.5" />{c.state}</span>}
          {c.contact_email && <span className="inline-flex items-center gap-1 break-all"><Mail className="size-3.5" />{c.contact_email}</span>}
          {c.contact_phone && <span className="inline-flex items-center gap-1"><Phone className="size-3.5" />{c.contact_phone}</span>}
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Count label="FDRs submitted" value={c.fdr_total} />
          <Count label="Awaiting decision" value={c.fdrs_open_review} />
          <Count label="Accepted" value={c.fdrs_accepted} />
          <Count label="Rejected" value={c.fdrs_rejected} />
        </div>
      </Card>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
          <h4 className="text-sm font-semibold text-slate-900">Submitted FDRs</h4>
          <div className="w-full sm:w-56">
            <select aria-label="Filter by status" className={inputStyles} value={status}
              onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
              <option value="">All statuses</option>
              {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
            </select>
          </div>
        </div>
        {fdrs.status === 'error' && (
          <div className="p-4">
            <Alert tone="error" title="Could not load this college’s FDRs"
              action={<button type="button" className={buttonStyles.secondary} onClick={fdrs.reload}>Try again</button>}>
              {fdrs.error.message}
            </Alert>
          </div>
        )}
        {fdrs.status === 'loading' && !data && <Spinner label="Loading FDRs…" />}
        {data && data.total === 0 && (
          <p className="px-4 py-8 text-center text-sm text-slate-600">
            {status ? 'No FDRs with this status.' : 'This college has not submitted any FDRs.'}
          </p>
        )}
        {data && data.total > 0 && (
          <div className={fdrs.status === 'loading' ? 'opacity-60' : ''}>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50 text-left text-xs font-semibold tracking-wide text-slate-600 uppercase">
                  <tr>
                    <th scope="col" className="px-4 py-3">FDR number / bank</th>
                    <th scope="col" className="px-4 py-3 text-right">Amount</th>
                    <th scope="col" className="px-4 py-3">Submitted</th>
                    <th scope="col" className="px-4 py-3">Maturity</th>
                    <th scope="col" className="px-4 py-3">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.items.map((fdr) => (
                    <tr key={fdr.id} className="align-top hover:bg-slate-50">
                      <td className="px-4 py-3">
                        <Link to={`/fdr-records/${fdr.id}`} state={{ backTo, backLabel: 'Colleges' }} className="font-medium text-navy-700 hover:underline">
                          {fdr.fdr_number}
                        </Link>
                        <div className="text-xs text-slate-500">{fdr.bank_name}{fdr.branch_name && `, ${fdr.branch_name}`}</div>
                        {fdr.possible_duplicate && <div className="mt-1"><DuplicateBadge /></div>}
                      </td>
                      <td className="px-4 py-3 text-right whitespace-nowrap tabular-nums">{formatINR(fdr.amount)}</td>
                      <td className="px-4 py-3 whitespace-nowrap text-slate-700">{formatDateTime(fdr.created_at)}</td>
                      <td className="px-4 py-3 whitespace-nowrap text-slate-700">{formatDate(fdr.maturity_date)}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={fdr.status} />
                        {fdr.lifecycle_status !== 'ACTIVE' && (
                          <div className="mt-1 text-xs font-medium text-slate-600">{LIFECYCLE_STATUS_LABELS[fdr.lifecycle_status]}</div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={data.page} pages={data.pages} onPage={setPage} disabled={fdrs.status === 'loading'} />
          </div>
        )}
      </Card>
    </div>
  )
}

export default function CollegesPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const selected = params.get('id') ?? ''
  const page = Math.max(1, Number(params.get('page')) || 1)

  const [input, setInput] = useState(q)
  useEffect(() => setInput(q), [q])
  useEffect(() => {
    if (input === q) return
    const timer = window.setTimeout(() => update({ q: input, page: '' }), 300)
    return () => window.clearTimeout(timer)
  }, [input])

  function update(changes: Record<string, string>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    setParams(next, { replace: true })
  }

  const results = useApiQuery<Page<InstitutionSummary>>(`/institutions/search${toQuery({ q, page, page_size: PAGE_SIZE })}`)
  const data = results.data
  const backTo = `/colleges?${params.toString()}`

  return (
    <div className="space-y-5">
      <PageHeader title="Colleges" description="Find a college by name, code or state to see the FDRs it has submitted." />

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="space-y-3 lg:col-span-2">
          <div className="relative">
            <label htmlFor="college-search" className="sr-only">Search colleges</label>
            <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-slate-400" />
            <input id="college-search" type="search" className={`${inputStyles} pl-9`} placeholder="College name, code or state"
              maxLength={100} value={input} onChange={(e) => setInput(e.target.value)} />
          </div>

          {results.status === 'error' && (
            <Alert tone="error" title="Could not search colleges"
              action={<button type="button" className={buttonStyles.secondary} onClick={results.reload}>Try again</button>}>
              {results.error.message}
            </Alert>
          )}
          {results.status === 'loading' && !data && <Spinner label="Searching…" />}
          {data && data.total === 0 && (
            <Card className="p-8 text-center text-sm text-slate-600">
              {q ? <>No college matches “{q}”.</> : 'No colleges are registered yet.'}
            </Card>
          )}
          {data && data.total > 0 && (
            <Card className={results.status === 'loading' ? 'opacity-60' : ''}>
              <p className="border-b border-slate-200 px-4 py-2 text-xs text-slate-500">
                {data.total} college{data.total === 1 ? '' : 's'}{q && ` matching “${q}”`}
              </p>
              <ul className="divide-y divide-slate-100">
                {data.items.map((college) => {
                  const active = String(college.id) === selected
                  return (
                    <li key={college.id}>
                      <button type="button" aria-current={active || undefined} onClick={() => update({ id: String(college.id) })}
                        className={`flex w-full items-start gap-3 px-4 py-3 text-left ${active ? 'bg-navy-50' : 'hover:bg-slate-50'}`}>
                        <Building2 className={`mt-0.5 size-4 shrink-0 ${active ? 'text-navy-700' : 'text-slate-400'}`} />
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium text-slate-900">{college.name}</span>
                          <span className="block text-xs text-slate-500">{college.code}{college.state && ` · ${college.state}`}</span>
                        </span>
                        <span className="shrink-0 text-right text-xs text-slate-600">
                          <span className="block font-semibold text-slate-900 tabular-nums">{college.fdr_total} FDR{college.fdr_total === 1 ? '' : 's'}</span>
                          {college.fdrs_open_review > 0 && <span className="block text-navy-700">{college.fdrs_open_review} awaiting decision</span>}
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
              <Pager page={data.page} pages={data.pages} onPage={(p) => update({ page: String(p) })} disabled={results.status === 'loading'} />
            </Card>
          )}
        </div>

        <div className="lg:col-span-3">
          {selected ? (
            <CollegeRecords institutionId={selected} backTo={backTo} />
          ) : (
            <Card className="p-10 text-center text-sm text-slate-600">
              <Building2 className="mx-auto size-8 text-slate-300" />
              <p className="mt-2">Choose a college to see its submitted FDRs.</p>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
