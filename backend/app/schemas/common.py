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
