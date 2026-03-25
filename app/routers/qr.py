import io

import qrcode
from PIL import Image, ImageDraw, ImageFont
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.models.user import User
from app.utils.auth import get_current_user

settings = get_settings()
router = APIRouter(prefix="/api/qr", tags=["QR Code"])


@router.get("/generate")
async def generate_qr(current_user: User = Depends(get_current_user)):
    url = f"{settings.FRONTEND_URL}/upload/{current_user.event_token}"
    return {
        "event_token": current_user.event_token,
        "event_name": current_user.event_name,
        "event_type": current_user.event_type,
        "qr_url": url,
    }


@router.get("/export")
async def export_qr(current_user: User = Depends(get_current_user)):
    url = f"{settings.FRONTEND_URL}/upload/{current_user.event_token}"

    # Generate QR code
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=20,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    qr_img = qr.make_image(fill_color="#1A1A2E", back_color="white").convert("RGB")

    # Create final canvas: 1024x1024
    canvas_size = 1024
    canvas = Image.new("RGB", (canvas_size, canvas_size), "white")

    # Resize QR to fit with room for text below
    qr_area_height = 820
    qr_img = qr_img.resize((qr_area_height, qr_area_height), Image.LANCZOS)

    # Center QR on canvas
    qr_x = (canvas_size - qr_area_height) // 2
    qr_y = 40
    canvas.paste(qr_img, (qr_x, qr_y))

    # Draw branding text below the QR code
    draw = ImageDraw.Draw(canvas)

    # Try to use a nice font, fall back to default
    try:
        title_font = ImageFont.truetype("arial.ttf", 36)
        subtitle_font = ImageFont.truetype("arial.ttf", 22)
    except (OSError, IOError):
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()

    # Event name
    event_text = current_user.event_name
    title_bbox = draw.textbbox((0, 0), event_text, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    draw.text(
        ((canvas_size - title_w) // 2, qr_y + qr_area_height + 20),
        event_text,
        fill="#1A1A2E",
        font=title_font,
    )

    # "Powered by Capture" subtitle
    subtitle = "Powered by Capture"
    sub_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    sub_w = sub_bbox[2] - sub_bbox[0]
    draw.text(
        ((canvas_size - sub_w) // 2, qr_y + qr_area_height + 68),
        subtitle,
        fill="#6B7280",
        font=subtitle_font,
    )

    # Save to buffer
    buf = io.BytesIO()
    canvas.save(buf, format="PNG", quality=95)
    buf.seek(0)

    filename = f"capture-qr-{current_user.username}.png"
    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
