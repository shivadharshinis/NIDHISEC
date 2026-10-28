import { X } from 'lucide-react'
import { NavLink } from 'react-router'
import { useCurrentUser } from '../../auth/AuthContext'
import { navItemsFor } from '../../navigation'
import BrandMark from '../BrandMark'

interface SidebarProps {
  onClose?: () => void
}

export default function Sidebar({ onClose }: SidebarProps) {
  const user = useCurrentUser()

  return (
    <div className="flex h-full flex-col bg-navy-900 text-navy-100">
      <div className="flex items-center gap-3 border-b border-white/10 px-5 py-5">
        <BrandMark className="size-9 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="text-lg leading-tight font-semibold tracking-tight text-white">NidhiSec</div>
          <div className="truncate text-[11px] leading-tight text-navy-300">AICTE FDR Management Portal</div>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-navy-200 hover:bg-white/10 hover:text-white"
            aria-label="Close navigation"
          >
            <X className="size-5" />
          </button>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4" aria-label="Primary">
        <p className="px-3 pb-2 text-[11px] font-semibold tracking-wider text-navy-400 uppercase">Modules</p>
        <ul className="space-y-1">
          {navItemsFor(user.role).map(({ path, label, icon: Icon, implemented }) => (
            <li key={path}>
              <NavLink
                to={path}
                end={path === '/'}
                className={({ isActive }) =>
                  `group flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                    isActive ? 'bg-white/10 text-white' : 'text-navy-200 hover:bg-white/5 hover:text-white'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon className={`size-4.5 shrink-0 ${isActive ? 'text-sky-300' : 'text-navy-300'}`} />
                    <span className="flex-1">{label}</span>
                    {!implemented && (
                      <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] font-medium text-navy-300">
                        Planned
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="border-t border-white/10 px-5 py-4 text-[11px] leading-relaxed text-navy-400">
        AICTE Security Deposit / FDR Management Portal
      </div>
    </div>
  )
}
