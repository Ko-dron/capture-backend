import math
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.media import Media
from app.models.upload_session import UploadSession
from app.schemas.media import (
    MediaResponse,
    MediaUploadResponse,
    MediaListResponse,
    MediaStatsResponse,
)
from app.services.cloudinary_service import upload_image, upload_video, delete_media
from app.utils.auth import get_current_user
from app.utils.file_validation import (
    validate_file_type,
    validate_file_size,
    strip_exif,
    ALLOWED_IMAGE_TYPES,
)

router = APIRouter(prefix="/api/media", tags=["Media"])


@router.get("/validate/{event_token}")
async def validate_event_token(
    event_token: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.event_token == event_token))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired event link",
        )

    return {
        "event_name": user.event_name,
        "event_type": user.event_type,
    }


@router.post("/upload/{event_token}", response_model=MediaUploadResponse)
async def upload_media(
    event_token: str,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    # Validate event token
    result = await db.execute(select(User).where(User.event_token == event_token))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired event link",
        )

    # Read file bytes
    file_bytes = await file.read()
    file_size = len(file_bytes)

    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file",
        )

    # Validate file type via magic bytes (rejects .exe renamed to .jpg, etc.)
    detected_mime = validate_file_type(file_bytes, file.content_type)
    is_image = detected_mime in ALLOWED_IMAGE_TYPES
    media_type = "photo" if is_image else "video"

    # Validate file size
    validate_file_size(file_bytes, media_type)

    # Strip EXIF metadata from images for privacy
    if is_image:
        file_bytes = strip_exif(file_bytes)
        file_size = len(file_bytes)
    user_id_str = str(user.id)

    # Create upload session record
    client_ip = request.client.host if request.client else "unknown"
    device_info = request.headers.get("user-agent", "unknown")[:255]

    upload_session = UploadSession(
        user_id=user.id,
        session_token=secrets.token_urlsafe(48),
        device_info=device_info,
        ip_address=client_ip,
        media_count=1,
    )
    db.add(upload_session)

    # Upload to Cloudinary first (always)
    filename = file.filename or f"capture_{secrets.token_hex(8)}"
    try:
        if is_image:
            cloud_result = await upload_image(file_bytes, filename, user_id_str)
        else:
            cloud_result = await upload_video(file_bytes, filename, user_id_str)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to upload to storage: {str(e)}",
        )

    # Save media as approved immediately
    media = Media(
        user_id=user.id,
        cloudinary_url=cloud_result.cloudinary_url,
        cloudinary_public_id=cloud_result.cloudinary_public_id,
        thumbnail_url=cloud_result.thumbnail_url,
        media_type=media_type,
        file_size=file_size,
        is_approved=True,
        quality_score=None,
    )
    db.add(media)
    await db.flush()

    return MediaUploadResponse(
        media_id=str(media.id),
        media_type=media_type,
        cloudinary_url=cloud_result.cloudinary_url,
        thumbnail_url=cloud_result.thumbnail_url,
        file_size=file_size,
        is_approved=True,
        quality_score=None,
        message="Upload successful",
    )


@router.get("", response_model=MediaListResponse)
async def list_media(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    media_type: str | None = Query(None, pattern="^(photo|video)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all media for the authenticated user, paginated."""
    # Base query — exclude broken records with empty cloudinary_url
    query = select(Media).where(
        Media.user_id == current_user.id,
        Media.cloudinary_url != "",
    )
    count_query = select(func.count()).select_from(Media).where(
        Media.user_id == current_user.id,
        Media.cloudinary_url != "",
    )

    # Optional type filter
    if media_type:
        query = query.where(Media.media_type == media_type)
        count_query = count_query.where(Media.media_type == media_type)

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Paginate
    offset = (page - 1) * per_page
    query = query.order_by(Media.uploaded_at.desc()).offset(offset).limit(per_page)

    result = await db.execute(query)
    media_items = result.scalars().all()

    return MediaListResponse(
        media=[MediaResponse.model_validate(m) for m in media_items],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=math.ceil(total / per_page) if total > 0 else 1,
    )


@router.get("/stats", response_model=MediaStatsResponse)
async def media_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return upload statistics for the authenticated user."""
    base = select(func.count()).select_from(Media).where(
        Media.user_id == current_user.id,
        Media.cloudinary_url != "",
    )

    total_result = await db.execute(base)
    total = total_result.scalar()

    photos_result = await db.execute(base.where(Media.media_type == "photo"))
    photos = photos_result.scalar()

    videos_result = await db.execute(base.where(Media.media_type == "video"))
    videos = videos_result.scalar()

    return MediaStatsResponse(
        total_uploads=total,
        approved=total,
        rejected=0,
        total_photos=photos,
        total_videos=videos,
    )


@router.delete("/{media_id}")
async def delete_media_item(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a media item. Verify ownership, remove from Cloudinary and database."""
    result = await db.execute(select(Media).where(Media.id == media_id))
    media = result.scalar_one_or_none()

    if media is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media not found",
        )

    if media.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this media",
        )

    # Delete from Cloudinary
    if media.cloudinary_public_id:
        resource_type = "video" if media.media_type == "video" else "image"
        await delete_media(media.cloudinary_public_id, resource_type)

    # Delete from database
    await db.delete(media)

    return {"message": "Media deleted successfully"}
