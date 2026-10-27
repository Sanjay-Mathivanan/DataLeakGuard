from limits.storage import storage_from_string
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "DataLeakGuard-CV"
    # Database
    DATABASE_URL: str = "sqlite:///./test.db"
    # CORS
    BACKEND_CORS_ORIGINS: list = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:8000",
    ]
    # Upload settings
    MAX_UPLOAD_SIZE_MB: int = 100
    # Keep False only for local HTTP development. HTTPS requests always receive
    # Secure cookies; TLS-terminating deployments should also set this to True.
    AUTH_SESSION_TTL_HOURS: int = 12
    AUTH_COOKIE_SECURE: bool = False
    AUTH_LOGIN_RATE_LIMIT: str = "5/minute"
    AUTH_REGISTER_RATE_LIMIT: str = "3/hour"
    # Memory storage is suitable for local single-process development. Set a
    # shared limits-compatible URI for multi-worker/multi-instance deployments.
    AUTH_RATE_LIMIT_STORAGE_URI: str = "memory://"

    @field_validator("AUTH_RATE_LIMIT_STORAGE_URI")
    @classmethod
    def validate_auth_rate_limit_storage_uri(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("AUTH_RATE_LIMIT_STORAGE_URI must not be empty")
        try:
            # Validate that limits recognizes the URI and has its provider
            # installed. The limiter constructs its own runtime storage below.
            storage_from_string(value)
        except Exception:
            raise ValueError(
                "AUTH_RATE_LIMIT_STORAGE_URI must identify an available limits storage backend"
            ) from None
        return value

    class Config:
        case_sensitive = True


settings = Settings()
