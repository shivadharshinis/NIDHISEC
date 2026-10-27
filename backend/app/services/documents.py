"""Access rules and serialisation for FDR documents."""

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.models import FDR, FDRDocument, FDRStatus, User, UserRole
from app.schemas.document import DocumentRead
from app.services import fdrs as fdr_service


def can_upload(user: User, fdr: FDR) -> bool:
    """The owning institution may add documents until the record is rejected."""
    return (
        user.role == UserRole.INSTITUTION
        and user.institution_id == fdr.institution_id
        and fdr.status != FDRStatus.REJECTED
        and fdr_service.is_workable(fdr)
    )


def can_withdraw(user: User, fdr: FDR) -> bool:
    """Withdrawal follows the same window as correcting the record's details."""
    return fdr_service.can_edit(user, fdr)


def can_check_integrity(user: User) -> bool:
    return user.role == UserRole.AICTE_OFFICIAL


def get_fdr_for_documents(db: Session, user: User, fdr_id: int, request: Request | None = None) -> FDR:
    """The FDR whose documents the user may reach.

    Institutions and AICTE follow the FDR's own access rules (out of scope: 404).
    A bank officer needs an ACTIVE assignment for this FDR; anything else is
    refused with 403 and audited, without revealing whether the FDR exists.
    """
    if user.role == UserRole.BANK_OFFICER:
        from app.services import verification  # local import: verification depends on this module

        if verification.officer_active_assignment(db, user, fdr_id) is None:
            raise verification.deny_bank_officer(db, request, user, fdr_id=fdr_id, attempted="fdr_documents")
        return db.get(FDR, fdr_id)
    return fdr_service.get_fdr_for_user(db, user, fdr_id)


def get_document_for_user(
    db: Session, user: User, fdr_id: int, document_id: int, request: Request | None = None
) -> tuple[FDR, FDRDocument]:
    """Load a document through its FDR's access rules."""
    fdr = get_fdr_for_documents(db, user, fdr_id, request)
    document = db.get(FDRDocument, document_id)
    if document is None or document.fdr_id != fdr.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return fdr, document


def to_document_read(document: FDRDocument) -> DocumentRead:
    return DocumentRead(
        id=document.id,
        fdr_id=document.fdr_id,
        document_type=document.document_type,
        original_filename=document.original_filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        uploaded_at=document.uploaded_at,
        uploaded_by_name=document.uploaded_by.full_name,
        is_withdrawn=document.withdrawn_at is not None,
        withdrawn_at=document.withdrawn_at,
        withdrawn_by_name=document.withdrawn_by.full_name if document.withdrawn_by else None,
        withdrawal_reason=document.withdrawal_reason,
    )
