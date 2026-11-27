"""Application settings loaded from environment variables and .env."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings for the backend.

    Secrets are read from the environment or a local .env file. They are never
    written in source code. A real Gemini key is not needed to start the app.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = "sqlite:///./data/ai_study_buddy.db"

    jwt_secret_key: str = Field(..., min_length=1)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=60, gt=0)

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    backend_base_url: str = "http://127.0.0.1:8000"
    frontend_origin: str = "http://localhost:8501"

    max_upload_mb: int = Field(default=5, gt=0)
    max_source_chars: int = Field(default=30_000, gt=0)

    @property
    def max_upload_bytes(self) -> int:
        """Return the upload limit in bytes for file-reading checks."""
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return cached settings so the .env file is read once per process."""
    return Settings()
