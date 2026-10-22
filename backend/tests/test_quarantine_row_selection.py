import pandas as pd

from app.utils.file_storage import QUARANTINE_DIR


def _upload_dataset(client, name, dataframe):
    response = client.post(
        "/api/v1/datasets",
        data={
            "name": name,
            "type": "tabular",
            "format": "CSV",
            "description": "row-index regression test",
        },
        files={"file": ("rows.csv", dataframe.to_csv(index=False).encode(), "text/csv")},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _quarantine_finding(client, finding_id):
    response = client.post(f"/api/v1/findings/{finding_id}/quarantine")
    assert response.status_code == 201
    result = response.json()
    return result, pd.read_csv(QUARANTINE_DIR / result["output_file"])


def test_contamination_quarantine_uses_source_indices_after_split_filtering(client, test_db):
    dataframe = pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5, 6],
            "sample": ["shared", "shared", "shared", "shared", "shared", "other"],
            "feature": [10, 10, 10, 10, 10, 20],
            "split": ["train", None, "validation", "test", "   ", "train"],
        }
    )
    dataset_id = _upload_dataset(client, "contamination row indices", dataframe)

    analysis = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage?split_column=split"
    )
    assert analysis.status_code == 200
    finding = next(
        finding
        for finding in analysis.json()["findings"]
        if finding["finding_type"] == "train_test_contamination"
    )
    assert finding["evidence"]["row_indices"] == {
        "test": [3],
        "train": [0],
        "validation": [2],
    }

    quarantine, quarantined_rows = _quarantine_finding(client, finding["id"])
    assert quarantine["quarantine_info"]["row_indices"] == [0, 2, 3]
    assert quarantined_rows["id"].tolist() == [1, 3, 4]


def test_entity_overlap_quarantine_uses_source_indices_after_missing_value_filtering(client, test_db):
    dataframe = pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5, 6, 7, 8],
            "entity": ["P1", None, "P1", "P1", "P1", "P2", "   ", "P1"],
            "split": ["train", "train", None, "test", "validation", "train", "test", "   "],
            "value": [
                "train",
                "missing-entity",
                "missing-split",
                "test",
                "validation",
                "other",
                "empty-entity",
                "empty-split",
            ],
        }
    )
    dataset_id = _upload_dataset(client, "entity overlap row indices", dataframe)

    analysis = client.post(
        f"/api/v1/datasets/{dataset_id}/analyze/leakage"
        "?entity_column=entity&split_column=split"
    )
    assert analysis.status_code == 200
    finding = next(
        finding
        for finding in analysis.json()["findings"]
        if finding["finding_type"] == "entity_overlap"
    )
    assert finding["evidence"]["row_indices"] == {
        "test": [3],
        "train": [0],
        "validation": [4],
    }

    quarantine, quarantined_rows = _quarantine_finding(client, finding["id"])
    assert quarantine["quarantine_info"]["row_indices"] == [0, 3, 4]
    assert quarantined_rows["id"].tolist() == [1, 4, 5]
