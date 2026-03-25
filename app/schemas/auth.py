import re
import uuid
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, field_validator


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _reject_html(value: str, field_name: str) -> str:
    """Reject any input containing HTML tags."""
    if _HTML_TAG_RE.search(value):
        raise ValueError(f"{field_name} must not contain HTML tags")
    return value


class EventType(str, Enum):
    birthday = "birthday"
    wedding = "wedding"
    graduation = "graduation"
    corporate = "corporate"
    other = "other"


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(..., min_length=8, max_length=128)
    event_name: str = Field(..., min_length=1, max_length=100)
    event_type: EventType

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()
        _reject_html(v, "Username")
        if not v.replace("_", "").isalnum():
            raise ValueError("Username can only contain letters, numbers, and underscores")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number")
        return v

    @field_validator("event_name")
    @classmethod
    def validate_event_name(cls, v: str) -> str:
        v = v.strip()
        _reject_html(v, "Event name")
        return v


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def strip_username(cls, v: str) -> str:
        return v.strip()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    event_name: str
    event_type: str
    event_token: str
    created_at: datetime

    model_config = {"from_attributes": True}
