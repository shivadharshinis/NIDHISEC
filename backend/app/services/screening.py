"""Explainable, advisory FDR screening.

The engine evaluates one FDR with deterministic rules and returns findings.
It only *reads*: it never changes the FDR, its documents, verification
assignments or review status, and it cannot reject, accept or verify anything.
Findings help AICTE officials decide what to look at first; a person decides.

Review priority (no numeric score, not a probability of fraud):
  HIGH   - at least one HIGH finding
  MEDIUM - otherwise, at least one WARNING finding
  LOW    - only informational findings, or none
Lifecycle findings (maturity timing) are always informational, so they never
raise the priority; they are not integrity concerns.
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import FDR, FDRDocument, FDRStatus, User
from app.models.enums import FindingCategory, FindingSeverity, ReviewPriority, ScreeningRunStatus
from app.models.screening import ScreeningFinding, ScreeningRun
from app.schemas.fdr import IFSC_PATTERN, MAX_AMOUNT, MAX_TENURE_YEARS, today_ist
from app.services import document_storage as storage
from app.services import fdrs as fdr_service
from app.services.audit import AuditAction, record_audit
from app.services.extraction import EXTRACTOR_VERSION, ExtractionResult, extract_document
from app.services.normalization import normalize_bank_name, normalize_fdr_number

logger = logging.getLogger(__name__)

ENGINE_VERSION = "screening/1.0"
RULE_VERSION = "1.0"
MATURING_SOON_DAYS = 90
NEAR_REFERENCE_MIN_LENGTH = 5

ADVISORY_NOTICE = (
    "Screening is advisory. Findings are prompts for human review, not conclusions: they do not reject, "
    "accept or verify an FDR, and a duplicate match is not proof of fraud. Extracted values do not prove "
    "that a document is genuine."
)


@dataclass
class Finding:
    code: str
    category: FindingCategory
    severity: FindingSeverity
    title: str
    description: str
    reason: str
    field: str | None = None
    observed: dict[str, Any] | None = None
    document_id: int | None = None
    related_fdr_id: int | None = None
    match_type: str | None = None

    @property
    def fingerprint(self) -> str:
        return f"{self.code}:{self.field or ''}:{self.document_id or ''}:{self.related_fdr_id or ''}"


@dataclass
class Evaluation:
    findings: list[Finding] = field(default_factory=list)
    extraction: list[dict[str, Any]] = field(default_factory=list)
    documents_fingerprint: str = ""


# ---------- helpers ----------


def _amount(fdr: FDR) -> str:
    return f"{fdr.amount:.2f}"


def _record_summary(fdr: FDR) -> dict[str, Any]:
    return {
        "id": fdr.id,
        "institution": {"id": fdr.institution.id, "code": fdr.institution.code, "name": fdr.institution.name},
        "fdr_number": fdr.fdr_number,
        "bank_name": fdr.bank_name,
        "ifsc_code": fdr.ifsc_code,
        "amount": _amount(fdr),
        "issue_date": fdr.issue_date.isoformat(),
        "maturity_date": fdr.maturity_date.isoformat(),
        "status": fdr.status.value,
    }


def _same_bank(a: FDR, b: FDR) -> bool:
    if a.bank_name_normalized == b.bank_name_normalized:
        return True
    return bool(a.ifsc_code and b.ifsc_code and a.ifsc_code[:4] == b.ifsc_code[:4])


def _edit_distance_at_most_one(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(long_)):
        if long_[:i] + long_[i + 1:] == short:
            return True
    return False


def _bank_names_agree(record: str, extracted: str) -> bool:
    record_tokens = set(normalize_bank_name(record).split())
    extracted_tokens = set(normalize_bank_name(extracted).split())
    if not record_tokens or not extracted_tokens:
        return False
    return record_tokens <= extracted_tokens or extracted_tokens <= record_tokens


_HOLDER_STOPWORDS = {"OF", "THE", "AND", "FOR", "INSTITUTE", "COLLEGE", "TECHNOLOGY", "ENGINEERING", "UNIVERSITY"}


def _holder_names_institution(holder: str, fdr: FDR) -> bool:
    text = holder.upper()
    if fdr.institution.code.upper() in text:
        return True
    tokens = [t for t in normalize_bank_name(fdr.institution.name).split() if len(t) > 3 and t not in _HOLDER_STOPWORDS]
    if not tokens:
        return True  # nothing distinctive to compare
    present = sum(token in text for token in tokens)
    return present / len(tokens) >= 0.5


def _documents_fingerprint(documents: list[FDRDocument]) -> str:
    payload = sorted((d.id, d.sha256, d.withdrawn_at is not None) for d in documents)
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


# ---------- rules: the record itself ----------


def record_rules(fdr: FDR) -> list[Finding]:
    findings: list[Finding] = []
    today = today_ist()
    if fdr.maturity_date <= fdr.issue_date:
        findings.append(Finding(
            "REC_DATE_ORDER_INVALID", FindingCategory.RECORD_VALIDATION, FindingSeverity.HIGH,
            "Maturity date is not after the issue date",
            "The record's maturity date is on or before its issue date.",
            "An FDR must mature after it is issued; this conflicts with the submission rules.",
            field="maturity_date",
            observed={"issue_date": fdr.issue_date.isoformat(), "maturity_date": fdr.maturity_date.isoformat()},
        ))
    if fdr.issue_date > today:
        findings.append(Finding(
            "REC_ISSUE_DATE_FUTURE", FindingCategory.RECORD_VALIDATION, FindingSeverity.HIGH,
            "Issue date is in the future",
            "The record's issue date is later than today.",
            "A deposit cannot have been issued on a future date.",
            field="issue_date", observed={"issue_date": fdr.issue_date.isoformat(), "today": today.isoformat()},
        ))
    try:
        limit = fdr.issue_date.replace(year=fdr.issue_date.year + MAX_TENURE_YEARS)
    except ValueError:
        limit = fdr.issue_date.replace(year=fdr.issue_date.year + MAX_TENURE_YEARS, day=28)
    if fdr.maturity_date > limit:
        findings.append(Finding(
            "REC_TENURE_TOO_LONG", FindingCategory.RECORD_VALIDATION, FindingSeverity.WARNING,
            f"Tenure exceeds {MAX_TENURE_YEARS} years",
            "The period between issue and maturity is longer than the submission rules allow.",
            f"Submission rules limit FDR tenure to {MAX_TENURE_YEARS} years.",
            field="maturity_date",
            observed={"issue_date": fdr.issue_date.isoformat(), "maturity_date": fdr.maturity_date.isoformat()},
        ))
    if not (0 < fdr.amount <= MAX_AMOUNT):
        findings.append(Finding(
            "REC_AMOUNT_OUT_OF_RANGE", FindingCategory.RECORD_VALIDATION, FindingSeverity.HIGH,
            "Amount is outside the permitted range",
            "The deposit amount is not positive or exceeds the permitted maximum.",
            "Amounts must be greater than zero and at most the configured ceiling.",
            field="amount", observed={"amount": _amount(fdr)},
        ))
    if fdr.ifsc_code and not re.fullmatch(IFSC_PATTERN, fdr.ifsc_code):
        findings.append(Finding(
            "REC_IFSC_FORMAT_INVALID", FindingCategory.RECORD_VALIDATION, FindingSeverity.WARNING,
            "IFSC is not in the standard format",
            "The branch IFSC does not have the 11-character format (4 letters, 0, 6 letters or digits).",
            "A malformed IFSC cannot identify the issuing branch.",
            field="ifsc_code", observed={"ifsc_code": fdr.ifsc_code},
        ))
    missing = [name for name in ("branch_name", "ifsc_code") if not getattr(fdr, name)]
    if missing:
        findings.append(Finding(
            "REC_OPTIONAL_FIELDS_MISSING", FindingCategory.RECORD_VALIDATION, FindingSeverity.INFO,
            "Branch details not provided",
            f"The record does not include: {', '.join(missing)}.",
            "Branch name and IFSC are optional, but they help bank verification and duplicate detection.",
            field=",".join(missing),
        ))
    return findings


def lifecycle_rules(fdr: FDR) -> list[Finding]:
    if fdr.status == FDRStatus.REJECTED:
        return []
    today = today_ist()
    observed = {"maturity_date": fdr.maturity_date.isoformat(), "today": today.isoformat()}
    if fdr.maturity_date < today:
        return [Finding(
            "LIFE_MATURED", FindingCategory.LIFECYCLE, FindingSeverity.INFO,
            "FDR has passed its maturity date",
            "The deposit matured before today.",
            "A matured FDR may need renewal or replacement to keep the security deposit in place. "
            "This is a lifecycle matter, not an integrity concern.",
            field="maturity_date", observed=observed,
        )]
    if fdr.maturity_date <= today + timedelta(days=MATURING_SOON_DAYS):
        return [Finding(
            "LIFE_MATURING_SOON", FindingCategory.LIFECYCLE, FindingSeverity.INFO,
            f"FDR matures within {MATURING_SOON_DAYS} days",
            "The deposit's maturity date is approaching.",
            "Renewal may be needed soon. This is a lifecycle matter, not an integrity concern.",
            field="maturity_date", observed=observed,
        )]
    return []


# ---------- rules: documents ----------


def _consistency_findings(fdr: FDR, document: FDRDocument, result: ExtractionResult) -> list[Finding]:
    findings: list[Finding] = []
    doc_ref = {"document_id": document.id, "document_name": document.original_filename,
               "document_type": document.document_type.value}

    def compare(field_name: str, record_value: str | None, matches, code: str, severity: FindingSeverity,
                title: str, reason: str) -> None:
        candidates = result.values(field_name)
        if not candidates or record_value is None:
            return
        if any(matches(record_value, c.value) for c in candidates):
            if len({c.value for c in candidates}) > 1:
                findings.append(Finding(
                    "DOC_AMBIGUOUS_VALUES", FindingCategory.DOCUMENT_CONSISTENCY, FindingSeverity.INFO,
                    f"Several different values found for {field_name.replace('_', ' ')}",
                    "The document contains more than one candidate value; one of them matches the record.",
                    "Multiple labelled values make automatic comparison less reliable.",
                    field=field_name, document_id=document.id,
                    observed={**doc_ref, "record": record_value,
                              "document_values": [{"value": c.value, "snippet": c.raw, "page": c.page} for c in candidates]},
                ))
            return
        findings.append(Finding(
            code, FindingCategory.DOCUMENT_CONSISTENCY, severity, title,
            f"The value read from “{document.original_filename}” differs from the submitted record.",
            reason, field=field_name, document_id=document.id,
            observed={**doc_ref, "record": record_value,
                      "document_values": [{"value": c.value, "snippet": c.raw, "page": c.page} for c in candidates]},
        ))

    compare("fdr_number", fdr.fdr_number,
            lambda record, doc: normalize_fdr_number(record) == normalize_fdr_number(doc),
            "DOC_FDR_NUMBER_MISMATCH", FindingSeverity.HIGH, "FDR reference differs from the document",
            "The FDR reference identifies the instrument; a different reference may mean the wrong document or record.")
    compare("amount", _amount(fdr), lambda record, doc: Decimal(record) == Decimal(doc),
            "DOC_AMOUNT_MISMATCH", FindingSeverity.HIGH, "Deposit amount differs from the document",
            "The amount on the receipt should equal the amount submitted.")
    compare("issue_date", fdr.issue_date.isoformat(), lambda record, doc: record == doc,
            "DOC_ISSUE_DATE_MISMATCH", FindingSeverity.WARNING, "Issue date differs from the document",
            "The issue date on the receipt should equal the submitted issue date. Dates are read day-first.")
    compare("maturity_date", fdr.maturity_date.isoformat(), lambda record, doc: record == doc,
            "DOC_MATURITY_DATE_MISMATCH", FindingSeverity.WARNING, "Maturity date differs from the document",
            "The maturity date on the receipt should equal the submitted maturity date. Dates are read day-first.")
    compare("ifsc_code", fdr.ifsc_code, lambda record, doc: record.upper() == doc.upper(),
            "DOC_IFSC_MISMATCH", FindingSeverity.WARNING, "IFSC differs from the document",
            "The branch IFSC printed on the document should equal the submitted IFSC.")
    compare("bank_name", fdr.bank_name, _bank_names_agree,
            "DOC_BANK_NAME_MISMATCH", FindingSeverity.WARNING, "Bank name differs from the document",
            "The issuing bank named on the document should be the submitted bank (compared ignoring case, "
            "punctuation and words such as 'Ltd').")

    # Date order within the document itself.
    issues, maturities = result.values("issue_date"), result.values("maturity_date")
    if len(issues) == 1 and len(maturities) == 1 and maturities[0].value <= issues[0].value:
        findings.append(Finding(
            "DOC_DATE_ORDER_INVALID", FindingCategory.DOCUMENT_CONSISTENCY, FindingSeverity.WARNING,
            "Dates on the document are out of order",
            "The maturity date read from the document is not after its issue date.",
            "A receipt should show maturity after issue; this may indicate a misread or an altered document.",
            field="maturity_date", document_id=document.id,
            observed={**doc_ref, "issue_date": issues[0].value, "maturity_date": maturities[0].value},
        ))

    holders = result.values("holder")
    if holders and not any(_holder_names_institution(h.value, fdr) for h in holders):
        findings.append(Finding(
            "DOC_HOLDER_NOT_INSTITUTION", FindingCategory.DOCUMENT_CONSISTENCY, FindingSeverity.INFO,
            "Depositor named on the document may not be the institution",
            "The depositor/holder text does not clearly mention the submitting institution.",
            "Security-deposit FDRs are normally held by or for the institution; the wording may simply differ.",
            field="holder", document_id=document.id,
            observed={**doc_ref, "institution": fdr.institution.name,
                      "document_values": [{"value": h.value, "snippet": h.raw, "page": h.page} for h in holders]},
        ))

    if document.document_type.value == "FDR_COPY" and result.status in ("EXTRACTED", "NO_FIELDS_FOUND"):
        missing = [name for name in ("fdr_number", "amount", "issue_date", "maturity_date") if not result.values(name)]
        if missing:
            findings.append(Finding(
                "DOC_KEY_FIELDS_NOT_FOUND", FindingCategory.DOCUMENT_EXTRACTION, FindingSeverity.INFO,
                "Some key fields could not be read from the FDR copy",
                f"No labelled value was found for: {', '.join(m.replace('_', ' ') for m in missing)}.",
                "Values are only read when clearly labelled; these need to be checked by eye.",
                field=",".join(missing), document_id=document.id, observed=doc_ref,
            ))
    return findings


def document_rules(db: Session, fdr: FDR) -> tuple[list[Finding], list[dict[str, Any]]]:
    findings: list[Finding] = []
    summaries: list[dict[str, Any]] = []
    current = [d for d in fdr.documents if d.withdrawn_at is None]

    if not current:
        findings.append(Finding(
            "DOC_NONE_ATTACHED", FindingCategory.DOCUMENT_EXTRACTION, FindingSeverity.WARNING,
            "No supporting documents attached",
            "The record has no current supporting documents.",
            "Without a copy of the FDR, the submitted details cannot be compared with a document.",
        ))
        return findings, summaries
    if not any(d.document_type.value == "FDR_COPY" for d in current):
        findings.append(Finding(
            "DOC_NO_FDR_COPY", FindingCategory.DOCUMENT_EXTRACTION, FindingSeverity.INFO,
            "No document is marked as the FDR copy",
            "Documents are attached, but none is of type 'FDR copy'.",
            "The FDR copy is the primary document for comparing the submitted details.",
        ))

    for document in current:
        doc_ref = {"document_id": document.id, "document_name": document.original_filename,
                   "document_type": document.document_type.value}
        integrity = storage.check_integrity(document.storage_key, document.sha256)
        if integrity.status != "intact":
            findings.append(Finding(
                "DOC_INTEGRITY_FAILED", FindingCategory.DOCUMENT_EXTRACTION, FindingSeverity.HIGH,
                "Stored document failed its integrity check",
                f"The stored file is {integrity.status} compared with the SHA-256 recorded at upload.",
                "The file on disk is not the file that was uploaded, so it was not read.",
                document_id=document.id, observed={**doc_ref, "status": integrity.status},
            ))
            summaries.append({**doc_ref, "sha256": document.sha256, "status": "INTEGRITY_FAILED",
                              "method": None, "pages_read": 0, "fields": [], "note": "Not read: integrity check failed."})
            continue

        try:
            result = extract_document(integrity.data, document.content_type)
        except Exception:  # an extractor bug must not fail the whole run
            logger.warning("Extraction raised for document %s", document.id, exc_info=True)
            result = ExtractionResult("FAILED", None, note="Extraction failed unexpectedly; manual review needed.")
        summaries.append({**doc_ref, "sha256": document.sha256, **result.to_dict()})

        if result.status == "UNSUPPORTED_FORMAT":
            findings.append(Finding(
                "DOC_EXTRACTION_UNSUPPORTED", FindingCategory.DOCUMENT_EXTRACTION, FindingSeverity.INFO,
                "Document could not be read automatically",
                f"“{document.original_filename}” is an image; automatic reading (OCR) is not available.",
                "Compare this document with the record by eye.", document_id=document.id, observed=doc_ref,
            ))
        elif result.status == "NO_TEXT_LAYER":
            findings.append(Finding(
                "DOC_NO_TEXT_LAYER", FindingCategory.DOCUMENT_EXTRACTION, FindingSeverity.INFO,
                "PDF has no readable text",
                f"“{document.original_filename}” appears to be a scanned image without a text layer.",
                "OCR is not available; compare this document with the record by eye.",
                document_id=document.id, observed=doc_ref,
            ))
        elif result.status == "FAILED":
            findings.append(Finding(
                "DOC_EXTRACTION_FAILED", FindingCategory.DOCUMENT_EXTRACTION, FindingSeverity.WARNING,
                "Document could not be parsed",
                f"“{document.original_filename}” could not be read by the PDF text reader.",
                "The file may be damaged or unusual; it needs manual review.",
                document_id=document.id, observed=doc_ref,
            ))
        findings.extend(_consistency_findings(fdr, document, result))
    return findings, summaries


# ---------- rules: duplicates and reuse ----------


def duplicate_rules(db: Session, fdr: FDR) -> list[Finding]:
    findings: list[Finding] = []
    this = _record_summary(fdr)

    # 1. Same normalised reference at the same bank (the existing duplicate rule).
    for other in fdr_service.find_duplicates(db, fdr):
        comparisons = {
            "amount": (this["amount"], _amount(other)),
            "issue_date": (this["issue_date"], other.issue_date.isoformat()),
            "maturity_date": (this["maturity_date"], other.maturity_date.isoformat()),
        }
        differing = [name for name, (a, b) in comparisons.items() if a != b]
        exact = not differing
        cross = other.institution_id != fdr.institution_id
        if exact:
            code = "DUP_EXACT_OTHER_INSTITUTION" if cross else "DUP_EXACT_SAME_INSTITUTION"
            title = "Same FDR submitted by another institution" if cross else "Same FDR submitted twice by this institution"
            description = ("Another record has the same reference, bank, amount, issue date and maturity date.")
        else:
            code = "DUP_POSSIBLE_OTHER_INSTITUTION" if cross else "DUP_POSSIBLE_SAME_INSTITUTION"
            title = ("Same FDR reference at the same bank used by another institution" if cross
                     else "Same FDR reference at the same bank in another record of this institution")
            description = (f"Another record has the same reference at the same bank, but differs in: "
                           f"{', '.join(d.replace('_', ' ') for d in differing)}.")
        findings.append(Finding(
            code, FindingCategory.DUPLICATE,
            FindingSeverity.HIGH if cross else FindingSeverity.WARNING,
            title, description,
            ("An FDR can secure only one deposit; the same instrument on two records needs explanation. "
             "This may also be a data-entry error and is not proof of fraud.") if cross else
            "Possibly a resubmission or data-entry duplicate; check which record should remain.",
            field="fdr_number", related_fdr_id=other.id, match_type="EXACT" if exact else "POSSIBLE",
            observed={"this": this, "other": _record_summary(other),
                      "matching_fields": ["fdr_number (normalised)", "bank"] + [n for n in comparisons if n not in differing],
                      "differing_fields": differing},
        ))

    # 2. Near reference: one character different, same bank and same amount.
    this_number = fdr.fdr_number_normalized
    if len(this_number) >= NEAR_REFERENCE_MIN_LENGTH:
        candidates = db.scalars(
            select(FDR).where(FDR.id != fdr.id, FDR.amount_paise == fdr.amount_paise,
                              FDR.fdr_number_normalized != this_number)
            .options(joinedload(FDR.institution))
        ).unique().all()
        for other in candidates:
            if _same_bank(fdr, other) and _edit_distance_at_most_one(this_number, other.fdr_number_normalized):
                cross = other.institution_id != fdr.institution_id
                findings.append(Finding(
                    "DUP_NEAR_REFERENCE", FindingCategory.DUPLICATE, FindingSeverity.WARNING,
                    "Very similar FDR reference with the same amount at the same bank",
                    "Another record's reference differs by a single character and has the same amount and bank.",
                    "This can be a typing error or an altered reference; compare the two documents. "
                    "Amount alone is never treated as a match.",
                    field="fdr_number", related_fdr_id=other.id, match_type="NEAR_REFERENCE",
                    observed={"this": this, "other": _record_summary(other), "cross_institution": cross,
                              "matching_fields": ["bank", "amount"], "differing_fields": ["fdr_number (1 character)"]},
                ))

    # 3. The very same file attached to another record.
    hashes = {d.sha256: d for d in fdr.documents}
    if hashes:
        others = db.scalars(
            select(FDRDocument).where(FDRDocument.sha256.in_(hashes), FDRDocument.fdr_id != fdr.id)
            .options(joinedload(FDRDocument.fdr).joinedload(FDR.institution))
        ).unique().all()
        for other_doc in others:
            mine = hashes[other_doc.sha256]
            cross = other_doc.fdr.institution_id != fdr.institution_id
            findings.append(Finding(
                "DUP_SAME_DOCUMENT_FILE", FindingCategory.DUPLICATE,
                FindingSeverity.HIGH if cross else FindingSeverity.WARNING,
                "Identical document file attached to another record",
                f"“{mine.original_filename}” is byte-for-byte identical (same SHA-256) to a document on another record.",
                "One receipt should support one record; identical files on different records need explanation.",
                document_id=mine.id, related_fdr_id=other_doc.fdr_id, match_type="SAME_FILE",
                observed={"sha256": mine.sha256, "this_document": mine.original_filename,
                          "other_document": other_doc.original_filename, "cross_institution": cross,
                          "this": this, "other": _record_summary(other_doc.fdr)},
            ))
    return findings


# ---------- orchestration ----------


def evaluate(db: Session, fdr: FDR) -> Evaluation:
    """Run every rule. Reads only; raises only on unexpected errors."""
    findings = record_rules(fdr)
    document_findings, extraction = document_rules(db, fdr)
    findings += document_findings
    findings += duplicate_rules(db, fdr)
    findings += lifecycle_rules(fdr)
    return Evaluation(findings, extraction, _documents_fingerprint(list(fdr.documents)))


def review_priority(findings: list[Finding]) -> ReviewPriority:
    severities = {f.severity for f in findings if f.category != FindingCategory.LIFECYCLE}
    if FindingSeverity.HIGH in severities:
        return ReviewPriority.HIGH
    if FindingSeverity.WARNING in severities:
        return ReviewPriority.MEDIUM
    return ReviewPriority.LOW


def run_screening(db: Session, fdr: FDR, user: User, request: Request | None) -> ScreeningRun:
    """Screen an FDR and store the run. A failure is stored as a FAILED run; the FDR is never changed."""
    started = datetime.now(timezone.utc)
    fdr_id, institution_id = fdr.id, fdr.institution_id
    run_number = (db.scalar(select(func.max(ScreeningRun.run_number)).where(ScreeningRun.fdr_id == fdr_id)) or 0) + 1

    try:
        evaluation = evaluate(db, fdr)
    except Exception:
        logger.exception("Screening engine failed for FDR %s", fdr_id)
        db.rollback()
        fdr = db.get(FDR, fdr_id)
        run = ScreeningRun(
            fdr_id=fdr_id, run_number=run_number, engine_version=ENGINE_VERSION, status=ScreeningRunStatus.FAILED,
            triggered_by_id=user.id, started_at=started, fdr_version=fdr.version,
            documents_fingerprint=_documents_fingerprint(list(fdr.documents)), extraction=[],
            error_code="ENGINE_ERROR",
        )
        db.add(run)
        db.flush()
        record_audit(
            db, action=AuditAction.SCREENING_RUN_FAILED, entity_type="fdr", entity_id=fdr_id,
            institution_id=institution_id, actor=user, request=request,
            summary=f"Screening run #{run_number} failed; no changes were made to the record",
            changes={"run_id": run.id, "engine_version": ENGINE_VERSION},
        )
        db.commit()
        return run

    counts = {severity: sum(f.severity == severity for f in evaluation.findings) for severity in FindingSeverity}
    priority = review_priority(evaluation.findings)
    run = ScreeningRun(
        fdr_id=fdr_id, run_number=run_number, engine_version=f"{ENGINE_VERSION}+{EXTRACTOR_VERSION}",
        status=ScreeningRunStatus.COMPLETED, triggered_by_id=user.id, started_at=started,
        fdr_version=fdr.version, documents_fingerprint=evaluation.documents_fingerprint,
        review_priority=priority, high_count=counts[FindingSeverity.HIGH],
        warning_count=counts[FindingSeverity.WARNING], info_count=counts[FindingSeverity.INFO],
        extraction=evaluation.extraction,
    )
    db.add(run)
    db.flush()
    for f in evaluation.findings:
        db.add(ScreeningFinding(
            run_id=run.id, code=f.code, rule_version=RULE_VERSION, category=f.category, severity=f.severity,
            title=f.title[:200], description=f.description[:1000], reason=f.reason[:1000], field=f.field,
            observed=f.observed, document_id=f.document_id, related_fdr_id=f.related_fdr_id,
            match_type=f.match_type, fingerprint=f.fingerprint[:200],
        ))
    record_audit(
        db, action=AuditAction.SCREENING_RUN_COMPLETED, entity_type="fdr", entity_id=fdr_id,
        institution_id=institution_id, actor=user, request=request,
        summary=(f"Screening run #{run_number} completed: priority {priority.value} "
                 f"({counts[FindingSeverity.HIGH]} high, {counts[FindingSeverity.WARNING]} warning, "
                 f"{counts[FindingSeverity.INFO]} info)"),
        changes={"run_id": run.id, "engine_version": run.engine_version, "review_priority": priority.value,
                 "finding_codes": sorted({f.code for f in evaluation.findings})},
    )
    db.commit()
    return run
