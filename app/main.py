from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.middleware.security import SecurityHeadersMiddleware
from app.middleware.rate_limiter import RateLimiterMiddleware
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
