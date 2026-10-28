from datetime import datetime
from math import ceil

from pydantic import BaseModel, ConfigDict, computed_field


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int

    @computed_field
    @property
    def pages(self) -> int:
        return ceil(self.total / self.page_size) if self.total else 0


class InstitutionBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str


class InstitutionSummary(InstitutionBrief):
    """AICTE college directory entry: contact details and FDR counts."""

    state: str | None
    contact_email: str | None
    contact_phone: str | None
    fdr_total: int
    fdrs_open_review: int
    fdrs_accepted: int
    fdrs_rejected: int
    latest_submission_at: datetime | None
