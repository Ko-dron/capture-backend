import asyncio
import io
import logging
from dataclasses import dataclass

import cloudinary
import cloudinary.uploader
import cloudinary.api

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Initialize Cloudinary
cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True,
)

MAX_RETRIES = 3
BASE_DELAY = 1  # seconds


@dataclass
class UploadResult:
    cloudinary_url: str
    cloudinary_public_id: str
    thumbnail_url: str


async def _retry_upload(upload_fn, *args, **kwargs):
    """Execute an upload function with exponential backoff retry."""
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            # cloudinary SDK is synchronous — run in thread pool
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: upload_fn(*args, **kwargs)
            )
            return result
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(
                    f"Cloudinary upload attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {delay}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"Cloudinary upload failed after {MAX_RETRIES} attempts: {e}")

    raise last_error


async def upload_image(file_bytes: bytes, filename: str, user_id: str) -> UploadResult:
    """Upload an image to Cloudinary with thumbnail transformation."""
    result = await _retry_upload(
        cloudinary.uploader.upload,
        file_bytes,
        folder=f"capture/{user_id}/photos",
        resource_type="image",
        public_id=filename.rsplit(".", 1)[0] if "." in filename else filename,
        eager=[
            {"width": 400, "height": 400, "crop": "fill", "quality": "auto"},
        ],
        eager_async=False,
    )

    # Get thumbnail URL from eager transformation
    thumbnail_url = result.get("secure_url", "")
    if result.get("eager") and len(result["eager"]) > 0:
        thumbnail_url = result["eager"][0].get("secure_url", result["secure_url"])

    return UploadResult(
        cloudinary_url=result["secure_url"],
        cloudinary_public_id=result["public_id"],
        thumbnail_url=thumbnail_url,
    )


async def upload_video(file_bytes: bytes, filename: str, user_id: str) -> UploadResult:
    """Upload a video to Cloudinary with video thumbnail transformation."""
    result = await _retry_upload(
        cloudinary.uploader.upload,
        file_bytes,
        folder=f"capture/{user_id}/videos",
        resource_type="video",
        public_id=filename.rsplit(".", 1)[0] if "." in filename else filename,
        eager=[
            {
                "width": 400,
                "height": 400,
                "crop": "fill",
                "format": "jpg",
                "start_offset": "0",
            },
        ],
        eager_async=False,
    )

    # Get thumbnail URL from eager transformation
    thumbnail_url = result.get("secure_url", "")
    if result.get("eager") and len(result["eager"]) > 0:
        thumbnail_url = result["eager"][0].get("secure_url", result["secure_url"])

    return UploadResult(
        cloudinary_url=result["secure_url"],
        cloudinary_public_id=result["public_id"],
        thumbnail_url=thumbnail_url,
    )


async def delete_media(public_id: str, resource_type: str = "image") -> bool:
    """Delete a media asset from Cloudinary."""
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: cloudinary.uploader.destroy(public_id, resource_type=resource_type),
        )
        return result.get("result") == "ok"
    except Exception as e:
        logger.error(f"Cloudinary delete failed for {public_id}: {e}")
        return False
