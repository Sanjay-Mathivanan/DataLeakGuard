import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session as OrmSession, sessionmaker

import app.db.session
from app.api.identity import get_current_user
from app.core.auth_rate_limit import reset_auth_rate_limits
from app.db.base import Base
from app.db.models import Dataset, User
from app.main import app as fastapi_app
from app.db.session import get_db
from app.utils import file_storage


_TEST_FIXTURE_OWNER_ID = None


@event.listens_for(OrmSession, "before_flush")
def _assign_test_fixture_owner(session, flush_context, instances):
    """Give legacy API tests an owner without changing production behavior."""
    owner_id = session.info.get("test_fixture_owner_user_id") or _TEST_FIXTURE_OWNER_ID
    if owner_id:
        for item in session.new:
            if isinstance(item, Dataset) and item.owner_user_id is None:
                item.owner_user_id = owner_id


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Route every imported storage constant into this test's private folder."""
    original_dir = file_storage.ORIGINAL_DIR
    processed_dir = file_storage.PROCESSED_DIR
    quarantine_dir = file_storage.QUARANTINE_DIR
    base = tmp_path / "storage"
    paths = {
        original_dir: base / "original",
        processed_dir: base / "processed",
        quarantine_dir: base / "quarantine",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)

    # Constants are imported by both application services and tests at module
    # import time. Patch every such reference so no test can reach repository
    # storage through a stale imported Path.
    for module in tuple(sys.modules.values()):
        namespace = getattr(module, "__dict__", None)
        if not namespace:
            continue
        for name, value in tuple(namespace.items()):
            if name in {"ORIGINAL_DIR", "PROCESSED_DIR", "QUARANTINE_DIR"}:
                replacement = paths.get(value)
                if replacement is not None:
                    monkeypatch.setattr(module, name, replacement, raising=False)

    return paths


@pytest.fixture
def test_db(tmp_path, monkeypatch, isolated_storage):
    """Use a fresh per-test SQLite file; never use project databases."""
    global _TEST_FIXTURE_OWNER_ID
    database_path = tmp_path / "test.sqlite"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(app.db.session, "TestingSessionLocal", factory)

    Base.metadata.create_all(bind=engine)
    db = factory()
    test_user = User(
        email="test-owner@example.test",
        display_name="Test Owner",
        password_hash="test-only",
    )
    db.add(test_user)
    db.commit()
    db.refresh(test_user)
    db.close()
    _TEST_FIXTURE_OWNER_ID = test_user.id

    yield

    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    _TEST_FIXTURE_OWNER_ID = None


@pytest.fixture
def client(test_db, monkeypatch):
    db_factory = app.db.session.TestingSessionLocal
    db = db_factory()
    test_user = db.query(User).filter(User.email == "test-owner@example.test").first()
    db.close()

    def override_get_db():
        db = db_factory()
        try:
            db.info["test_fixture_owner_user_id"] = test_user.id
            yield db
        finally:
            db.close()

    overrides_before = dict(fastapi_app.dependency_overrides)
    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_user] = lambda: test_user
    reset_auth_rate_limits()
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()
    fastapi_app.dependency_overrides.update(overrides_before)
    reset_auth_rate_limits()
