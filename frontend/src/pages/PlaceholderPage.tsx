import { Construction } from 'lucide-react'
import { Link } from 'react-router'
import type { NavItem } from '../navigation'

export default function PlaceholderPage({ item }: { item: NavItem }) {
  const Icon = item.icon

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
      <div className="flex items-start gap-4">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-navy-50 text-navy-600">
          <Icon className="size-6" />
        </span>
        <div>
          <h2 className="text-xl font-semibold text-slate-900">{item.label}</h2>
          <p className="mt-1 text-sm text-slate-600">{item.summary}</p>
        </div>
      </div>

      <div className="mt-6 flex gap-3 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        <Construction className="mt-0.5 size-5 shrink-0 text-amber-600" />
        <p>This module has not been implemented yet. No data is stored or processed here.</p>
      </div>

      {item.planned.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold text-slate-900">Planned scope</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600">
            {item.planned.map((entry) => (
              <li key={entry}>{entry}</li>
            ))}
          </ul>
        </div>
      )}

      <Link to="/" className="mt-8 inline-block text-sm font-medium text-navy-600 hover:text-navy-800">
        ← Back to dashboard
      </Link>
    </div>
  )
}
