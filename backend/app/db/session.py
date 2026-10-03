from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .base import Base
from app.core.config import settings

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
TestingSessionLocal = SessionLocal  # for tests

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()