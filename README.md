# NidhiSec

**AICTE Security Deposit / FDR Management Portal** — Smart India Hackathon (SIH) prototype.

NidhiSec helps AICTE and authorised stakeholders manage the lifecycle of security deposits held as Fixed Deposit Receipts (FDRs). The system serves three stakeholder portals:

1. **Institution / College** — submit FDRs, track review status, correct records, request release.
2. **Bank Officer** — confirm the authenticity and status of FDRs assigned for verification.
3. **AICTE Official** — search and review records, resolve possible duplicates, approve releases, monitor compliance.

## Current status

| Area | Status |
| --- | --- |
| Application shell, dashboard, live backend health status | Implemented |
| Sign-in with Argon2id-hashed passwords and signed, expiring tokens | Implemented |
| Role-based access control (INSTITUTION, BANK_OFFICER, AICTE_OFFICIAL), enforced by the API | Implemented |
| FDR records: submit, list (search, filters, pagination), detail, correct, AICTE review status | Implemented |
| Possible-duplicate detection (normalised bank + FDR reference), flagged for review | Implemented |
| Append-only audit log (sign-ins, record creation, edits, status changes, duplicate flags, document events) | Implemented |
| Supporting documents: upload (PDF/PNG/JPEG, content-checked), list, download, withdraw, SHA-256 integrity checks | Implemented |
| Bank verification workflow: AICTE assigns/reassigns cases, bank officers record outcomes, AICTE records separate review decisions | Implemented (manual officer attestation; no bank-system integration) |
| Advisory screening (AICTE): explainable rules, PDF text-layer field extraction, cross-institution duplicate / reuse detection, human review history | Implemented — advisory only; never rejects, accepts or verifies |
| OCR, machine-learning models, automated verification | **Not implemented** (no external AI services are used) |
| Maturity tracking and alerts (configurable windows, de-duplicated) | Implemented |
| Renewal, replacement and release/refund requests with AICTE review and explicit completion | Implemented (prototype rules; no payment integration) |
| Notification centre (bell, list, read state) and role-scoped dashboard counts | Implemented |
| Reports | **Not implemented** (placeholder page) |
| User administration UI | **Not implemented** (use the CLI commands below) |

> No record status, document hash or bank officer outcome is independent proof that an FDR is genuine. A bank officer's outcome is their own recorded attestation; NidhiSec has no connection to bank systems and does not simulate one. Submitting an FDR stores what the institution entered; AICTE review statuses record review steps only. Bank verification is a later module.

> This is a development prototype. Use only fictional data.

## Technology stack

| Layer | Technology |
| --- | --- |
| Frontend | React 19, Vite 6, TypeScript 5.8, Tailwind CSS 4, React Router 7, lucide-react icons |
| Backend | Python 3.13, FastAPI, Uvicorn, Pydantic / Pydantic Settings |
| Database | SQLite via SQLAlchemy 2.0, schema managed with Alembic |
| Security | pwdlib (Argon2id) for password hashing, PyJWT (HS256) for access tokens |
| API | REST (JSON), OpenAPI docs at `/api/docs` |

## Folder structure

```
NIDHISEC/
├── README.md
├── .gitignore
├── backend/
│   ├── requirements.txt / requirements-dev.txt
│   ├── .env.example              # copy via `python -m app.cli init-env`
│   ├── alembic.ini
│   ├── migrations/               # Alembic environment and versions/
│   ├── data/                     # SQLite DB + dev credentials file (git-ignored)
│   ├── storage/documents/        # uploaded files under random names (git-ignored, private)
│   ├── app/
│   │   ├── main.py               # FastAPI app, CORS, security headers, error handlers
│   │   ├── cli.py                # init-env, seed-demo, create-institution, create-user
│   │   ├── core/config.py        # settings (NIDHISEC_* env vars)
│   │   ├── core/security.py      # password hashing, token creation/validation
│   │   ├── core/login_throttle.py
│   │   ├── core/upload_limit.py  # rejects oversized uploads before parsing
│   │   ├── db/                   # Base, naming conventions, UTC datetime type, session
│   │   ├── models/               # Institution, User, FDR, FDRDocument, AuditLog
│   │   ├── schemas/              # Pydantic request/response models and validation rules
│   │   ├── services/             # FDR + document access rules, duplicate detection, audit,
│   │   │                         # file validation, private document storage
│   │   └── api/
│   │       ├── deps.py           # current user, role checks
│   │       └── routes/           # health, auth, fdrs, documents, verification, screening, lifecycle,
│   │                             # notifications, dashboard, institutions, audit_logs
│   └── tests/                    # pytest suite (uses a throwaway database)
└── frontend/
    └── src/
        ├── auth/                 # AuthContext (session), route guards
        ├── lib/api.ts            # fetch wrapper: token, timeouts, 401 handling, 422 field errors
        ├── lib/format.ts         # INR/date formatting, status labels
        ├── hooks/                # useApiQuery, useBackendHealth
        ├── components/           # layout, ui primitives, FDR form, documents panel, backend status
        ├── navigation.ts         # modules, implemented flag, role visibility
        └── pages/                # Login, Dashboard, fdrs/*, verification/*, lifecycle/*, ScreeningQueue,
                                  # Notifications, AuditLog, placeholders
```

## Prerequisites (Windows 11)

- **Python 3.11+** (developed with 3.13) — `py --version`
- **Node.js 20.19+ or 22.12+** (developed with Node 24) — `node -v`
- VS Code (recommended)

## Installation (one time)

Open the `NIDHISEC` folder in VS Code and open a PowerShell terminal (**Terminal → New Terminal**).

### Backend

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt

python -m app.cli init-env        # creates backend\.env with a random JWT secret
alembic upgrade head              # creates / upgrades the database schema
python -m app.cli seed-demo       # DEVELOPMENT ONLY: fictional demo accounts + FDRs
```

If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once and retry.

`seed-demo` prints the generated passwords once and saves them to `backend\data\dev-credentials.txt` (git-ignored). Running it again changes nothing; `python -m app.cli seed-demo --reset-passwords` generates new passwords. It refuses to run unless `NIDHISEC_ENVIRONMENT=development`.

Demo accounts (all fictional):

| Role | Email |
| --- | --- |
| INSTITUTION (Demo Institute of Technology, DEMO-INST-001) | `institution1@demo-institute.example.org` |
| INSTITUTION (Sample College of Engineering, DEMO-INST-002) | `institution2@sample-college.example.org` |
| BANK_OFFICER | `bank.officer@demo-bank.example.org` |
| BANK_OFFICER (second officer, for reassignment/isolation demos) | `bank.officer2@demo-bank.example.org` |
| AICTE_OFFICIAL | `aicte.official@aicte-demo.example.org` |

The seed also creates four fictional FDRs, including one cross-institution pair (`DNB/FD/000123` and `dnb-fd-000123`) that demonstrates possible-duplicate flagging.

### Frontend

```powershell
cd frontend
npm install
```

## Running the application

Use **two separate VS Code terminals**.

**Terminal 1 — backend:**

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — frontend:**

```powershell
cd frontend
npm run dev
```

| What | URL |
| --- | --- |
| NidhiSec web app | http://localhost:5173 |
| API health check | http://localhost:8000/api/health |
| API docs (Swagger UI) | http://localhost:8000/api/docs — use **Authorize** with an email in the *username* field |
| API docs (ReDoc) | http://localhost:8000/api/redoc |

## Roles and permissions (enforced by the API)

| Action | INSTITUTION | AICTE_OFFICIAL | BANK_OFFICER |
| --- | --- | --- | --- |
| List / view FDRs (general API) | Own institution only | All institutions | Denied (403); uses verification cases instead |
| Submit FDR | Yes, always for own institution | No | No |
| Correct FDR details | Own records, while Submitted or Clarification requested | No | No |
| Change review status | No | Yes (Under review, Clarification requested, Rejected) | No |
| See possible-duplicate details | Matches within own institution; other institutions' matches are counted, not shown | Full details | — |
| Record history | Own records | All records | — |
| Audit log | No | Yes | No |
| List / download documents | Own records | All records | Only for an FDR currently assigned to them |
| Upload documents | Own records, unless Rejected | No | No |
| Withdraw a document (with reason) | Own records, while Submitted or Clarification requested | No | No |
| Re-check stored-file integrity | No | Yes | No |
| Assign / reassign verification | No | Yes | No |
| View verification cases | No | All, with full history | Own cases only (details and documents only while active) |
| Record a verification outcome | No | No | Own active case, once |
| Accept a record | No | Yes, only after a confirmed bank outcome | No |
| Advisory screening (run, view, review findings, queue) | No | Yes | No |
| Request renewal / replacement / release | Own accepted, active FDRs | No | No |
| Review, decide and record completion of lifecycle requests | No | Yes | No |
| Respond to clarification / withdraw a lifecycle request | Own requests | No | No |
| Maturity list | Own FDRs | All | No (refused and audited) |
| Notifications | Own only | Own only | Own only |
| See verification progress | Coarse state only (not started / in progress / completed) | Everything incl. internal notes | Own outcomes |

Records outside a user's scope return **404**, so their existence is not disclosed. Unauthenticated requests get **401**; a disallowed role gets **403**.

## API overview

| Method & path | Purpose |
| --- | --- |
| `POST /api/auth/login` | Email + password → bearer token (default lifetime 60 min) |
| `POST /api/auth/token` | Same, as an OAuth2 form (Swagger "Authorize") |
| `GET /api/auth/me` | Current user |
| `GET /api/fdrs` | List: `page`, `page_size` (≤100), `q`, `status` (repeatable), `institution_id` (AICTE), `maturity_from`, `maturity_to`, `duplicates_only`, `sort` |
| `GET /api/fdrs/summary` | Dashboard counts within the user's scope |
| `POST /api/fdrs` | Submit an FDR (institution) |
| `GET /api/fdrs/{id}` | Detail incl. duplicate review and permitted actions |
| `PATCH /api/fdrs/{id}` | Correct fields; requires the current `version` (409 if stale) |
| `POST /api/fdrs/{id}/review` | AICTE review status change; requires `version` |
| `GET /api/fdrs/{id}/history` | Audit trail for one record |
| `GET /api/fdrs/{id}/documents` | Documents, upload policy and permitted actions |
| `POST /api/fdrs/{id}/documents` | Upload (multipart: `file`, `document_type` = FDR_COPY / BANK_LETTER / OTHER) |
| `GET /api/fdrs/{id}/documents/{doc}` | Document metadata |
| `GET /api/fdrs/{id}/documents/{doc}/download` | Permission- and integrity-checked download (audited) |
| `POST /api/fdrs/{id}/documents/{doc}/withdraw` | Withdraw with a `reason`; file and record are kept |
| `POST /api/fdrs/{id}/documents/{doc}/integrity-check` | AICTE: re-hash the stored file and compare |
| `GET /api/verification/officers` | AICTE: active bank officers |
| `POST /api/fdrs/{id}/verification/assignments` | AICTE: assign (`bank_officer_id`, `fdr_version`, optional `note`) |
| `POST /api/verification/assignments/{a}/reassign` | AICTE: reassign (`bank_officer_id`, `version`, `reason`) |
| `GET /api/verification/assignments` | AICTE: queue, filter by `status`, `bank_officer_id` |
| `GET /api/fdrs/{id}/verification` | AICTE: assignments, outcomes and review decisions for one FDR |
| `GET /api/verification/cases` | Bank officer: own cases (`state` = active / closed / all) |
| `GET /api/verification/cases/{a}` | Bank officer: restricted case view |
| `POST /api/verification/cases/{a}/outcome` | Bank officer: `outcome`, `notes` (≥ 20 chars), optional `bank_reference`, `evidence_document_ids`, `version` |
| `POST /api/fdrs/{id}/screening/runs` | AICTE: run screening now (earlier runs kept) |
| `GET /api/fdrs/{id}/screening` | AICTE: latest run with findings, plus all earlier runs |
| `GET /api/fdrs/{id}/screening/runs/{run}` | AICTE: one specific run |
| `POST /api/fdrs/{id}/screening/findings/{f}/reviews` | AICTE: record `disposition` + `notes` on a latest-run finding |
| `GET /api/screening/queue` | AICTE: latest run per screened FDR, highest priority first (`priority` filter) |
| `GET /api/fdrs/{id}/lifecycle` | Lifecycle status, eligibility (with reasons), related requests |
| `POST /api/fdrs/{id}/lifecycle-requests` | Institution: `request_type`, `fdr_version`, `reason`, optional `supporting_note`, `successor` (renewal/replacement) |
| `GET /api/lifecycle-requests` | List (`type`, `status` filters; institutions see their own) |
| `GET /api/lifecycle-requests/{r}` | Detail with append-only history and the caller's allowed actions |
| `POST /api/lifecycle-requests/{r}/transitions` | `action`, `version`, `message`, `internal_note` (AICTE), `completion_reference` (COMPLETE) |
| `GET /api/lifecycle/maturity` | Matured / due-soon active instruments (`within_days`, `include_overdue`) |
| `POST /api/lifecycle/check` | AICTE: run the maturity check now (idempotent) |
| `GET /api/notifications`, `GET /api/notifications/unread-count` | Own notifications |
| `POST /api/notifications/{n}/read`, `POST /api/notifications/read-all` | Mark own notifications read |
| `GET /api/dashboard/summary` | Role-scoped counts |
| `GET /api/institutions` | AICTE: all; institution: own |
| `GET /api/audit-logs` | AICTE only; filters `action`, `entity_type`, `entity_id`, `actor_email`, `date_from`, `date_to` |

### Validation rules

- Amount: greater than 0, at most 2 decimal places, at most ₹1,000 crore. Stored as integer paise.
- Issue date not in the future (Indian Standard Time). Maturity date after issue date, tenure at most 10 years.
- Bank name, FDR number, branch, IFSC: length limits and character allow-lists. IFSC format `ABCD0123456`.
- Unknown fields (for example `institution_id` or `status` in a submission) are rejected with 422.

### Possible-duplicate detection

Two records are a possible duplicate when their **normalised FDR reference** matches (case, spaces and separators ignored, zero padding in digit runs ignored) **and** they are at the same bank (normalised name, ignoring "The", "Ltd", "Co-operative" and similar words, or the same IFSC bank code). Matching records are both saved and flagged; nothing is overwritten, blocked or labelled fraudulent. The flag is recomputed on every read, so it stays accurate after edits.

## Document management

- **Accepted types:** PDF, PNG and JPEG, decided from the file's content. The extension must match the detected type; the browser-supplied MIME type is ignored. Size limit: `NIDHISEC_MAX_UPLOAD_BYTES` (default 10 MB). Oversized requests are refused from their `Content-Length` before the body is parsed.
- **Rejected:** empty files; unknown or mismatched signatures; truncated or corrupt files (PNG chunk checksums, JPEG frame structure, PDF end marker); images over 20,000 px per side or 100 megapixels; encrypted PDFs; PDFs with JavaScript, launch actions, embedded files, XFA or similar active content; files containing HTML/script markup. Rejections are audited.
- **Storage:** files are written atomically under `backend/storage/documents/` with random 128-bit names. Client filenames are sanitised and kept only as display text. No URL serves files directly; downloads go through the permission-checked endpoint with `Content-Disposition: attachment`, `nosniff` and a sandboxing Content-Security-Policy.
- **Consistency:** if the database step fails after the file is written, the file is deleted; a failed write leaves no partial file.
- **Integrity:** the SHA-256 recorded at upload is re-checked on every download. A mismatched or missing file blocks the download and writes a `DOCUMENT_INTEGRITY_FAILED` audit entry. AICTE officials can re-check on demand. A matching hash shows the stored file is unchanged since upload; it does **not** show that the document is genuine.
- **Evidence protection:** documents cannot be replaced or deleted. A document attached by mistake is *withdrawn* with a reason; it stays listed and downloadable. Database triggers block changes to a document's file fields, reversal of a withdrawal and deletion of document rows. The same file cannot be attached twice to one record.
- **Audit:** uploads, rejected uploads, downloads, withdrawals and integrity checks are logged with actor, FDR, document id, hash and time, and appear in the record history.

## Bank verification workflow

1. **Assign (AICTE).** From an FDR's record page, an AICTE official assigns a Submitted or Under-review record to an active bank officer, optionally with instructions. A Submitted record moves to Under review, which also freezes the institution's edits while the bank checks it. At most one assignment per FDR can be active; a database partial unique index enforces this even under concurrent requests.
2. **Reassign (AICTE).** An active case can move to a different officer with a reason (at least 10 characters). The old assignment is kept as *Reassigned* with who, when and why; the previous officer loses access immediately.
3. **Check and record (bank officer).** Officers see only their own cases. While a case is active they see the FDR details needed for checking (institution, bank, branch, IFSC, reference, amount, dates) and its documents. They do not see duplicate matches, AICTE notes, institution remarks or the record history. They record one outcome: *Confirmed against authorised bank records*, *Details mismatch*, *Additional information required* or *Unable to verify*, with notes, an optional bank reference and the documents relied on. Recording an outcome closes the case.
4. **Decide (AICTE).** AICTE review decisions are stored separately from bank outcomes, with a message to the institution and optional internal notes. *Accepted* is possible only when the latest bank outcome is a confirmation and no case is open. Requesting clarification or rejecting closes any open assignment as *Cancelled*; after the institution corrects the record, AICTE can assign it again. Every round stays in the history.

**What institutions see:** status, AICTE's message and a coarse verification state. They never see which officer handled the case, the outcome, officer notes, AICTE instructions or internal notes; these are also filtered out of their record history.

**Integrity:** assignments, outcomes and decisions cannot be deleted; outcomes and decisions cannot be edited; a closed assignment cannot be changed; an assignment's officer and FDR cannot be swapped (database triggers). Stale `version` values are rejected with 409. Bank officer attempts to reach records or cases outside their assignments get 403/404 without revealing whether the record exists, and are audited as `VERIFICATION_ACCESS_DENIED`.

## Advisory screening (AICTE only)

Screening helps AICTE officials decide which records to look at first. **It is advisory only**: it never changes an FDR, its documents, its verification assignments or its status, and it cannot reject, accept or verify anything. A duplicate match is a prompt for review, not proof of fraud.

**Running it.** On an FDR's page, *Advisory screening → Run screening*. Every run is stored with its number, time, who ran it and the engine version (`screening/1.0+pdf-text/1.0`). Re-running never overwrites earlier runs. If the record or its documents change afterwards, the run is marked *out of date*.

**Findings.** Each finding has a stable code, a category, a severity (informational / warning / high priority), a title, a description, the reason it was raised, the field compared, and the observed values (record value, document value with page and source snippet, or both records side by side for duplicates).

| Category | Examples (codes) |
| --- | --- |
| Record check | `REC_DATE_ORDER_INVALID`, `REC_ISSUE_DATE_FUTURE`, `REC_TENURE_TOO_LONG`, `REC_AMOUNT_OUT_OF_RANGE`, `REC_IFSC_FORMAT_INVALID`, `REC_OPTIONAL_FIELDS_MISSING` |
| Document reading | `DOC_NONE_ATTACHED`, `DOC_NO_FDR_COPY`, `DOC_NO_TEXT_LAYER`, `DOC_EXTRACTION_UNSUPPORTED`, `DOC_EXTRACTION_FAILED`, `DOC_KEY_FIELDS_NOT_FOUND`, `DOC_INTEGRITY_FAILED` |
| Record vs document | `DOC_FDR_NUMBER_MISMATCH`, `DOC_AMOUNT_MISMATCH`, `DOC_ISSUE_DATE_MISMATCH`, `DOC_MATURITY_DATE_MISMATCH`, `DOC_IFSC_MISMATCH`, `DOC_BANK_NAME_MISMATCH`, `DOC_DATE_ORDER_INVALID`, `DOC_HOLDER_NOT_INSTITUTION`, `DOC_AMBIGUOUS_VALUES` |
| Duplicate / reuse | `DUP_EXACT_OTHER_INSTITUTION`, `DUP_POSSIBLE_OTHER_INSTITUTION`, `DUP_EXACT_SAME_INSTITUTION`, `DUP_POSSIBLE_SAME_INSTITUTION`, `DUP_NEAR_REFERENCE`, `DUP_SAME_DOCUMENT_FILE` |
| Maturity (not an integrity concern) | `LIFE_MATURED`, `LIFE_MATURING_SOON` |

**Review priority** (no numeric score and not a probability of fraud): HIGH if any high-priority finding; otherwise MEDIUM if any warning; otherwise LOW. Maturity findings never raise the priority.

**Duplicates.**
- *Exact duplicate*: same normalised FDR reference and same bank (normalised name or IFSC bank code), **and** the same amount, issue date and maturity date.
- *Possible match*: same normalised reference and same bank, but amount and/or dates differ; the differing fields are listed.
- *Near-identical reference*: references differ by one character, at the same bank, with the same amount.
- *Identical document file*: the same file (SHA-256) is attached to another record.
- Similar amounts alone are never treated as a match. Cross-institution matches are high priority; same-institution matches are warnings.

**Document extraction.** Local only (pypdf), reading a PDF's embedded text layer. Values are taken only from clearly labelled lines (e.g. "FDR No:", "Deposit Amount:", "Date of Issue:", "Maturity Date:", "IFSC", "Name of Depositor:"), dates are read day-first, and "maturity amount"/"interest" lines are ignored for the deposit amount. The stored file's SHA-256 is verified before reading; files are only read, never modified or copied. Only matched snippets (≤120 characters) are stored, never the full text. Limitations: no OCR (images and scanned PDFs are reported for manual review), at most 20 pages, unusual layouts or unlabelled values are not found, and extracted values do not prove a document is genuine.

**Human review.** AICTE officials record a disposition (*Concern confirmed*, *Needs follow-up*, *Reviewed — not an issue*) with notes on findings of the latest run. Reviews are append-only. A rerun does not carry reviews over automatically: earlier reviews of the same finding are shown as context, and findings that disappear in a new run are listed as *not raised in this run*, explicitly not a human decision.

**Access.** Only AICTE officials can reach any screening endpoint or screen. Institutions and bank officers (including an officer assigned to the case) get 403, which is audited as `SCREENING_ACCESS_DENIED`; screening entries are also filtered out of the institution's record history. Runs, failures and reviews are audited (`SCREENING_RUN_COMPLETED`, `SCREENING_RUN_FAILED`, `SCREENING_FINDING_REVIEWED`). Runs, findings and reviews cannot be edited or deleted (database triggers). An engine error is stored as a *failed* run with a generic code; nothing else changes and the run can be retried.

## FDR lifecycle (prototype rules)

Lifecycle status is separate from AICTE review status: **Active** (the instrument in force), **Proposed** (a new instrument submitted with a renewal/replacement request), **Renewed** / **Replaced** (superseded, kept as history), **Released** (release completion recorded), **Cancelled** (a proposed instrument whose request was rejected or withdrawn). Superseded, released and cancelled records can no longer be edited, reviewed, verified or receive documents, but all their documents, verification, screening and audit history remain.

**Dates.** All "today" comparisons use the Indian Standard Time calendar date, as in the submission rules.

**Maturity alerts.** Alert windows are `NIDHISEC_MATURITY_ALERT_DAYS` (default `30,15,7`). For each active, non-rejected FDR the check finds the smallest window already reached (or "matured" once the date has passed) and notifies the institution's users; AICTE officials are also notified at or below `NIDHISEC_AICTE_MATURITY_ALERT_DAYS` (default 7) and when an FDR has matured. Each alert has the key `maturity:<fdr>:<maturity date>:<window|matured>`, unique per recipient, so repeating the check never duplicates alerts; a new window, a changed maturity date or a new instrument produces new ones. Maturity never changes an FDR; nothing is released or refunded automatically.

Run the check from AICTE's *Renewals & Maturity* page, or on a schedule (no in-process scheduler is used, so development reloads cannot start competing jobs):

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.cli lifecycle-check
```

For example, Windows Task Scheduler can run that daily with *Start in* set to the `backend` folder. In development only, `--date YYYY-MM-DD` evaluates another day for testing.

**Eligibility** (configurable, not official AICTE policy): renewal, replacement and release apply to *Active* FDRs that AICTE has *Accepted*, with no other open request. Renewal opens `NIDHISEC_RENEWAL_WINDOW_DAYS` (default 90) before maturity; replacement has no timing rule; release requires the FDR to have matured unless `NIDHISEC_RELEASE_REQUIRES_MATURITY=false`. Only one open request per FDR is allowed (enforced by a database partial unique index).

**Request statuses and transitions**

| Action | Who | From | To |
| --- | --- | --- | --- |
| Submit | Institution | — | Submitted |
| Start review | AICTE | Submitted | Under review |
| Request clarification (message required) | AICTE | Submitted, Under review | Clarification requested |
| Respond (message required) | Institution | Clarification requested | Submitted |
| Approve | AICTE | Submitted, Under review | Approved |
| Reject (reason required) | AICTE | Submitted, Under review, Clarification requested, Approved | Rejected |
| Withdraw (reason required) | Institution | Submitted, Under review, Clarification requested | Withdrawn |
| Record completion (note required) | AICTE | Approved | Completed |

*Approved* is a decision only. *Completed* is an explicitly recorded administrative action: for a release it sets the FDR to *Released*; for a renewal/replacement it sets the original to *Renewed*/*Replaced* and the new instrument to *Active*, and (with `NIDHISEC_LIFECYCLE_REQUIRE_SUCCESSOR_ACCEPTANCE=true`, the default) only after the new instrument has been verified by a bank officer and accepted by AICTE through the normal workflow. NidhiSec records no payments and has no payment integration; a completion reference is just an administrative note.

For renewal/replacement the new instrument is created at submission as a separate *Proposed* FDR, validated with the normal rules (a renewal must also mature after, and not be issued before, the current one). Its documents are uploaded on its own record. The original FDR is never modified. Rejecting or withdrawing the request cancels the proposed instrument and closes any verification case on it. Every transition is stored in an append-only history with actor, time, the message shown to the institution, and AICTE-only internal notes; closed requests cannot be changed (database triggers).

**Notifications** are created by real events: verification assignment, reassignment and cancellation (bank officers), recorded outcomes (AICTE), AICTE review decisions (institution), lifecycle submissions, responses and withdrawals (AICTE), lifecycle decisions and completion (institution), and maturity checks. Each carries an event key unique per recipient (enforced by the database with `INSERT … ON CONFLICT DO NOTHING`). Text never includes internal notes, screening findings or another institution's details. Users can only list and mark their own notifications; content cannot be edited or deleted.

**Dashboards** use grouped database queries scoped to the role: institutions see their own counts (status, lifecycle, maturing, overdue, open requests, clarifications needing action); bank officers see only their own case counts; AICTE sees portfolio-wide counts including outcomes awaiting a decision, unreviewed screening findings and lifecycle requests awaiting decision or completion.

## Database migrations

The schema is managed by Alembic; the app no longer creates tables on startup.

```powershell
cd backend
alembic upgrade head                                   # apply migrations
alembic revision --autogenerate -m "describe change"   # after changing models; review the file
```

Migrations use batch mode so SQLite table changes are applied without data loss. The test suite checks that the migrations produce exactly the schema the models define. Back up `backend\data\nidhisec.db` before upgrading a database that holds data you care about.

## Creating real accounts

```powershell
python -m app.cli create-institution --code INST-CODE --name "Institution name"
python -m app.cli create-user --email user@example.org --name "Full Name" --role INSTITUTION --institution-code INST-CODE
python -m app.cli create-user --email official@example.org --name "Full Name" --role AICTE_OFFICIAL
```

The password is prompted for (minimum 12 characters) and never passed on the command line.

## Testing

```powershell
# backend (from backend\, venv active) — uses a temporary database, never data\nidhisec.db
python -m pytest -q

# frontend type-check + production build (from frontend\)
npm run build
```

The backend suite covers sign-in success and failure, token expiry and tampering, login throttling, role-based access and institution data isolation, FDR create/retrieve/update, amount and date validation, optimistic-locking conflicts, review transitions, duplicate detection and privacy, audit-log creation and append-only enforcement, migrations, and the health check.

## Configuration

| Variable | Where | Default |
| --- | --- | --- |
| `NIDHISEC_ENVIRONMENT` | `backend\.env` | `development` |
| `NIDHISEC_DATABASE_URL` | `backend\.env` | `sqlite:///./data/nidhisec.db` (relative to `backend\`) |
| `NIDHISEC_CORS_ORIGINS` | `backend\.env` | `http://localhost:5173,http://127.0.0.1:5173` |
| `NIDHISEC_JWT_SECRET` | `backend\.env` | none — required outside development; ≥ 32 characters |
| `NIDHISEC_ACCESS_TOKEN_EXPIRE_MINUTES` | `backend\.env` | `60` |
| `NIDHISEC_MATURITY_ALERT_DAYS` | `backend\.env` | `30,15,7` |
| `NIDHISEC_AICTE_MATURITY_ALERT_DAYS` | `backend\.env` | `7` |
| `NIDHISEC_RENEWAL_WINDOW_DAYS` | `backend\.env` | `90` |
| `NIDHISEC_RELEASE_REQUIRES_MATURITY` | `backend\.env` | `true` |
| `NIDHISEC_LIFECYCLE_REQUIRE_SUCCESSOR_ACCEPTANCE` | `backend\.env` | `true` |
| `VITE_API_BASE_URL` | `frontend\.env.local` | `http://localhost:8000/api` |

If `NIDHISEC_JWT_SECRET` is missing in development, a temporary random key is used and everyone is signed out whenever the server restarts. Outside development the API refuses to start without it.

## Security limitations (known, to address before production)

- **Token storage:** the access token is kept in `sessionStorage`, which scripts on the page can read. Production should use an HttpOnly, Secure, SameSite cookie with CSRF protection.
- **No server-side logout or revocation:** signing out discards the token in the browser; a copied token stays valid until it expires (60 min). Deactivating a user does take effect immediately.
- **Login throttling is in-memory:** it resets on restart and is not shared across worker processes.
- **No password reset, password-change or account-management UI;** accounts are created with the CLI.
- **SQLite** is single-node; the audit log is append-only via database triggers, but anyone with file access to the database can still alter it. Production needs a managed database, backups and stronger tamper evidence.
- **Duplicate flags reveal existence:** an institution learns that its FDR reference matches a record elsewhere (but not whose). This is intended to prompt review.
- **HTTPS** is not configured; the dev servers use plain HTTP.
- **File checks are structural, not antivirus.** Content inside compressed PDF streams is not inspected, so active content hidden in a compressed object stream could pass. The server never executes or renders files and downloads are sandboxed attachments, but production should add malware scanning (for example ClamAV) and PDF sanitisation.
- **Documents are stored unencrypted on local disk.** Production needs encryption at rest, backups and storage access controls. Anyone with filesystem access could read the files; modification is detected by the hash check.
- **Uploads are held in memory** (up to the size limit) while they are validated.
- **Bank verification is a manual attestation.** There is no integration with bank systems; an officer account belongs to whoever holds the credentials. Production needs verified officer onboarding (bank-issued identities), possibly bank-to-bank APIs, and officer-to-bank/branch scoping (currently any officer can be assigned any case).
- **Screening extraction is text-layer only.** No OCR; scanned receipts and images always need manual comparison. Field patterns are tuned to common English labels and may miss other layouts or languages. Holder-name and bank-name comparisons are deliberately loose and only informational/warning.
- **Screening runs on request** (no automatic or scheduled runs) and synchronously; very large PDFs are capped at 20 pages.
- **Lifecycle rules are prototype assumptions**, not AICTE policy; confirm them before use. No payment, refund or bank integration exists; completion is an administrative record.
- **Maturity alerts need the check to run** (button or scheduled CLI). There is no email/SMS delivery; notifications are in-app only.
- **A renewal that keeps the same FDR number** is flagged as a possible duplicate of the original by the existing duplicate rules; reviewers should read the linked request.
- **No separation-of-duties rules** beyond roles: for example, the official who assigns a case can also accept it. A real deployment may require a second reviewer.
- **Bank officers cannot upload their own evidence** (such as a bank letter); they can only cite documents already attached and give a bank reference.

## Troubleshooting

- **"An Application Control policy has blocked this file … rollup.win32-x64-msvc.node"**: Windows Smart App Control / WDAC can block Rollup's native binary. `frontend/package.json` therefore uses `overrides` to install `@rollup/wasm-node`, the official WebAssembly build of Rollup.
- **Dashboard shows "Unavailable"**: confirm the API is on port 8000 and the frontend origin is in `NIDHISEC_CORS_ORIGINS`.
- **API log says "Database schema is not initialised"**: run `alembic upgrade head` in `backend`.
- **Signed out after every backend restart**: run `python -m app.cli init-env` so a persistent JWT secret is used.
- **"Too many failed login attempts"**: wait 15 minutes or restart the backend (development only).
- **Port 5173 already in use**: the dev server uses `strictPort`; close the other process.

## Security notes

- Never commit `.env` files, credentials, database files or uploaded documents; `.gitignore` excludes them, including `backend\data\dev-credentials.txt` and `backend\storage\`.
- Use only fictional demo data. Do not enter real FDRs or institutional financial records.
