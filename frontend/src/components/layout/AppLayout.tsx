import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router'
import Header from './Header'
import Sidebar from './Sidebar'

export default function AppLayout() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const { pathname } = useLocation()

  // Close the mobile drawer after navigating.
  useEffect(() => setMobileNavOpen(false), [pathname])

  useEffect(() => {
    if (!mobileNavOpen) return
    const onKeyDown = (event: KeyboardEvent) => event.key === 'Escape' && setMobileNavOpen(false)
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [mobileNavOpen])

  return (
    <div className="min-h-screen">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:shadow"
      >
        Skip to main content
      </a>

      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-64 lg:block">
        <Sidebar />
      </aside>

      {/* Mobile drawer */}
      {mobileNavOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-slate-900/50" onClick={() => setMobileNavOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85vw] shadow-xl">
            <Sidebar onClose={() => setMobileNavOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-h-screen flex-col lg:pl-64">
        <Header onOpenNav={() => setMobileNavOpen(true)} />
        <main id="main-content" className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
        <footer className="border-t border-slate-200 px-4 py-4 text-xs text-slate-500 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            NidhiSec · AICTE Security Deposit / FDR Management Portal · Development prototype — not for use with real
            financial records.
          </div>
        </footer>
      </div>
    </div>
  )
}
