/** Types mirroring the backend schemas in backend/app/schemas. */

export type Role = 'INSTITUTION' | 'BANK_OFFICER' | 'AICTE_OFFICIAL'

export type FdrStatus = 'SUBMITTED' | 'UNDER_REVIEW' | 'CLARIFICATION_REQUESTED' | 'REJECTED' | 'ACCEPTED'

export interface InstitutionBrief {
  id: number
  name: string
  code: string
}

export interface User {
  id: number
  full_name: string
  email: string
  role: Role
  institution: InstitutionBrief | null
  is_active: boolean
  last_login_at: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_at: string
  user: User
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface FdrListItem {
  id: number
  institution: InstitutionBrief
  bank_name: string
  branch_name: string | null
  ifsc_code: string | null
  fdr_number: string
  /** Decimal serialised as a string, e.g. "250000.00" */
  amount: string
  issue_date: string
  maturity_date: string
  status: FdrStatus
  lifecycle_status: LifecycleStatus
  possible_duplicate: boolean
  version: number
  created_at: string
  updated_at: string
}

export interface DuplicateMatch {
  id: number
  institution: InstitutionBrief
  bank_name: string
  fdr_number: string
  status: FdrStatus
  created_at: string
  same_institution: boolean
}

export type DocumentType = 'FDR_COPY' | 'BANK_LETTER' | 'OTHER'

/** Mirrors backend/app/schemas/document.py. Never contains storage paths. */
export interface DocumentRead {
  id: number
  fdr_id: number
  document_type: DocumentType
  original_filename: string
  content_type: string
  size_bytes: number
  sha256: string
  uploaded_at: string
  uploaded_by_name: string
  is_withdrawn: boolean
  withdrawn_at: string | null
  withdrawn_by_name: string | null
  withdrawal_reason: string | null
}

export interface DocumentList {
  items: DocumentRead[]
  can_upload: boolean
  can_withdraw: boolean
  can_check_integrity: boolean
  max_upload_bytes: number
  allowed_extensions: string[]
}

export interface IntegrityReport {
  document_id: number
  status: 'intact' | 'mismatch' | 'missing'
  expected_sha256: string
  actual_sha256: string | null
  checked_at: string
}

export interface FdrDetail extends FdrListItem {
  remarks: string | null
  review_remarks: string | null
  created_by_name: string
  documents: DocumentRead[]
  duplicate_review: {
    flagged: boolean
    match_count: number
    matches: DuplicateMatch[]
    hidden_match_count: number
  }
  can_edit: boolean
  can_review: boolean
  can_upload_documents: boolean
  verification_state: VerificationState
}

export interface FdrSummary {
  total: number
  by_status: Record<FdrStatus, number>
  possible_duplicates: number
  maturing_within_90_days: number
  matured: number
}

export interface FdrHistoryEntry {
  id: number
  created_at: string
  action: string
  summary: string
  actor_name: string | null
  actor_role: Role | null
  changes: Record<string, unknown> | null
}

export interface AuditLogEntry {
  id: number
  created_at: string
  actor_user_id: number | null
  actor_email: string | null
  actor_name: string | null
  actor_role: Role | null
  action: string
  entity_type: string
  entity_id: number | null
  institution_id: number | null
  summary: string
  changes: Record<string, unknown> | null
  ip_address: string | null
}

/** Fields an institution submits or edits. All values are form strings. */
export interface FdrFormValues {
  bank_name: string
  branch_name: string
  ifsc_code: string
  fdr_number: string
  amount: string
  issue_date: string
  maturity_date: string
  remarks: string
}

// ---------- bank verification (mirrors backend/app/schemas/verification.py) ----------

export type VerificationState = 'NOT_ASSIGNED' | 'IN_PROGRESS' | 'OUTCOME_RECORDED'
export type AssignmentStatus = 'ACTIVE' | 'COMPLETED' | 'SUPERSEDED' | 'CANCELLED'
export type OutcomeType =
  | 'CONFIRMED_AGAINST_BANK_RECORDS'
  | 'DETAILS_MISMATCH'
  | 'ADDITIONAL_INFO_REQUIRED'
  | 'UNABLE_TO_VERIFY'

export interface UserBrief {
  id: number
  full_name: string
  email: string
}

export interface OutcomeRead {
  id: number
  assignment_id: number
  outcome: OutcomeType
  notes: string
  bank_reference: string | null
  evidence_documents: DocumentRead[]
  method: string
  submitted_by: UserBrief
  submitted_at: string
}

export interface AssignmentRead {
  id: number
  fdr_id: number
  status: AssignmentStatus
  bank_officer: UserBrief
  assigned_by: UserBrief
  assigned_at: string
  assignment_note: string | null
  previous_assignment_id: number | null
  ended_at: string | null
  ended_by: UserBrief | null
  end_reason: string | null
  version: number
  outcome: OutcomeRead | null
}

export interface ReviewDecisionRead {
  id: number
  previous_status: FdrStatus
  new_status: FdrStatus
  message_to_institution: string | null
  internal_notes: string | null
  reviewed_outcome_id: number | null
  decided_by: UserBrief
  decided_at: string
}

export interface VerificationHistory {
  fdr_id: number
  fdr_status: FdrStatus
  fdr_version: number
  state: VerificationState
  can_assign: boolean
  can_accept: boolean
  active_assignment: AssignmentRead | null
  assignments: AssignmentRead[]
  decisions: ReviewDecisionRead[]
}

export interface AssignmentQueueItem {
  id: number
  status: AssignmentStatus
  fdr_id: number
  fdr_number: string
  bank_name: string
  institution: InstitutionBrief
  bank_officer: UserBrief
  assigned_at: string
  ended_at: string | null
  outcome: OutcomeType | null
}

export interface BankCaseSummary {
  id: number
  status: AssignmentStatus
  assigned_at: string
  ended_at: string | null
  fdr_number: string
  bank_name: string
  institution: InstitutionBrief
  outcome: OutcomeType | null
}

export interface BankCase {
  id: number
  status: AssignmentStatus
  version: number
  assigned_at: string
  assignment_note: string | null
  ended_at: string | null
  fdr_number: string
  bank_name: string
  institution: InstitutionBrief
  fdr: {
    id: number
    institution: InstitutionBrief
    bank_name: string
    branch_name: string | null
    ifsc_code: string | null
    fdr_number: string
    amount: string
    issue_date: string
    maturity_date: string
  } | null
  documents: DocumentRead[]
  outcome: OutcomeRead | null
  can_submit_outcome: boolean
}

// ---------- advisory screening (mirrors backend/app/schemas/screening.py) ----------

export type FindingSeverity = 'INFO' | 'WARNING' | 'HIGH'
export type FindingCategory =
  | 'RECORD_VALIDATION'
  | 'DOCUMENT_EXTRACTION'
  | 'DOCUMENT_CONSISTENCY'
  | 'DUPLICATE'
  | 'LIFECYCLE'
export type ReviewPriority = 'HIGH' | 'MEDIUM' | 'LOW'
export type ScreeningDisposition = 'CONCERN_CONFIRMED' | 'NEEDS_FOLLOW_UP' | 'DISMISSED_NOT_AN_ISSUE'

export interface ScreeningReviewRead {
  id: number
  finding_id: number
  run_number: number
  disposition: ScreeningDisposition
  notes: string
  reviewer: UserBrief
  reviewed_at: string
}

export interface FindingRead {
  id: number
  code: string
  rule_version: string
  category: FindingCategory
  severity: FindingSeverity
  title: string
  description: string
  reason: string
  field: string | null
  observed: Record<string, unknown> | null
  document_id: number | null
  related_fdr_id: number | null
  match_type: string | null
  fingerprint: string
  reviews: ScreeningReviewRead[]
  earlier_reviews: ScreeningReviewRead[]
}

export interface ExtractedFieldRead {
  field: string
  value: string
  raw: string
  page: number
}

export interface ExtractionSummary {
  document_id: number
  document_name: string
  document_type: DocumentType
  sha256: string
  status: string
  method: string | null
  pages_read: number
  fields: ExtractedFieldRead[]
  note: string | null
}

export interface RunSummary {
  id: number
  run_number: number
  status: 'COMPLETED' | 'FAILED'
  engine_version: string
  started_at: string
  completed_at: string
  triggered_by: UserBrief
  review_priority: ReviewPriority | null
  high_count: number
  warning_count: number
  info_count: number
  fdr_version: number
  error_code: string | null
}

export interface RunDetail extends RunSummary {
  findings: FindingRead[]
  extraction: ExtractionSummary[]
  no_longer_raised: {
    code: string
    title: string
    severity: FindingSeverity
    fingerprint: string
    previous_run_number: number
    reviewed_by_human: boolean
  }[]
  is_latest: boolean
  is_stale: boolean
}

export interface ScreeningOverview {
  fdr_id: number
  advisory_notice: string
  priority_explanation: string
  latest: RunDetail | null
  runs: RunSummary[]
}

export interface ScreeningQueueItem {
  fdr_id: number
  fdr_number: string
  bank_name: string
  institution: InstitutionBrief
  fdr_status: FdrStatus
  run_id: number
  run_number: number
  run_status: 'COMPLETED' | 'FAILED'
  completed_at: string
  review_priority: ReviewPriority | null
  high_count: number
  warning_count: number
  info_count: number
  unreviewed_high: number
  unreviewed_warning: number
  is_stale: boolean
}

// ---------- lifecycle, notifications, dashboard (mirrors backend/app/schemas/lifecycle.py) ----------

export type LifecycleStatus = 'ACTIVE' | 'PROPOSED' | 'RENEWED' | 'REPLACED' | 'RELEASED' | 'CANCELLED'
export type LifecycleRequestType = 'RENEWAL' | 'REPLACEMENT' | 'RELEASE'
export type LifecycleRequestStatus =
  | 'SUBMITTED'
  | 'UNDER_REVIEW'
  | 'CLARIFICATION_REQUESTED'
  | 'APPROVED'
  | 'REJECTED'
  | 'WITHDRAWN'
  | 'COMPLETED'
export type LifecycleAction = 'START_REVIEW' | 'REQUEST_CLARIFICATION' | 'APPROVE' | 'REJECT' | 'COMPLETE' | 'RESPOND' | 'WITHDRAW'

export interface FdrBrief {
  id: number
  fdr_number: string
  bank_name: string
  amount: string
  issue_date: string
  maturity_date: string
  status: FdrStatus
  lifecycle_status: LifecycleStatus
}

export interface LifecycleRequestRead {
  id: number
  request_type: LifecycleRequestType
  status: LifecycleRequestStatus
  institution: InstitutionBrief
  fdr: FdrBrief
  successor: FdrBrief | null
  reason: string
  supporting_note: string | null
  created_by_name: string
  created_at: string
  updated_at: string
  decided_at: string | null
  completed_at: string | null
  completion_reference: string | null
  version: number
}

export interface LifecycleEventRead {
  id: number
  action: string
  from_status: LifecycleRequestStatus | null
  to_status: LifecycleRequestStatus
  actor_name: string
  actor_role: Role
  message: string | null
  internal_note: string | null
  created_at: string
}

export interface LifecycleRequestDetail extends LifecycleRequestRead {
  events: LifecycleEventRead[]
  allowed_actions: LifecycleAction[]
  completion_blockers: string[]
}

export interface FdrLifecycle {
  fdr_id: number
  fdr_version: number
  lifecycle_status: LifecycleStatus
  maturity_date: string
  days_to_maturity: number
  eligibility: Record<LifecycleRequestType, { allowed: boolean; reasons: string[] }>
  requests: LifecycleRequestRead[]
  proposed_by_request: LifecycleRequestRead | null
  rules: Record<string, number | boolean>
}

export interface MaturityItem {
  fdr_id: number
  fdr_number: string
  bank_name: string
  institution: InstitutionBrief
  status: FdrStatus
  lifecycle_status: LifecycleStatus
  maturity_date: string
  days_remaining: number
  state: 'MATURED' | 'DUE' | 'NOT_DUE'
  alert_window: number | null
  open_request_type: LifecycleRequestType | null
}

export interface LifecycleCheckResult {
  checked: number
  due: number
  matured: number
  skipped: number
  notifications_created: number
  date: string
}

export interface NotificationRead {
  id: number
  event_type: string
  title: string
  body: string
  link: string | null
  fdr_id: number | null
  created_at: string
  read_at: string | null
}

export interface DashboardSummary {
  role: Role
  as_of: string
  fdr_by_status: Record<string, number> | null
  fdr_by_lifecycle: Record<string, number> | null
  maturing_within_30_days: number | null
  overdue_active: number | null
  clarifications_requiring_action: number | null
  lifecycle_requests_open: Record<string, number> | null
  lifecycle_requests_awaiting_decision: Record<string, number> | null
  lifecycle_requests_awaiting_completion: number | null
  verification_active: number | null
  verification_outcomes_awaiting_decision: number | null
  screening_unreviewed_high: number | null
  screening_unreviewed_warning: number | null
  cases_awaiting_action: number | null
  cases_completed: number | null
  cases_closed_other: number | null
  unread_notifications: number
}

/** GET /verification/awaiting-decision (AICTE only). Mirrors AwaitingDecisionItem. */
export interface AwaitingDecisionItem {
  fdr_id: number
  fdr_number: string
  bank_name: string
  institution: InstitutionBrief
  fdr_status: FdrStatus
  lifecycle_status: LifecycleStatus
  outcome_id: number
  outcome: OutcomeType
  outcome_submitted_at: string
  officer: UserBrief
  assignment_id: number
}

/** GET /reports/summary (AICTE only). Mirrors backend/app/schemas/reports.py. */
export interface ReportSummary {
  as_of: string
  generated_at: string
  scope_note: string
  fdr_total: number
  fdr_by_status: Record<string, number>
  fdr_by_lifecycle: Record<string, number>
  lifecycle_requests: { request_type: LifecycleRequestType; status: LifecycleRequestStatus; count: number }[]
  monitored_total: number
  maturity: { bucket: string; label: string; count: number; total_amount: string }[]
  institutions: {
    institution: InstitutionBrief
    total_fdrs: number
    by_status: Record<string, number>
    active_instruments: number
    active_amount: string
    maturing_within_30_days: number
    overdue_active: number
    open_lifecycle_requests: number
  }[]
}
