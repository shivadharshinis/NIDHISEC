from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserRole
from app.schemas.common import InstitutionBrief


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Not format-validated: any malformed address simply fails authentication.
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UserRead(BaseModel):
    """Public view of a user. Never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    role: UserRole
    institution: InstitutionBrief | None
    is_active: bool
    last_login_at: datetime | None


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserRead
