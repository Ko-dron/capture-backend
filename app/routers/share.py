import math
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.media import Media
from app.models.share_link import ShareLink
from app.models.user import User
from app.schemas.media import MediaResponse
from app.schemas.share import ShareLinkCreate, ShareLinkList, SharedGalleryResponse
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/share", tags=["Share Links"])
settings = get_settings()


@router.post("/create", response_model=ShareLinkCreate)
async def create_share_link(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new 24-hour share link for the authenticated user's gallery."""
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    share_link = ShareLink(
        user_id=current_user.id,
        token=token,
        expires_at=expires_at,
    )
    db.add(share_link)
    await db.flush()
    await db.refresh(share_link)

    return ShareLinkCreate(
        id=share_link.id,
        token=token,
        url=f"{settings.FRONTEND_URL}/share/{token}",
        expires_at=expires_at,
        created_at=share_link.created_at,
    )


@router.get("/links", response_model=list[ShareLinkList])
async def list_share_links(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all share links for the authenticated user, ordered by created_at desc."""
    result = await db.execute(
        select(ShareLink)
        .where(ShareLink.user_id == current_user.id)
        .order_by(ShareLink.created_at.desc())
    )
    links = result.scalars().all()
    now = datetime.now(timezone.utc)

    return [
        ShareLinkList(
            id=link.id,
            token=link.token,
            url=f"{settings.FRONTEND_URL}/share/{link.token}",
            expires_at=link.expires_at,
            is_active=link.is_active,
            view_count=link.view_count,
            is_expired=link.expires_at <= now,
            created_at=link.created_at,
        )
        for link in links
    ]


@router.get("/{token}", response_model=SharedGalleryResponse)
async def get_shared_gallery(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — view a shared gallery by token."""
    result = await db.execute(
        select(ShareLink).where(ShareLink.token == token)
    )
    share_link = result.scalar_one_or_none()

    if share_link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found",
        )

    now = datetime.now(timezone.utc)

    if not share_link.is_active or share_link.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This link has expired",
        )

    # Increment view count
    share_link.view_count += 1

    # Get the owner's event name
    user_result = await db.execute(
        select(User).where(User.id == share_link.user_id)
    )
    user = user_result.scalar_one()

    # Get all approved media for this user
    media_result = await db.execute(
        select(Media)
        .where(Media.user_id == share_link.user_id, Media.is_approved == True)
        .order_by(Media.uploaded_at.desc())
    )
    media_items = media_result.scalars().all()

    time_remaining = int((share_link.expires_at - now).total_seconds())

    return SharedGalleryResponse(
        event_name=user.event_name,
        time_remaining=max(time_remaining, 0),
        media=[MediaResponse.model_validate(m) for m in media_items],
    )


@router.delete("/{link_id}")
async def deactivate_share_link(
    link_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-deactivate a share link (owner only)."""
    result = await db.execute(
        select(ShareLink).where(ShareLink.id == link_id)
    )
    share_link = result.scalar_one_or_none()

    if share_link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found",
        )

    if share_link.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to deactivate this link",
        )

    share_link.is_active = False

    return {"message": "Share link deactivated"}
