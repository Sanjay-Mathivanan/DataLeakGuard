from app.db import models, session
from app.utils.file_storage import ORIGINAL_DIR


def _upload(client, filename="mixed.csv"):
    response = client.post(
        "/api/v1/datasets",
        data={
            "name": "Generic profile fixture",
            "type": "tabular",
            "format": "CSV",
            "description": "Disposable API integration fixture",
        },
        files={
            "file": (
                filename,
                b"reading_value,category_label,recorded_at\n1.5,A,2025-01-01\n, B,invalid\n-2,A,2025-01-03\n4,A,2025-01-04\n5,C,2025-01-05\n6,C,\n",
                "text/csv",
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_and_detailed_profiling_endpoints_return_persisted_backend_statistics(client):
    dataset = _upload(client)

    assert dataset["profile"]["row_count"] == 6
    assert dataset["profile"]["total_missing_values"] == 2
    assert dataset["profile"]["duplicate_row_count"] == 0
    assert {item["kind"] for item in dataset["profile"]["column_profiles"]} == {
        "numeric",
        "categorical",
        "datetime",
    }

    profile_response = client.get(f"/api/v1/datasets/{dataset['id']}/profiling")
    assert profile_response.status_code == 200
    initial = profile_response.json()
    assert initial["dataset_id"] == dataset["id"]
    assert initial["source_file_sha256"] == dataset["file_sha256"]
    assert initial["profile"]["row_count"] == 6

    refresh_response = client.post(f"/api/v1/datasets/{dataset['id']}/profiling")
    assert refresh_response.status_code == 201
    refreshed = refresh_response.json()
    assert refreshed["profile"]["row_count"] == 6
    assert refreshed["profile"]["column_profiles"][0]["missing_count"] in {0, 1}
    assert refreshed["source_file_sha256"] == dataset["file_sha256"]

    persisted = client.get(f"/api/v1/datasets/{dataset['id']}")
    assert persisted.status_code == 200
    assert persisted.json()["profile"]["profiled_at"] == refreshed["generated_at"]
    history = client.get(f"/api/v1/datasets/{dataset['id']}/history")
    assert history.status_code == 200
    assert any(event["event_type"] == "dataset_profiling" for event in history.json())


def test_detailed_profiling_is_owner_scoped_and_rejects_unsupported_dataset_type(client, test_db):
    db = session.TestingSessionLocal()
    try:
        current_owner = db.query(models.User).filter_by(email="test-owner@example.test").first()
        foreign_owner = models.User(
            email="profile-private@example.test",
            display_name="Private owner",
            password_hash="test-only",
        )
        db.add(foreign_owner)
        db.commit()
        db.refresh(foreign_owner)
        private = models.Dataset(
            id="private-profile-dataset",
            name="Private",
            type="tabular",
            format="CSV",
            owner_user_id=foreign_owner.id,
        )
        image = models.Dataset(
            id="image-profile-dataset",
            name="Image archive",
            type="computer-vision",
            format="ZIP",
            owner_user_id=current_owner.id,
        )
        db.add_all([private, image])
        db.commit()
    finally:
        db.close()

    assert client.get("/api/v1/datasets/private-profile-dataset/profiling").status_code == 404
    assert client.get("/api/v1/datasets/image-profile-dataset/profiling").status_code == 422


def test_refresh_rejects_a_source_hash_mismatch(client):
    dataset = _upload(client)
    original_path = ORIGINAL_DIR / dataset["storage_filename"]
    original_path.write_bytes(original_path.read_bytes() + b"\n")

    stale_profile = client.get(f"/api/v1/datasets/{dataset['id']}/profiling")
    assert stale_profile.status_code == 409
    response = client.post(f"/api/v1/datasets/{dataset['id']}/profiling")
    assert response.status_code == 409
    assert "SHA-256" in response.json()["detail"]
