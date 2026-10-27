import { Link } from 'react-router'

export default function NotFoundPage() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-8 text-center shadow-sm">
      <p className="text-sm font-semibold text-navy-600">404</p>
      <h2 className="mt-1 text-xl font-semibold text-slate-900">Page not found</h2>
      <p className="mt-2 text-sm text-slate-600">The page you requested does not exist in NidhiSec.</p>
      <Link to="/" className="mt-6 inline-block text-sm font-medium text-navy-600 hover:text-navy-800">
        ← Back to dashboard
      </Link>
    </div>
  )
}
