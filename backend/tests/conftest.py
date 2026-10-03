import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import app.db.session
from app.db.base import Base
from app.main import app as fastapi_app
from app.db.session import get_db
from app.core.config import settings

SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///./test_test.db"

engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def test_db():
    print("test_db fixture: entering")
    # Store original TestingSessionLocal to restore later
    original_testing_session_local = app.db.session.TestingSessionLocal
    # Replace the TestingSessionLocal in the session module with our test-bound sessionmaker
    app.db.session.TestingSessionLocal = TestingSessionLocal
    # Create the tables
    print("About to create tables. Tables in metadata:", list(Base.metadata.tables.keys()))
    Base.metadata.create_all(bind=engine)
    print("After create_all. Tables in metadata:", list(Base.metadata.tables.keys()))
    yield
    # Drop tables after test
    print("Dropping tables...")
    Base.metadata.drop_all(bind=engine)
    # Restore original TestingSessionLocal
    app.db.session.TestingSessionLocal = original_testing_session_local
    print("test_db fixture: exiting")


@pytest.fixture(scope="function")
def client(test_db):
    print("client fixture: entering")
    def override_get_db():
        try:
            db = TestingSessionLocal()
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()
    print("client fixture: exiting")