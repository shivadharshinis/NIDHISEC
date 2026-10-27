from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import DbSession, require_roles
from app.models import Institution, User, UserRole
from app.schemas.common import InstitutionBrief

router = APIRouter(prefix="/institutions", tags=["institutions"])


@router.get("", response_model=list[InstitutionBrief])
def list_institutions(
    db: DbSession,
    user: Annotated[User, Depends(require_roles(UserRole.AICTE_OFFICIAL, UserRole.INSTITUTION))],
) -> list[Institution]:
    """AICTE officials see all institutions (e.g. for filtering); institution users see only their own."""
    query = select(Institution).order_by(Institution.name)
    if user.role == UserRole.INSTITUTION:
        query = query.where(Institution.id == user.institution_id)
    return list(db.scalars(query).all())
