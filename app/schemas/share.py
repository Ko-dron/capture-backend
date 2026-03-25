import uuid
from datetime import datetime
from pydantic import BaseModel
from app.schemas.media import MediaResponse


class ShareLinkCreate(BaseModel):
    id: uuid.UUID
    token: str
    url: str
    expires_at: datetime
    created_at: datetime


class ShareLinkList(BaseModel):
    id: uuid.UUID
    token: str
    url: str
    expires_at: datetime
    is_active: bool
    view_count: int
    is_expired: bool
    created_at: datetime


class SharedGalleryResponse(BaseModel):
    event_name: str
    time_remaining: int
    media: list[MediaResponse]
