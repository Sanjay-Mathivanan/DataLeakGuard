from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from .base import Base
from app.core.config import settings

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite disables FK enforcement by default; enable it per connection."""
    if dbapi_connection.__class__.__module__.split(".", 1)[0] != "sqlite3":
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
TestingSessionLocal = SessionLocal  # for tests

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
