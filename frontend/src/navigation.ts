import {
  BadgeCheck,
  CalendarClock,
  FileStack,
  FileText,
  LayoutDashboard,
  ListChecks,
  ScanSearch,
  type LucideIcon,
  ScrollText,
  Undo2,
} from 'lucide-react'
import type { Role } from './types'

export interface NavItem {
  path: string
  label: string
  icon: LucideIcon
  /** Shown on the placeholder page until the module is built. */
  summary: string
  planned: string[]
  /** Whether the module works today. Unimplemented modules render a placeholder. */
  implemented: boolean
  /** Roles that see this item. Omitted = every signed-in role. */
  roles?: Role[]
}

export const NAV_ITEMS: NavItem[] = [
  {
    path: '/',
    label: 'Dashboard',
    icon: LayoutDashboard,
    summary: 'Overview of the portal and system status.',
    planned: [],
    implemented: true,
  },
  {
    path: '/action-centre',
    label: 'Action Centre',
    icon: ListChecks,
    summary: 'Items that need attention: corrections, missing documents, deadlines, requests and review workload.',
    planned: [],
    implemented: true,
    roles: ['INSTITUTION', 'AICTE_OFFICIAL'],
  },
  {
    path: '/fdr-records',
    label: 'FDR Records',
    icon: FileStack,
    summary: 'Submission and management of Fixed Deposit Receipts lodged as security deposits.',
    planned: ['OCR for scanned documents and images'],
    implemented: true,
    // Bank officers will see assigned records once verification assignments exist.
    roles: ['INSTITUTION', 'AICTE_OFFICIAL'],
  },
  {
    path: '/verification',
    label: 'Verification',
    icon: BadgeCheck,
    summary: 'Assignment of FDRs to bank officers and their recorded verification outcomes.',
    planned: [],
    implemented: true,
    roles: ['AICTE_OFFICIAL', 'BANK_OFFICER'],
  },
  {
    path: '/screening',
    label: 'Screening',
    icon: ScanSearch,
    summary: 'Advisory, explainable checks that help prioritise human review. Never rejects or verifies anything.',
    planned: [],
    implemented: true,
    roles: ['AICTE_OFFICIAL'],
  },
  {
    path: '/renewals',
    label: 'Renewals & Maturity',
    icon: CalendarClock,
    summary: 'Maturity tracking with alerts, and renewal/replacement requests linking old and new instruments.',
    planned: [],
    implemented: true,
    roles: ['INSTITUTION', 'AICTE_OFFICIAL'],
  },
  {
    path: '/release-requests',
    label: 'Release Requests',
    icon: Undo2,
    summary: 'Release/refund requests with AICTE review and a separately recorded completion step.',
    planned: [],
    implemented: true,
    roles: ['INSTITUTION', 'AICTE_OFFICIAL'],
  },
  {
    path: '/reports',
    label: 'Reports',
    icon: FileText,
    summary: 'Snapshot reports across institutions: status, lifecycle, maturity and institution-wise summaries.',
    planned: [],
    implemented: true,
    roles: ['AICTE_OFFICIAL'],
  },
  {
    path: '/audit-logs',
    label: 'Audit Logs',
    icon: ScrollText,
    summary: 'Append-only trail of sign-ins and record changes.',
    planned: [],
    implemented: true,
    roles: ['AICTE_OFFICIAL'],
  },
]

export function navItemsFor(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => !item.roles || item.roles.includes(role))
}
