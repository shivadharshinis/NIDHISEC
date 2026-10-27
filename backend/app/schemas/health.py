from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    description: str
    version: str
    environment: str
    database: Literal["ok", "error"]
    timestamp: datetime
