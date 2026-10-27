"""Supporting documents for FDR records.

Documents are only reachable through their FDR, so every request passes the
same access rules as the record itself. Files are served exclusively by the
permission-checked download endpoint; there are no public file URLs.
"""

import re
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_roles
from app.core.config import get_settings
from app.models import FDR, DocumentType, FDRDocument, User, UserRole
from app.schemas.document import DocumentList, DocumentRead, DocumentWithdraw, IntegrityReport
from app.services import document_storage as storage
from app.services import documents as document_service
from app.services.audit import AuditAction, record_audit
from app.services.file_validation import ALLOWED_EXTENSIONS, FileRejected, validate_upload

router = APIRouter(prefix="/fdrs/{fdr_id}/documents", tags=["documents"])

AicteUser = Annotated[User, Depends(require_roles(UserRole.AICTE_OFFICIAL))]

INTEGRITY_BLOCKED = (
    "The stored file no longer matches the hash recorded at upload, so the download was blocked. "
    "The event has been recorded in the audit log."
)


def _audit_document(
    db: DbSession, request: Request, user: User, fdr: FDR, action: AuditAction, summary: str, document: FDRDocument | None = None, **extra
) -> None:
    changes = {"document_id": document.id, "sha256": document.sha256} if document else {}
    changes.update(extra)
    record_audit(
        db,
        action=action,
        entity_type="fdr",
        entity_id=fdr.id,
        institution_id=fdr.institution_id,
        actor=user,
        summary=summary,
        changes=changes or None,
        request=request,
    )


def _content_disposition(filename: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._() -]", "_", filename) or "document"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.get("", response_model=DocumentList)
def list_documents(fdr_id: int, request: Request, user: CurrentUser, db: DbSession) -> DocumentList:
    fdr = document_service.get_fdr_for_documents(db, user, fdr_id, request)
    return DocumentList(
        items=[document_service.to_document_read(document) for document in fdr.documents],
        can_upload=document_service.can_upload(user, fdr),
        can_withdraw=document_service.can_withdraw(user, fdr),
        can_check_integrity=document_service.can_check_integrity(user),
        max_upload_bytes=get_settings().max_upload_bytes,
        allowed_extensions=list(ALLOWED_EXTENSIONS),
    )


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def upload_document(
    fdr_id: int,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File(description="PDF, PNG or JPEG")],
    document_type: Annotated[DocumentType, Form()] = DocumentType.FDR_COPY,
) -> DocumentRead:
    """Attach a supporting document. The file type is checked from its content.

    Uploading records the file and its SHA-256 hash. It does not verify that
    the document is genuine.
    """
    fdr = document_service.get_fdr_for_documents(db, user, fdr_id, request)
    if not document_service.can_upload(user, fdr):
        if user.role != UserRole.INSTITUTION:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your role cannot upload documents")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Documents cannot be added to a rejected record or to an instrument that is no longer active",
        )

    max_bytes = get_settings().max_upload_bytes
    data = file.file.read(max_bytes + 1)
    try:
        kind, display_name = validate_upload(data, file.filename, max_bytes)
    except FileRejected as exc:
        _audit_document(
            db, request, user, fdr, AuditAction.DOCUMENT_UPLOAD_REJECTED,
            f"Document upload rejected: {exc}", reason=str(exc), size_bytes=len(data),
        )
        db.commit()
        too_large = len(data) > max_bytes
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE if too_large else status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"loc": ["body", "file"], "msg": str(exc), "type": "value_error"}],
        ) from None

    digest = storage.sha256_hex(data)
    existing = db.scalar(select(FDRDocument.id).where(FDRDocument.fdr_id == fdr.id, FDRDocument.sha256 == digest))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This file is already attached to the record (document #{existing})",
        )

    key = storage.new_storage_key()
    storage.write_atomic(key, data)
    try:
        document = FDRDocument(
            fdr_id=fdr.id,
            document_type=document_type,
            original_filename=display_name,
            content_type=kind.content_type,
            size_bytes=len(data),
            sha256=digest,
            storage_key=key,
            uploaded_by_id=user.id,
        )
        db.add(document)
        db.flush()
        _audit_document(
            db, request, user, fdr, AuditAction.DOCUMENT_UPLOADED,
            f"Document #{document.id} uploaded ({display_name}, {kind.label})", document,
            filename=display_name, size_bytes=len(data),
        )
        db.commit()
    except BaseException:
        # Keep disk and database consistent: no orphaned file without a record.
        db.rollback()
        storage.delete(key)
        raise
    return document_service.to_document_read(document)


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(fdr_id: int, document_id: int, request: Request, user: CurrentUser, db: DbSession) -> DocumentRead:
    _, document = document_service.get_document_for_user(db, user, fdr_id, document_id, request)
    return document_service.to_document_read(document)


@router.get("/{document_id}/download", response_class=Response)
def download_document(fdr_id: int, document_id: int, request: Request, user: CurrentUser, db: DbSession) -> Response:
    """Stream a document after access and integrity checks. Every download is audited."""
    fdr, document = document_service.get_document_for_user(db, user, fdr_id, document_id, request)
    result = storage.check_integrity(document.storage_key, document.sha256)
    if result.status != "intact":
        _audit_document(
            db, request, user, fdr, AuditAction.DOCUMENT_INTEGRITY_FAILED,
            f"Download of document #{document.id} blocked: stored file {result.status}", document,
            result=result.status, actual_sha256=result.actual_sha256,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=INTEGRITY_BLOCKED)

    _audit_document(
        db, request, user, fdr, AuditAction.DOCUMENT_DOWNLOADED,
        f"Document #{document.id} downloaded ({document.original_filename})", document,
    )
    db.commit()
    return Response(
        content=result.data,
        media_type=document.content_type,
        headers={
            "Content-Disposition": _content_disposition(document.original_filename),
            # If a browser renders the file anyway, nothing in it may run.
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "no-store",
            "X-Content-SHA256": document.sha256,
        },
    )


@router.post("/{document_id}/withdraw", response_model=DocumentRead)
def withdraw_document(
    fdr_id: int, document_id: int, payload: DocumentWithdraw, request: Request, user: CurrentUser, db: DbSession
) -> DocumentRead:
    """Mark a document as withdrawn (e.g. attached by mistake). The file and record are kept."""
    fdr, document = document_service.get_document_for_user(db, user, fdr_id, document_id, request)
    if user.role != UserRole.INSTITUTION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your role cannot withdraw documents")
    if not document_service.can_withdraw(user, fdr):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Documents can only be withdrawn while the record is Submitted or Clarification requested",
        )
    if document.withdrawn_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This document has already been withdrawn")

    document.withdrawn_at = datetime.now(timezone.utc)
    document.withdrawn_by_id = user.id
    document.withdrawal_reason = payload.reason
    _audit_document(
        db, request, user, fdr, AuditAction.DOCUMENT_WITHDRAWN,
        f"Document #{document.id} withdrawn: {payload.reason}", document, reason=payload.reason,
    )
    db.commit()
    db.refresh(document)
    return document_service.to_document_read(document)


@router.post("/{document_id}/integrity-check", response_model=IntegrityReport)
def check_document_integrity(
    fdr_id: int, document_id: int, request: Request, user: AicteUser, db: DbSession
) -> IntegrityReport:
    """Re-hash the stored file and compare it with the hash recorded at upload."""
    fdr, document = document_service.get_document_for_user(db, user, fdr_id, document_id, request)
    result = storage.check_integrity(document.storage_key, document.sha256)
    intact = result.status == "intact"
    _audit_document(
        db, request, user, fdr,
        AuditAction.DOCUMENT_INTEGRITY_CHECKED if intact else AuditAction.DOCUMENT_INTEGRITY_FAILED,
        f"Integrity check of document #{document.id}: {result.status}", document,
        result=result.status, actual_sha256=result.actual_sha256,
    )
    db.commit()
    return IntegrityReport(
        document_id=document.id,
        status=result.status,  # type: ignore[arg-type]
        expected_sha256=document.sha256,
        actual_sha256=result.actual_sha256,
        checked_at=datetime.now(timezone.utc),
    )
