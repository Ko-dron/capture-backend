import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserResponse,
)
from app.utils.auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token,
    get_current_user,
)

settings = get_settings()
router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# In-memory login attempt tracking: {key: [(timestamp, ...),]}
_failed_attempts: dict[str, list[datetime]] = defaultdict(list)
LOCKOUT_THRESHOLD = 5
LOCKOUT_WINDOW = timedelta(minutes=15)

REFRESH_COOKIE_NAME = "refresh_token"


def _check_lockout(username: str, ip: str) -> None:
    key = f"{username}:{ip}"
    now = datetime.now(timezone.utc)
    # Prune old entries
    _failed_attempts[key] = [
        t for t in _failed_attempts[key] if now - t < LOCKOUT_WINDOW
    ]
    if len(_failed_attempts[key]) >= LOCKOUT_THRESHOLD:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later.",
        )


def _record_failed_attempt(username: str, ip: str) -> None:
    key = f"{username}:{ip}"
    _failed_attempts[key].append(datetime.now(timezone.utc))


def _clear_failed_attempts(username: str, ip: str) -> None:
    key = f"{username}:{ip}"
    _failed_attempts.pop(key, None)


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=7 * 24 * 60 * 60,  # 7 days
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/api/auth",
    )


@router.post("/register", response_model=TokenResponse)
async def register(
    data: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    # Check username uniqueness
    result = await db.execute(select(User).where(User.username == data.username))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    # Generate event token and QR data
    event_token = secrets.token_urlsafe(48)
    qr_code_data = f"{settings.FRONTEND_URL}/upload/{event_token}"

    # Create user
    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        event_name=data.event_name,
        event_type=data.event_type.value,
        event_token=event_token,
        qr_code_data=qr_code_data,
    )
    db.add(user)
    await db.flush()

    # Generate tokens
    token_data = {"sub": str(user.id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    _set_refresh_cookie(response, refresh_token)

    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"

    # Check lockout
    _check_lockout(data.username, client_ip)

    # Find user
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(data.password, user.password_hash):
        _record_failed_attempt(data.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Clear failed attempts on success
    _clear_failed_attempts(data.username, client_ip)

    # Generate tokens
    token_data = {"sub": str(user.id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    _set_refresh_cookie(response, refresh_token)

    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: Request,
    response: Response,
):
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token",
        )

    # Verify the refresh token
    payload = verify_token(token, expected_type="refresh")
    user_id = payload.get("sub")

    # Rotate: issue new tokens
    token_data = {"sub": user_id}
    new_access_token = create_access_token(token_data)
    new_refresh_token = create_refresh_token(token_data)

    _set_refresh_cookie(response, new_refresh_token)

    return TokenResponse(access_token=new_access_token)


@router.post("/logout")
async def logout(response: Response):
    _clear_refresh_cookie(response)
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user
