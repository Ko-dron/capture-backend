import io
from fastapi import HTTPException, status
from PIL import Image as PILImage


# Magic byte signatures
_MAGIC_BYTES = {
    "image/jpeg": lambda b: b[:3] == b"\xff\xd8\xff",
    "image/png": lambda b: b[:4] == b"\x89PNG",
    "image/webp": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP",
    "video/mp4": lambda b: b[4:8] == b"ftyp",
    "video/webm": lambda b: b[:4] == b"\x1a\x45\xdf\xa3",
}

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm"}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES

MAX_PHOTO_SIZE = 15 * 1024 * 1024   # 15MB
MAX_VIDEO_SIZE = 50 * 1024 * 1024   # 50MB


def validate_file_type(file_bytes: bytes, content_type: str | None) -> str:
    """Detect actual MIME type from magic bytes. Reject if mismatch with claimed type.

    Returns the validated MIME type string.
    Raises HTTPException 400 if file type is not allowed or mismatched.
    """
    if len(file_bytes) < 16:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too small to identify",
        )

    # Detect actual type from magic bytes
    detected_mime = None
    for mime, check_fn in _MAGIC_BYTES.items():
        if check_fn(file_bytes):
            detected_mime = mime
            break

    if detected_mime is None or detected_mime not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File type not allowed. Supported: JPEG, PNG, WebP, MP4, WebM",
        )

    # Validate claimed Content-Type matches detected category
    claimed = (content_type or "").strip()
    if claimed and claimed not in ("application/octet-stream", "") and claimed in ALLOWED_TYPES:
        detected_is_image = detected_mime in ALLOWED_IMAGE_TYPES
        claimed_is_image = claimed in ALLOWED_IMAGE_TYPES
        if detected_is_image != claimed_is_image:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File content does not match declared type",
            )

    return detected_mime


def validate_file_size(file_bytes: bytes, media_type: str) -> None:
    """Check file size against limits for the given media type.

    Raises HTTPException 413 if file exceeds the limit.
    """
    file_size = len(file_bytes)

    if media_type == "photo" and file_size > MAX_PHOTO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Photo too large. Maximum size is {MAX_PHOTO_SIZE // (1024 * 1024)}MB",
        )
    if media_type == "video" and file_size > MAX_VIDEO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Video too large. Maximum size is {MAX_VIDEO_SIZE // (1024 * 1024)}MB",
        )


def strip_exif(image_bytes: bytes) -> bytes:
    """Remove EXIF metadata from an image for privacy protection.

    Opens with Pillow, saves back without EXIF data.
    Returns cleaned image bytes. If stripping fails, returns original bytes.
    """
    try:
        img = PILImage.open(io.BytesIO(image_bytes))
        output = io.BytesIO()

        # Determine format
        fmt = img.format or "JPEG"
        if fmt.upper() == "MPO":
            fmt = "JPEG"

        # Save without EXIF — Pillow drops EXIF by default when you don't pass exif=
        save_kwargs = {}
        if fmt.upper() in ("JPEG", "JPG"):
            save_kwargs["quality"] = 95
            save_kwargs["optimize"] = True
        elif fmt.upper() == "PNG":
            save_kwargs["optimize"] = True
        elif fmt.upper() == "WEBP":
            save_kwargs["quality"] = 95

        img.save(output, format=fmt, **save_kwargs)
        return output.getvalue()
    except Exception:
        # If stripping fails for any reason, return original bytes
        return image_bytes
