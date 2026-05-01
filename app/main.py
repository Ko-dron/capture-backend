import traceback

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.middleware.security import SecurityHeadersMiddleware
from app.middleware.rate_limiter import RateLimiterMiddleware
from app.models.user import User
from app.routers import auth, qr, media, share

settings = get_settings()

app = FastAPI(
    title="Capture API",
    description="Event Photo & Video Platform API",
    version="1.0.0",
)

# Middleware stack (applied bottom-to-top: CORS -> Security -> Rate Limiter)
app.add_middleware(RateLimiterMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
origins = [
    "http://localhost:5173",
    "https://capture-i9wg.onrender.com",
    settings.FRONTEND_URL,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routers
app.include_router(auth.router)
app.include_router(qr.router)
app.include_router(media.router)
app.include_router(share.router)


@app.get("/")
async def root():
    return {"message": "Welcome to Capture API", "docs": "/docs"}


@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/api/debug/db")
async def debug_db(db: AsyncSession = Depends(get_db)):
    info: dict = {"db_url_scheme": settings.DATABASE_URL.split("://", 1)[0]}
    try:
        result = await db.execute(text("SELECT 1"))
        info["select_1"] = result.scalar()
    except Exception as e:
        info["select_1_error"] = f"{type(e).__name__}: {e}"
        info["select_1_trace"] = traceback.format_exc().splitlines()[-5:]
        return info
    try:
        result = await db.execute(select(User).limit(1))
        info["users_query"] = "ok"
        info["user_count_sample"] = "rows fetched" if result.scalars().first() is not None else "table empty"
    except Exception as e:
        info["users_query_error"] = f"{type(e).__name__}: {e}"
        info["users_trace"] = traceback.format_exc().splitlines()[-5:]
    return info
