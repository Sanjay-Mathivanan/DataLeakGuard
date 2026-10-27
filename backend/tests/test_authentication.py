import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db import leakage_models, models
from app.db.session import get_db
from app.main import app
from app.services.activity_service import record_user_event
from app.core.auth_rate_limit import reset_auth_rate_limits
from app.core.config import settings


@pytest.fixture
def auth_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    reset_auth_rate_limits()
    with TestClient(app) as client:
        client.headers.update({"Origin": "http://localhost:3000"})
        client.db_session_factory = session_factory
        yield client
    app.dependency_overrides.pop(get_db, None)
    reset_auth_rate_limits()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_register_login_csrf_profile_and_revocable_logout(auth_client):
    response = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "  Person@Example.com ",
            "display_name": "Test Person",
            "password": "a-strong-password-123",
        },
    )
    assert response.status_code == 201
    assert response.json()["user"]["email"] == "person@example.com"
    assert "password_hash" not in response.json()["user"]
    assert "httponly" in response.headers["set-cookie"].lower()
    assert auth_client.cookies.get("dlg_session")
    csrf_token = auth_client.cookies.get("dlg_csrf")

    current = auth_client.get("/api/v1/auth/me")
    assert current.status_code == 200
    # /me rotates the CSRF token so a token from a prior login response cannot
    # be reused after a refresh.
    csrf_token = current.json()["csrf_token"]
    assert auth_client.patch(
        "/api/v1/auth/profile",
        json={"email": "new@example.com", "display_name": "Updated"},
    ).status_code == 403

    updated = auth_client.patch(
        "/api/v1/auth/profile",
        headers={"X-CSRF-Token": csrf_token},
        json={"email": "new@example.com", "display_name": "Updated"},
    )
    assert updated.status_code == 200
    assert updated.json()["email"] == "new@example.com"

    logout = auth_client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert logout.status_code == 204
    assert auth_client.get("/api/v1/auth/me").status_code == 401

    login = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "NEW@example.com", "password": "a-strong-password-123"},
    )
    assert login.status_code == 200
    assert auth_client.get("/api/v1/auth/me").status_code == 200


def test_registration_rejects_duplicate_and_weak_password(auth_client):
    payload = {
        "email": "duplicate@example.com",
        "display_name": "First",
        "password": "a-strong-password-123",
    }
    assert auth_client.post("/api/v1/auth/register", json=payload).status_code == 201
    duplicate = auth_client.post(
        "/api/v1/auth/register",
        json={**payload, "email": "DUPLICATE@example.com"},
    )
    assert duplicate.status_code == 409
    weak = auth_client.post(
        "/api/v1/auth/register",
        json={**payload, "email": "other@example.com", "password": "short"},
    )
    assert weak.status_code == 422
    bad_login = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "duplicate@example.com", "password": "wrong-password"},
    )
    assert bad_login.status_code == 401


def test_legacy_datasets_and_resources_are_isolated_between_users(auth_client):
    owner_response = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner@example.com",
            "display_name": "Owner",
            "password": "owner-password-long",
        },
    )
    owner_id = owner_response.json()["user"]["id"]
    factory = auth_client.db_session_factory
    db = factory()
    owned = models.Dataset(
        id="owned-dataset",
        owner_user_id=owner_id,
        name="Owned dataset",
        type="tabular",
        format="CSV",
        status="Uploaded",
        storage_filename="owned.csv",
        file_sha256="a" * 64,
    )
    legacy = models.Dataset(
        id="legacy-dataset",
        owner_user_id=None,
        name="Legacy dataset",
        type="tabular",
        format="CSV",
        status="Uploaded",
        storage_filename="legacy.csv",
        file_sha256="b" * 64,
    )
    db.add_all([owned, legacy])
    db.flush()
    finding = leakage_models.LeakageFinding(
        id="owned-finding",
        dataset_id="owned-dataset",
        finding_type="exact_duplicate",
        severity="high",
        status="open",
        description="test",
        evidence={"row_indices": [0, 1]},
    )
    operation = models.RepairRecord(
        id="owned-operation",
        dataset_id="owned-dataset",
        finding_id="owned-finding",
        operation_type="repair",
        status="completed",
        input_file_sha256="a" * 64,
        output_filename="missing.csv",
        output_file_sha256="c" * 64,
    )
    db.add_all([finding, operation])
    db.commit()
    db.close()

    assert [item["id"] for item in auth_client.get("/api/v1/datasets").json()] == [
        "owned-dataset"
    ]
    assert auth_client.get("/api/v1/datasets/legacy-dataset").status_code == 404

    # Login as a second account in the same client jar, replacing the first session.
    second = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "second@example.com",
            "display_name": "Second",
            "password": "second-password-long",
        },
    )
    assert second.status_code == 201
    assert auth_client.get("/api/v1/datasets/owned-dataset").status_code == 404
    assert auth_client.get("/api/v1/findings/owned-finding").status_code == 404
    assert auth_client.get("/api/v1/repairs/owned-operation").status_code == 404
    assert auth_client.get("/api/v1/operations/owned-operation/download").status_code == 404


def test_notifications_are_persistent_user_scoped_and_readable(auth_client):
    created = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "notify@example.com",
            "display_name": "Notify User",
            "password": "notification-password",
        },
    )
    user_id = created.json()["user"]["id"]
    db = auth_client.db_session_factory()
    record_user_event(
        db,
        user_id=user_id,
        event_type="analysis",
        outcome="completed",
        title="Analysis completed",
        message="Persisted event",
        deduplication_key="notify-test-event",
    )
    db.close()

    listing = auth_client.get("/api/v1/notifications")
    assert listing.status_code == 200
    notification_id = listing.json()[0]["id"]
    assert auth_client.get("/api/v1/notifications/unread-count").json() == {"unread_count": 1}
    headers = {"X-CSRF-Token": auth_client.cookies.get("dlg_csrf")}
    read = auth_client.post(
        f"/api/v1/notifications/{notification_id}/read",
        headers=headers,
    )
    assert read.status_code == 200
    assert read.json()["read_at"]
    assert auth_client.get("/api/v1/notifications/unread-count").json() == {"unread_count": 0}
    history = auth_client.get("/api/v1/account/history")
    assert history.status_code == 200
    assert history.json()[0]["event_type"] == "analysis"


def test_password_change_revokes_sessions(auth_client):
    auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "password@example.com",
            "display_name": "Password User",
            "password": "previous-password-123",
        },
    )
    response = auth_client.post(
        "/api/v1/auth/password",
        headers={"X-CSRF-Token": auth_client.cookies.get("dlg_csrf")},
        json={
            "current_password": "previous-password-123",
            "new_password": "replacement-password-456",
        },
    )
    assert response.status_code == 204
    assert auth_client.get("/api/v1/auth/me").status_code == 401
    assert auth_client.post(
        "/api/v1/auth/login",
        json={"email": "password@example.com", "password": "previous-password-123"},
    ).status_code == 401
    assert auth_client.post(
        "/api/v1/auth/login",
        json={"email": "password@example.com", "password": "replacement-password-456"},
    ).status_code == 200


def test_dashboard_summary_counts_only_authenticated_users_records(auth_client):
    first = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "dashboard-one@example.com",
            "display_name": "Dashboard One",
            "password": "dashboard-password-one",
        },
    )
    first_user_id = first.json()["user"]["id"]
    db = auth_client.db_session_factory()
    db.add(models.Dataset(
        id="dashboard-one-dataset",
        owner_user_id=first_user_id,
        name="One",
        type="tabular",
        format="CSV",
        status="Analyzed",
    ))
    db.flush()
    db.add(leakage_models.LeakageFinding(
        id="dashboard-one-finding",
        dataset_id="dashboard-one-dataset",
        finding_type="exact_duplicate",
        severity="critical",
        status="open",
        description="Persisted",
        evidence={},
    ))
    db.commit()
    db.close()
    assert auth_client.get("/api/v1/dashboard/summary").json()["finding_count"] == 1

    second = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "dashboard-two@example.com",
            "display_name": "Dashboard Two",
            "password": "dashboard-password-two",
        },
    )
    assert second.status_code == 201
    summary = auth_client.get("/api/v1/dashboard/summary").json()
    assert summary["dataset_count"] == 0
    assert summary["finding_count"] == 0
    assert summary["open_finding_count"] == 0
    assert summary["high_or_critical_finding_count"] == 0


def test_auth_origin_validation_and_referer_fallback(auth_client):
    payload = {
        "email": "origin@example.com",
        "display_name": "Origin",
        "password": "origin-password-long",
    }
    rejected = auth_client.post(
        "/api/v1/auth/register",
        headers={"Origin": "https://attacker.invalid"},
        json=payload,
    )
    assert rejected.status_code == 403
    rejected_login = auth_client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://attacker.invalid"},
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert rejected_login.status_code == 403
    assert auth_client.post(
        "/api/v1/auth/register",
        headers={"Referer": "http://localhost:3000/register?next=%2F"},
        json=payload,
    ).status_code == 201


@pytest.mark.parametrize(
    "path",
    ["/api/v1/auth/login", "/api/v1/auth/register"],
)
@pytest.mark.parametrize(
    "origin",
    ["http://localhost:3000", "http://127.0.0.1:3000"],
)
def test_auth_preflight_allows_vite_development_origins(auth_client, path, origin):
    response = auth_client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )

    assert response.status_code in {200, 204}
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.parametrize(
    "path",
    ["/api/v1/auth/login", "/api/v1/auth/register"],
)
def test_auth_preflight_rejects_unapproved_origin(auth_client, path):
    response = auth_client.options(
        path,
        headers={
            "Origin": "https://attacker.invalid",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_login_and_registration_reach_auth_endpoints_from_loopback_dev_origin(
    auth_client,
):
    origin = "http://127.0.0.1:3000"
    payload = {
        "email": "cors-user@example.test",
        "display_name": "CORS Test",
        "password": "cors-test-password-long",
    }
    registered = auth_client.post(
        "/api/v1/auth/register",
        headers={"Origin": origin},
        json=payload,
    )
    assert registered.status_code == 201, registered.text

    logged_in = auth_client.post(
        "/api/v1/auth/login",
        headers={"Origin": origin},
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert logged_in.status_code == 200, logged_in.text


def test_auth_endpoints_rate_limit_without_permanent_lockout(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_LOGIN_RATE_LIMIT", "2/minute")
    reset_auth_rate_limits()
    body = {"email": "unknown@example.com", "password": "wrong-password"}
    assert auth_client.post("/api/v1/auth/login", json=body).status_code == 401
    assert auth_client.post("/api/v1/auth/login", json=body).status_code == 401
    limited = auth_client.post("/api/v1/auth/login", json=body)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0

    monkeypatch.setattr(settings, "AUTH_REGISTER_RATE_LIMIT", "1/hour")
    reset_auth_rate_limits()
    register = {
        "email": "limited@example.com",
        "display_name": "Limited",
        "password": "limited-password-long",
    }
    assert auth_client.post("/api/v1/auth/register", json=register).status_code == 201
    limited_register = auth_client.post(
        "/api/v1/auth/register",
        json={**register, "email": "another@example.com"},
    )
    assert limited_register.status_code == 429
    assert int(limited_register.headers["retry-after"]) > 0


def test_cookie_secure_configuration_and_password_hash(auth_client, monkeypatch):
    local_response = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "local-cookie@example.com",
            "display_name": "Local",
            "password": "local-cookie-password",
        },
    )
    local_cookie = next(
        cookie for cookie in local_response.headers.get_list("set-cookie")
        if cookie.startswith("dlg_session=")
    )
    assert "httponly" in local_cookie.lower()
    assert "secure" not in local_cookie.lower()

    monkeypatch.setattr(settings, "AUTH_COOKIE_SECURE", True)
    response = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "secure@example.com",
            "display_name": "Secure",
            "password": "secure-password-long",
        },
    )
    assert response.status_code == 201
    session_cookie = next(
        cookie for cookie in response.headers.get_list("set-cookie")
        if cookie.startswith("dlg_session=")
    )
    assert "httponly" in session_cookie.lower()
    assert "secure" in session_cookie.lower()
    db = auth_client.db_session_factory()
    user = db.query(models.User).filter_by(email="secure@example.com").one()
    assert user.password_hash != "secure-password-long"
    assert user.password_hash.startswith("scrypt:")
    db.close()


def test_https_request_forces_secure_cookies(auth_client, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "AUTH_COOKIE_SECURE", False)
    monkeypatch.setattr(
        settings,
        "BACKEND_CORS_ORIGINS",
        [*settings.BACKEND_CORS_ORIGINS, "https://localhost:3000"],
    )
    with TestClient(app, base_url="https://localhost:3000") as https_client:
        response = https_client.post(
            "/api/v1/auth/register",
            headers={"Origin": "https://localhost:3000"},
            json={
                "email": "https-cookie@example.com",
                "display_name": "HTTPS",
                "password": "https-cookie-password",
            },
        )
    assert response.status_code == 201
    session_cookie = next(
        cookie for cookie in response.headers.get_list("set-cookie")
        if cookie.startswith("dlg_session=")
    )
    assert "secure" in session_cookie.lower()


def test_cross_user_access_denied_for_owned_resources_and_writes(auth_client):
    owner = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "resource-owner@example.com",
            "display_name": "Owner",
            "password": "owner-password-long",
        },
    ).json()["user"]
    db = auth_client.db_session_factory()
    dataset = models.Dataset(
        id="private-dataset",
        owner_user_id=owner["id"],
        name="Private",
        type="tabular",
        format="CSV",
        status="Analyzed",
        storage_filename="private.csv",
    )
    finding = leakage_models.LeakageFinding(
        id="private-finding",
        dataset_id=dataset.id,
        finding_type="exact_duplicate",
        severity="high",
        status="open",
        description="Private finding",
        evidence={"row_indices": [0, 1]},
    )
    repair = models.RepairRecord(
        id="private-repair",
        dataset_id=dataset.id,
        finding_id=finding.id,
        operation_type="repair",
        status="completed",
        input_file_sha256="a" * 64,
        output_filename="private-output.csv",
        output_file_sha256="b" * 64,
    )
    quarantine = models.RepairRecord(
        id="private-quarantine",
        dataset_id=dataset.id,
        finding_id=finding.id,
        operation_type="quarantine",
        status="completed",
        input_file_sha256="a" * 64,
        output_filename="private-quarantine.csv",
        output_file_sha256="c" * 64,
    )
    db.add(dataset)
    db.flush()
    db.add(finding)
    db.flush()
    db.add_all([repair, quarantine])
    db.commit()
    event = record_user_event(
        db,
        user_id=owner["id"],
        dataset_id=dataset.id,
        finding_id=finding.id,
        operation_id=repair.id,
        event_type="repair",
        outcome="completed",
        title="Private event",
        message="Private notification",
    )
    notification_id = db.query(models.Notification).filter_by(
        user_id=owner["id"]
    ).one().id
    db.close()

    second = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "resource-other@example.com",
            "display_name": "Other",
            "password": "other-password-long",
        },
    )
    assert second.status_code == 201
    headers = {"X-CSRF-Token": second.json()["csrf_token"]}

    assert auth_client.get("/api/v1/datasets").json() == []
    assert auth_client.get("/api/v1/datasets/private-dataset").status_code == 404
    assert auth_client.get("/api/v1/datasets/private-dataset/profile").status_code == 404
    assert auth_client.get("/api/v1/findings/private-finding").status_code == 404
    assert auth_client.get(
        "/api/v1/findings/private-finding/evidence"
    ).status_code == 404
    assert auth_client.get(
        "/api/v1/datasets/private-dataset/findings"
    ).status_code == 404
    assert auth_client.post(
        "/api/v1/datasets/private-dataset/analyze/leakage",
        headers=headers,
    ).status_code == 404
    assert auth_client.delete(
        "/api/v1/datasets/private-dataset",
        headers=headers,
    ).status_code == 404
    assert auth_client.post(
        "/api/v1/findings/private-finding/repair",
        headers=headers,
    ).status_code == 404
    assert auth_client.post(
        "/api/v1/datasets/private-dataset/repairs/combined",
        headers=headers,
        json={"selected_finding_ids": ["private-finding"]},
    ).status_code == 404
    assert auth_client.post(
        "/api/v1/findings/private-finding/quarantine",
        headers=headers,
    ).status_code == 404
    assert auth_client.get(
        "/api/v1/datasets/private-dataset/repairs"
    ).status_code == 404
    assert auth_client.get(
        "/api/v1/datasets/private-dataset/quarantines"
    ).status_code == 404
    assert auth_client.get("/api/v1/repairs/private-repair").status_code == 404
    assert auth_client.get(
        "/api/v1/quarantines/private-quarantine"
    ).status_code == 404
    assert auth_client.get(
        "/api/v1/operations/private-repair/download"
    ).status_code == 404
    assert auth_client.get(
        "/api/v1/datasets/private-dataset/history"
    ).status_code == 404
    assert auth_client.get("/api/v1/account/history").json() == []
    assert auth_client.get("/api/v1/notifications").json() == []
    assert auth_client.get(
        "/api/v1/notifications/unread-count"
    ).json() == {"unread_count": 0}
    assert auth_client.post(
        f"/api/v1/notifications/{notification_id}/read",
        headers=headers,
    ).status_code == 404
    assert auth_client.post(
        "/api/v1/notifications/read-all",
        headers=headers,
    ).status_code == 200

    db = auth_client.db_session_factory()
    assert db.query(models.AuditEvent).filter_by(id=event.id).one().user_id == owner["id"]
    assert db.query(models.Notification).filter_by(id=notification_id).one().read_at is None
    db.close()
