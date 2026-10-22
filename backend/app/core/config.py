from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "DataLeakGuard-CV"
    # Database
    DATABASE_URL: str = "sqlite:///./test.db"
    # CORS
    BACKEND_CORS_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:8000",
    ]
    # Upload settings
    MAX_UPLOAD_SIZE_MB: int = 100

    class Config:
        case_sensitive = True


settings = Settings()
