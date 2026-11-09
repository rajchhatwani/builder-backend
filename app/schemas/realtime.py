from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HeartbeatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    where: str = Field(default="", max_length=80)


class PresenceRead(BaseModel):
    user_id: str
    display: str
    where: str
    last_seen: datetime
