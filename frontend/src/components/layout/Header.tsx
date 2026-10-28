import { LogOut, Menu } from 'lucide-react'
import { useLocation } from 'react-router'
import { useAuth, useCurrentUser } from '../../auth/AuthContext'
import { ROLE_LABELS } from '../../lib/format'
import NotificationBell from '../notifications/NotificationBell'
import { NAV_ITEMS } from '../../navigation'

interface HeaderProps {
  onOpenNav: () => void
}

export default function Header({ onOpenNav }: HeaderProps) {
  const { pathname } = useLocation()
  const { logout } = useAuth()
  const user = useCurrentUser()
  const current = NAV_ITEMS.find(
    (item) => item.path === pathname || (item.path !== '/' && pathname.startsWith(`${item.path}/`)),
  )
  const title = current?.label
    ?? (pathname.startsWith('/lifecycle-requests/') ? 'Lifecycle request' : pathname === '/notifications' ? 'Notifications' : 'Page not found')

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div className="flex h-16 items-center gap-3 px-4 sm:px-6 lg:px-8">
        <button
          type="button"
          onClick={onOpenNav}
          className="-ml-1 rounded-md p-2 text-slate-600 hover:bg-slate-100 lg:hidden"
          aria-label="Open navigation"
        >
          <Menu className="size-5" />
        </button>

        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-slate-500">
            <span className="font-semibold text-navy-700">NidhiSec</span>
            <span className="hidden sm:inline"> · AICTE Security Deposit / FDR Management Portal</span>
          </p>
          <h1 className="truncate text-base font-semibold text-slate-900">{title}</h1>
        </div>

        <NotificationBell />

        <div className="hidden min-w-0 text-right md:block">
          <p className="truncate text-sm font-medium text-slate-900">{user.full_name}</p>
          <p className="truncate text-xs text-slate-500">
            {ROLE_LABELS[user.role]}
            {user.institution && ` · ${user.institution.code}`}
          </p>
        </div>
        <button
          type="button"
          onClick={() => logout()}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
        >
          <LogOut className="size-3.5" />
          <span className="hidden sm:inline">Sign out</span>
        </button>
      </div>
    </header>
  )
}
