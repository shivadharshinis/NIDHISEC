import type { AssignmentStatus, DocumentType, FdrStatus, OutcomeType, Role, VerificationState } from '../types'

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 })
const dateFormat = new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
const dateTimeFormat = new Intl.DateTimeFormat('en-IN', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

/** Formats a decimal string such as "250000.00" as ₹2,50,000.00 without float rounding of the paise. */
export function formatINR(amount: string): string {
  const [rupees, paise = '00'] = amount.split('.')
  const formatted = inr.format(Number(rupees))
  return formatted.replace(/\.\d{2}$/, `.${paise.padEnd(2, '0').slice(0, 2)}`)
}

/** Formats an ISO date (YYYY-MM-DD) without timezone shifting. */
export function formatDate(isoDate: string): string {
  const [y, m, d] = isoDate.split('-').map(Number)
  return dateFormat.format(new Date(y, m - 1, d))
}

export function formatDateTime(iso: string): string {
  return dateTimeFormat.format(new Date(iso))
}

/** Today's date as YYYY-MM-DD in the browser's local timezone. */
export function todayIso(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

export function addDaysIso(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split('-').map(Number)
  const date = new Date(y, m - 1, d + days)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export const ROLE_LABELS: Record<Role, string> = {
  INSTITUTION: 'Institution',
  BANK_OFFICER: 'Bank Officer',
  AICTE_OFFICIAL: 'AICTE Official',
}

export const STATUS_LABELS: Record<FdrStatus, string> = {
  SUBMITTED: 'Submitted',
  UNDER_REVIEW: 'Under AICTE review',
  CLARIFICATION_REQUESTED: 'Clarification requested',
  REJECTED: 'Rejected',
  ACCEPTED: 'Accepted by AICTE',
}

export const STATUS_STYLES: Record<FdrStatus, string> = {
  SUBMITTED: 'bg-slate-100 text-slate-700 ring-slate-300',
  UNDER_REVIEW: 'bg-sky-50 text-sky-800 ring-sky-200',
  CLARIFICATION_REQUESTED: 'bg-amber-50 text-amber-800 ring-amber-200',
  REJECTED: 'bg-red-50 text-red-700 ring-red-200',
  ACCEPTED: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
}

/** Statuses still awaiting a final AICTE decision; shown together as "Pending". */
export const PENDING_STATUSES: FdrStatus[] = ['SUBMITTED', 'UNDER_REVIEW', 'CLARIFICATION_REQUESTED']

/** Mirrors REVIEW_TRANSITIONS in backend/app/services/fdrs.py (the backend enforces it). */
export const REVIEW_TRANSITIONS: Record<FdrStatus, FdrStatus[]> = {
  SUBMITTED: ['UNDER_REVIEW', 'CLARIFICATION_REQUESTED', 'REJECTED'],
  UNDER_REVIEW: ['CLARIFICATION_REQUESTED', 'REJECTED', 'ACCEPTED'],
  CLARIFICATION_REQUESTED: ['UNDER_REVIEW', 'REJECTED'],
  REJECTED: [],
  ACCEPTED: [],
}

export const AUDIT_ACTION_LABELS: Record<string, string> = {
  LOGIN_SUCCEEDED: 'Signed in',
  LOGIN_FAILED: 'Failed sign-in',
  LOGIN_THROTTLED: 'Sign-in blocked',
  FDR_CREATED: 'FDR submitted',
  FDR_UPDATED: 'FDR updated',
  FDR_STATUS_CHANGED: 'Status changed',
  FDR_DUPLICATE_FLAGGED: 'Possible duplicate flagged',
  DOCUMENT_UPLOADED: 'Document uploaded',
  DOCUMENT_UPLOAD_REJECTED: 'Document upload rejected',
  DOCUMENT_DOWNLOADED: 'Document downloaded',
  DOCUMENT_WITHDRAWN: 'Document withdrawn',
  DOCUMENT_INTEGRITY_CHECKED: 'Document integrity checked',
  DOCUMENT_INTEGRITY_FAILED: 'Document integrity failure',
  VERIFICATION_ASSIGNED: 'Assigned for bank verification',
  VERIFICATION_REASSIGNED: 'Verification reassigned',
  VERIFICATION_CANCELLED: 'Verification assignment cancelled',
  VERIFICATION_OUTCOME_SUBMITTED: 'Bank officer outcome recorded',
  VERIFICATION_ACCESS_DENIED: 'Bank officer access denied',
  SCREENING_RUN_COMPLETED: 'Screening run completed',
  SCREENING_RUN_FAILED: 'Screening run failed',
  SCREENING_FINDING_REVIEWED: 'Screening finding reviewed',
  SCREENING_ACCESS_DENIED: 'Screening access denied',
  LIFECYCLE_REQUEST_SUBMITTED: 'Lifecycle request submitted',
  LIFECYCLE_REQUEST_UPDATED: 'Lifecycle request updated',
  LIFECYCLE_CHECK_RUN: 'Maturity check run',
  LIFECYCLE_ACCESS_DENIED: 'Lifecycle access denied',
}

export const OUTCOME_LABELS: Record<OutcomeType, string> = {
  CONFIRMED_AGAINST_BANK_RECORDS: 'Verified against bank records',
  DETAILS_MISMATCH: 'Discrepancy found',
  ADDITIONAL_INFO_REQUIRED: 'Additional information required',
  UNABLE_TO_VERIFY: 'Unable to verify',
}

export const OUTCOME_DESCRIPTIONS: Record<OutcomeType, string> = {
  CONFIRMED_AGAINST_BANK_RECORDS: 'The FDR details match your bank’s own records.',
  DETAILS_MISMATCH: 'Bank records exist but one or more details differ.',
  ADDITIONAL_INFO_REQUIRED: 'You need more information before you can check this FDR.',
  UNABLE_TO_VERIFY: 'The FDR could not be found or checked in your records.',
}

export const OUTCOME_STYLES: Record<OutcomeType, string> = {
  CONFIRMED_AGAINST_BANK_RECORDS: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
  DETAILS_MISMATCH: 'bg-red-50 text-red-700 ring-red-200',
  ADDITIONAL_INFO_REQUIRED: 'bg-amber-50 text-amber-800 ring-amber-200',
  UNABLE_TO_VERIFY: 'bg-slate-100 text-slate-700 ring-slate-300',
}

export const ASSIGNMENT_STATUS_LABELS: Record<AssignmentStatus, string> = {
  ACTIVE: 'Awaiting outcome',
  COMPLETED: 'Outcome recorded',
  SUPERSEDED: 'Reassigned',
  CANCELLED: 'Cancelled',
}

export const VERIFICATION_STATE_LABELS: Record<VerificationState, string> = {
  NOT_ASSIGNED: 'Not yet sent for bank verification',
  IN_PROGRESS: 'Bank verification in progress',
  OUTCOME_RECORDED: 'Bank verification step completed; awaiting AICTE decision',
}

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  FDR_COPY: 'FDR copy',
  BANK_LETTER: 'Bank letter',
  OTHER: 'Other supporting document',
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export const SEVERITY_LABELS: Record<'INFO' | 'WARNING' | 'HIGH', string> = {
  HIGH: 'High priority',
  WARNING: 'Warning',
  INFO: 'Informational',
}

export const SEVERITY_STYLES: Record<'INFO' | 'WARNING' | 'HIGH', string> = {
  HIGH: 'bg-red-50 text-red-700 ring-red-200',
  WARNING: 'bg-amber-50 text-amber-800 ring-amber-200',
  INFO: 'bg-slate-100 text-slate-700 ring-slate-300',
}

export const PRIORITY_STYLES: Record<'HIGH' | 'MEDIUM' | 'LOW', string> = {
  HIGH: 'bg-red-50 text-red-700 ring-red-200',
  MEDIUM: 'bg-amber-50 text-amber-800 ring-amber-200',
  LOW: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
}

export const CATEGORY_LABELS: Record<string, string> = {
  RECORD_VALIDATION: 'Record check',
  DOCUMENT_EXTRACTION: 'Document reading',
  DOCUMENT_CONSISTENCY: 'Record vs document',
  DUPLICATE: 'Duplicate / reuse',
  LIFECYCLE: 'Maturity (not an integrity concern)',
}

export const DISPOSITION_LABELS: Record<'CONCERN_CONFIRMED' | 'NEEDS_FOLLOW_UP' | 'DISMISSED_NOT_AN_ISSUE', string> = {
  CONCERN_CONFIRMED: 'Concern confirmed',
  NEEDS_FOLLOW_UP: 'Needs follow-up',
  DISMISSED_NOT_AN_ISSUE: 'Reviewed — not an issue',
}

export const MATCH_TYPE_LABELS: Record<string, string> = {
  EXACT: 'Exact duplicate',
  POSSIBLE: 'Possible match',
  NEAR_REFERENCE: 'Near-identical reference',
  SAME_FILE: 'Identical document file',
}

export const EXTRACTION_STATUS_LABELS: Record<string, string> = {
  EXTRACTED: 'Fields read from text layer',
  NO_FIELDS_FOUND: 'Readable, but no labelled fields found',
  NO_TEXT_LAYER: 'No text layer (likely scanned) — manual review',
  UNSUPPORTED_FORMAT: 'Image — no OCR available, manual review',
  FAILED: 'Could not be read — manual review',
  INTEGRITY_FAILED: 'Not read: integrity check failed',
}

export const LIFECYCLE_STATUS_LABELS: Record<string, string> = {
  ACTIVE: 'Active instrument',
  PROPOSED: 'Proposed (awaiting request completion)',
  RENEWED: 'Renewed (superseded)',
  REPLACED: 'Replaced (superseded)',
  RELEASED: 'Release recorded',
  CANCELLED: 'Cancelled proposal',
}

export const REQUEST_TYPE_LABELS: Record<string, string> = {
  RENEWAL: 'Renewal',
  REPLACEMENT: 'Replacement',
  RELEASE: 'Release / refund',
}

export const REQUEST_STATUS_LABELS: Record<string, string> = {
  SUBMITTED: 'Submitted',
  UNDER_REVIEW: 'Under AICTE review',
  CLARIFICATION_REQUESTED: 'Clarification requested',
  APPROVED: 'Approved — awaiting completion',
  REJECTED: 'Rejected',
  WITHDRAWN: 'Withdrawn',
  COMPLETED: 'Completed',
}

export const REQUEST_STATUS_STYLES: Record<string, string> = {
  SUBMITTED: 'bg-slate-100 text-slate-700 ring-slate-300',
  UNDER_REVIEW: 'bg-sky-50 text-sky-800 ring-sky-200',
  CLARIFICATION_REQUESTED: 'bg-amber-50 text-amber-800 ring-amber-200',
  APPROVED: 'bg-indigo-50 text-indigo-800 ring-indigo-200',
  REJECTED: 'bg-red-50 text-red-700 ring-red-200',
  WITHDRAWN: 'bg-slate-100 text-slate-500 ring-slate-300',
  COMPLETED: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
}

export const LIFECYCLE_ACTION_LABELS: Record<string, string> = {
  SUBMIT: 'Submitted',
  START_REVIEW: 'Review started',
  REQUEST_CLARIFICATION: 'Clarification requested',
  RESPOND: 'Institution responded',
  APPROVE: 'Approved',
  REJECT: 'Rejected',
  WITHDRAW: 'Withdrawn',
  COMPLETE: 'Completion recorded',
}

export function describeDays(days: number): string {
  if (days === 0) return 'matures today'
  return days > 0 ? `${days} day${days === 1 ? '' : 's'} remaining` : `${-days} day${days === -1 ? '' : 's'} overdue`
}
