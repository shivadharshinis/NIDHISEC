import { Bell, Loader2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { ApiError, apiGet, apiRequest } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type { NotificationRead, Page } from '../../types'

const POLL_MS = 60_000

export default function NotificationBell() {
  const [unread, setUnread] = useState<number | null>(null)
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<NotificationRead[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const { pathname } = useLocation()

  const refreshCount = useCallback(() => {
    apiGet<{ unread: number }>('/notifications/unread-count')
      .then((r) => setUnread(r.unread))
      .catch(() => setUnread(null))
  }, [])

  useEffect(() => {
    refreshCount()
    const timer = window.setInterval(refreshCount, POLL_MS)
    return () => window.clearInterval(timer)
  }, [refreshCount, pathname])

  useEffect(() => {
    if (!open) return
    setItems(null)
    setError(null)
    apiGet<Page<NotificationRead>>('/notifications?page_size=8')
      .then((page) => setItems(page.items))
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Could not load notifications'))
    const onClick = (event: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  async function openNotification(item: NotificationRead) {
    if (!item.read_at) {
      await apiRequest(`/notifications/${item.id}/read`, { method: 'POST' }).catch(() => undefined)
      refreshCount()
    }
    setOpen(false)
    if (item.link) navigate(item.link)
  }

  async function markAll() {
    await apiRequest('/notifications/read-all', { method: 'POST' }).catch(() => undefined)
    setItems((current) => current?.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })) ?? null)
    refreshCount()
  }

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="relative rounded-md p-2 text-slate-600 hover:bg-slate-100"
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        aria-expanded={open}
      >
        <Bell className="size-5" />
        {unread !== null && unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-4.5 rounded-full bg-red-600 px-1 text-center text-[10px] leading-4.5 font-semibold text-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-lg border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
            <p className="text-sm font-semibold text-slate-900">Notifications</p>
            <button type="button" className="text-xs font-medium text-navy-600 hover:text-navy-800 disabled:opacity-50"
              onClick={markAll} disabled={!unread}>Mark all read</button>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {error && <p className="px-4 py-3 text-sm text-red-700">{error}</p>}
            {!items && !error && <p className="flex items-center gap-2 px-4 py-3 text-sm text-slate-500"><Loader2 className="size-4 animate-spin" /> Loading…</p>}
            {items && items.length === 0 && <p className="px-4 py-6 text-center text-sm text-slate-500">No notifications yet.</p>}
            {items?.map((item) => (
              <button key={item.id} type="button" onClick={() => openNotification(item)}
                className={`block w-full border-b border-slate-50 px-4 py-3 text-left hover:bg-slate-50 ${item.read_at ? '' : 'bg-sky-50/60'}`}>
                <p className="flex items-start gap-2 text-sm font-medium text-slate-900">
                  {!item.read_at && <span className="mt-1.5 size-2 shrink-0 rounded-full bg-sky-600" aria-label="Unread" />}
                  {item.title}
                </p>
                <p className="mt-0.5 text-xs text-slate-600">{item.body}</p>
                <p className="mt-1 text-[11px] text-slate-400">{formatDateTime(item.created_at)}</p>
              </button>
            ))}
          </div>
          <Link to="/notifications" onClick={() => setOpen(false)} className="block border-t border-slate-100 px-4 py-2.5 text-center text-xs font-medium text-navy-600 hover:bg-slate-50">
            View all notifications
          </Link>
        </div>
      )}
    </div>
  )
}
