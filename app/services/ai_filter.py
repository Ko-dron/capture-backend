import asyncio
import base64
import json
import logging
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass

import cv2
import numpy as np

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1


@dataclass
class FilterResult:
    is_approved: bool
    quality_score: float  # 0.0 to 1.0
    rejection_reason: str | None  # "blurry", "too_dark", "too_bright", "obstructed", "unclear", None


class MediaFilter(ABC):
    @abstractmethod
    async def analyze_image(self, image_bytes: bytes) -> FilterResult:
        pass

    @abstractmethod
    async def analyze_video(self, video_bytes: bytes) -> FilterResult:
        pass


def _extract_video_frame(video_bytes: bytes, timestamp_sec: float = 1.0) -> bytes | None:
    """Extract a frame from video at the given timestamp using OpenCV."""
    tmp = None
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
        tmp.write(video_bytes)
        tmp.flush()
        tmp_path = tmp.name
        tmp.close()

        cap = cv2.VideoCapture(tmp_path)
        if not cap.isOpened():
            return None

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30

        frame_number = int(timestamp_sec * fps)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # If video is shorter than timestamp, get first frame
        if frame_number >= total_frames:
            frame_number = 0

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return None

        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return buf.tobytes()
    except Exception as e:
        logger.error(f"Failed to extract video frame: {e}")
        return None
    finally:
        if tmp:
            import os
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


# =============================================================================
# IMPLEMENTATION 1: Claude AI Filter
# =============================================================================

class ClaudeFilter(MediaFilter):
    """Uses Claude's vision API to analyze image quality."""

    SYSTEM_PROMPT = (
        "You are a photo quality analyzer for an event photography platform. "
        "Analyze this image and respond with ONLY a JSON object. "
        "Evaluate: 1) Sharpness/blur (is the image in focus?), "
        "2) Lighting (is it too dark or too bright?), "
        "3) Composition (is the subject visible and not obstructed?), "
        "4) Overall quality (would this be a good event photo to keep?). "
        'Respond with: {"is_approved": true/false, "quality_score": 0.0-1.0, '
        '"rejection_reason": null or one of "blurry"/"too_dark"/"too_bright"/"obstructed"/"unclear"}'
    )

    def __init__(self):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def analyze_image(self, image_bytes: bytes) -> FilterResult:
        """Send image to Claude for quality analysis."""
        for attempt in range(MAX_RETRIES):
            try:
                # Detect media type for the API
                media_type = "image/jpeg"
                if image_bytes[:4] == b"\x89PNG":
                    media_type = "image/png"
                elif image_bytes[:4] == b"RIFF":
                    media_type = "image/webp"

                b64_image = base64.standard_b64encode(image_bytes).decode("utf-8")

                response = await self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=256,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": b64_image,
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": self.SYSTEM_PROMPT,
                                },
                            ],
                        }
                    ],
                )

                # Parse JSON from response
                text = response.content[0].text.strip()
                # Handle possible markdown code blocks
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()

                data = json.loads(text)

                return FilterResult(
                    is_approved=bool(data.get("is_approved", True)),
                    quality_score=float(data.get("quality_score", 0.5)),
                    rejection_reason=data.get("rejection_reason"),
                )

            except json.JSONDecodeError as e:
                logger.warning(f"Claude returned invalid JSON (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRIES - 1:
                    # Fail open
                    logger.error("Claude filter: could not parse response, approving by default")
                    return FilterResult(is_approved=True, quality_score=0.5, rejection_reason=None)
                await asyncio.sleep(BASE_DELAY * (2 ** attempt))

            except Exception as e:
                logger.warning(f"Claude API error (attempt {attempt + 1}): {e}")
                if attempt == MAX_RETRIES - 1:
                    # Fail open — approve the media if API is down
                    logger.error("Claude filter failed, approving by default")
                    return FilterResult(is_approved=True, quality_score=0.5, rejection_reason=None)
                await asyncio.sleep(BASE_DELAY * (2 ** attempt))

        # Should not reach here, but fail open
        return FilterResult(is_approved=True, quality_score=0.5, rejection_reason=None)

    async def analyze_video(self, video_bytes: bytes) -> FilterResult:
        """Extract a frame from the video and analyze it."""
        frame_bytes = await asyncio.get_event_loop().run_in_executor(
            None, _extract_video_frame, video_bytes, 1.0
        )

        if frame_bytes is None:
            # Can't extract frame — approve by default
            logger.warning("Could not extract video frame for analysis, approving by default")
            return FilterResult(is_approved=True, quality_score=0.5, rejection_reason=None)

        return await self.analyze_image(frame_bytes)


# =============================================================================
# IMPLEMENTATION 2: Local OpenCV Filter
# =============================================================================

class LocalFilter(MediaFilter):
    """Uses OpenCV for local image quality analysis without API calls."""

    BLUR_THRESHOLD = 100
    DARK_THRESHOLD = 40
    BRIGHT_THRESHOLD = 220
    APPROVAL_THRESHOLD = 0.4

    async def analyze_image(self, image_bytes: bytes) -> FilterResult:
        """Analyze image quality using OpenCV."""
        result = await asyncio.get_event_loop().run_in_executor(
            None, self._analyze_sync, image_bytes
        )
        return result

    def _analyze_sync(self, image_bytes: bytes) -> FilterResult:
        """Synchronous image analysis with OpenCV."""
        try:
            # Decode image
            arr = np.frombuffer(image_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

            if img is None:
                return FilterResult(is_approved=True, quality_score=0.5, rejection_reason=None)

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 1) Blur detection — Laplacian variance
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            is_blurry = laplacian_var < self.BLUR_THRESHOLD

            # Normalize sharpness score: cap at 1000 for max
            sharpness_score = min(laplacian_var / 1000.0, 1.0)

            # 2) Brightness check
            mean_brightness = float(gray.mean())
            is_too_dark = mean_brightness < self.DARK_THRESHOLD
            is_too_bright = mean_brightness > self.BRIGHT_THRESHOLD

            # Normalize brightness score: optimal around 100-160
            if mean_brightness < self.DARK_THRESHOLD:
                brightness_score = mean_brightness / self.DARK_THRESHOLD * 0.3
            elif mean_brightness > self.BRIGHT_THRESHOLD:
                brightness_score = max(0.0, 1.0 - (mean_brightness - self.BRIGHT_THRESHOLD) / 35.0) * 0.5
            else:
                # Good range
                brightness_score = 0.7 + 0.3 * (1.0 - abs(mean_brightness - 130) / 130.0)

            # 3) Contrast — standard deviation of grayscale
            contrast = float(gray.std())
            contrast_score = min(contrast / 80.0, 1.0)

            # Weighted quality score
            quality_score = (
                sharpness_score * 0.5
                + brightness_score * 0.3
                + contrast_score * 0.2
            )
            quality_score = round(max(0.0, min(1.0, quality_score)), 3)

            # Determine rejection reason (brightness issues take priority
            # since extreme dark/bright causes false blur readings)
            rejection_reason = None
            if is_too_dark:
                rejection_reason = "too_dark"
            elif is_too_bright:
                rejection_reason = "too_bright"
            elif is_blurry:
                rejection_reason = "blurry"

            is_approved = quality_score >= self.APPROVAL_THRESHOLD and rejection_reason is None

            return FilterResult(
                is_approved=is_approved,
                quality_score=quality_score,
                rejection_reason=rejection_reason if not is_approved else None,
            )

        except Exception as e:
            logger.error(f"LocalFilter analysis failed: {e}")
            return FilterResult(is_approved=True, quality_score=0.5, rejection_reason=None)

    async def analyze_video(self, video_bytes: bytes) -> FilterResult:
        """Extract a frame from the video and analyze it."""
        frame_bytes = await asyncio.get_event_loop().run_in_executor(
            None, _extract_video_frame, video_bytes, 1.0
        )

        if frame_bytes is None:
            logger.warning("Could not extract video frame, approving by default")
            return FilterResult(is_approved=True, quality_score=0.5, rejection_reason=None)

        return await self.analyze_image(frame_bytes)


# =============================================================================
# Factory
# =============================================================================

def get_media_filter() -> MediaFilter:
    """Return the appropriate filter based on configuration."""
    mode = settings.AI_FILTER_MODE.lower()

    if mode == "claude" and settings.ANTHROPIC_API_KEY:
        logger.info("Using Claude AI filter")
        return ClaudeFilter()

    logger.info("Using local OpenCV filter")
    return LocalFilter()
