import { CircleAlert, Copy, Info, Loader2, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { STATUS_LABELS, STATUS_STYLES } from '../lib/format'
import type { FdrStatus } from '../types'

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500" role="status">
      <Loader2 className="size-5 animate-spin text-navy-500" />
      {label}
    </div>
  )
}

type AlertTone = 'info' | 'warning' | 'error'

const ALERT_STYLES: Record<AlertTone, { box: string; icon: ReactNode }> = {
  info: { box: 'border-sky-200 bg-sky-50 text-sky-900', icon: <Info className="mt-0.5 size-5 shrink-0 text-sky-600" /> },
  warning: {
    box: 'border-amber-200 bg-amber-50 text-amber-900',
    icon: <TriangleAlert className="mt-0.5 size-5 shrink-0 text-amber-600" />,
  },
  error: { box: 'border-red-200 bg-red-50 text-red-800', icon: <CircleAlert className="mt-0.5 size-5 shrink-0 text-red-600" /> },
}

export function Alert({
  tone = 'info',
  title,
  children,
  action,
}: {
  tone?: AlertTone
  title?: string
  children?: ReactNode
  action?: ReactNode
}) {
  const style = ALERT_STYLES[tone]
  return (
    <div className={`flex gap-3 rounded-lg border p-4 text-sm ${style.box}`} role={tone === 'error' ? 'alert' : 'note'}>
      {style.icon}
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={title ? 'mt-1' : ''}>{children}</div>}
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  )
}

export function StatusBadge({ status }: { status: FdrStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset ${STATUS_STYLES[status]}`}
    >
      {STATUS_LABELS[status]}
    </span>
  )
}

export function DuplicateBadge() {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium whitespace-nowrap text-amber-800 ring-1 ring-amber-200 ring-inset"
      title="Shares a bank and FDR reference with another record. Flagged for review; not a finding of fraud."
    >
      <Copy className="size-3" />
      Possible duplicate
    </span>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-lg border border-slate-200 bg-white shadow-sm ${className}`}>{children}</section>
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-xl font-semibold text-slate-900">{title}</h2>
        {description && <p className="mt-1 text-sm text-slate-600">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

export const buttonStyles = {
  primary:
    'inline-flex items-center justify-center gap-1.5 rounded-md bg-navy-700 px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:bg-navy-800 disabled:cursor-not-allowed disabled:opacity-60',
  secondary:
    'inline-flex items-center justify-center gap-1.5 rounded-md border border-slate-300 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60',
}

export const inputStyles =
  'block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-navy-500 focus:ring-2 focus:ring-navy-200 focus:outline-none aria-[invalid=true]:border-red-400 aria-[invalid=true]:ring-red-100'

export function Field({
  id,
  label,
  error,
  hint,
  required,
  children,
}: {
  id: string
  label: string
  error?: string
  hint?: string
  required?: boolean
  children: ReactNode
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-700">
        {label}
        {required && <span className="text-red-600"> *</span>}
      </label>
      <div className="mt-1">{children}</div>
      {error ? (
        <p id={`${id}-error`} className="mt-1 text-xs text-red-700">
          {error}
        </p>
      ) : (
        hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>
      )}
    </div>
  )
}
