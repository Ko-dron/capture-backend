from pydantic_settings import BaseSettings
from functools import lru_cache


def _normalize_db_url(url: str) -> str:
    # Render's managed Postgres exposes URLs as postgres://... but SQLAlchemy
    # needs the explicit asyncpg driver.
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/capture"
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    FRONTEND_URL: str = "http://localhost:5173"

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }

    def model_post_init(self, __context) -> None:
        self.DATABASE_URL = _normalize_db_url(self.DATABASE_URL)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
