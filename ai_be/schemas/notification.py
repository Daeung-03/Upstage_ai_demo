from uuid import UUID
from datetime import datetime
from pydantic import BaseModel
from app.models.enums import NotificationStatus

class NotificationResponse(BaseModel):
    id:           UUID
    user_id:      UUID
    term_id:      UUID
    version_id:   UUID | None
    title:        str
    diff_summary: str | None
    status:       NotificationStatus
    created_at:   datetime

    model_config = {"from_attributes": True}

class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    unread_count:  int