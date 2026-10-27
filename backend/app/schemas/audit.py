from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor_user_id: int | None
    actor_email: str | None
    actor_name: str | None
    actor_role: str | None
    action: str
    entity_type: str
    entity_id: int | None
    institution_id: int | None
    summary: str
    changes: dict | None
    ip_address: str | None
