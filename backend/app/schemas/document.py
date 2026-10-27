from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DocumentType


class DocumentRead(BaseModel):
    """Document metadata. Never includes the storage key or any filesystem path."""

    id: int
    fdr_id: int
    document_type: DocumentType
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime
    uploaded_by_name: str
    is_withdrawn: bool
    withdrawn_at: datetime | None
    withdrawn_by_name: str | None
    withdrawal_reason: str | None


class DocumentList(BaseModel):
    items: list[DocumentRead]
    can_upload: bool
    can_withdraw: bool
    can_check_integrity: bool
    max_upload_bytes: int
    allowed_extensions: list[str]


class DocumentWithdraw(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    reason: str = Field(min_length=5, max_length=500)


class IntegrityReport(BaseModel):
    """Whether the stored file still matches the hash recorded at upload.

    "intact" proves the file is unchanged since upload. It does not prove the
    document is genuine.
    """

    document_id: int
    status: Literal["intact", "mismatch", "missing"]
    expected_sha256: str
    actual_sha256: str | None
    checked_at: datetime
