import uuid
from datetime import datetime
from pydantic import BaseModel


class MediaResponse(BaseModel):
    id: uuid.UUID
    media_type: str
    cloudinary_url: str
    thumbnail_url: str | None
    file_size: int | None
    is_approved: bool
    quality_score: float | None
    rejection_reason: str | None
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class MediaUploadResponse(BaseModel):
    media_id: str
    media_type: str
    cloudinary_url: str
    thumbnail_url: str | None
    file_size: int
    is_approved: bool
    quality_score: float | None = None
    rejection_reason: str | None = None
    message: str


class MediaListResponse(BaseModel):
    media: list[MediaResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class MediaStatsResponse(BaseModel):
    total_uploads: int
    approved: int
    rejected: int
    total_photos: int
    total_videos: int
