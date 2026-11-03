-- Forward-only migration. Apply with the project's migration runner; do not
-- run this file automatically during application startup.
CREATE TABLE model_artifacts (
    id VARCHAR PRIMARY KEY, owner_user_id VARCHAR NOT NULL REFERENCES users(id),
    name VARCHAR NOT NULL, version VARCHAR, storage_filename VARCHAR NOT NULL,
    original_filename VARCHAR NOT NULL, sha256 VARCHAR NOT NULL, size_bytes INTEGER NOT NULL,
    metadata_json JSON, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_model_artifacts_owner_user_id ON model_artifacts(owner_user_id);
CREATE TABLE provenance_records (
    id VARCHAR PRIMARY KEY, owner_user_id VARCHAR NOT NULL REFERENCES users(id),
    dataset_id VARCHAR NOT NULL REFERENCES datasets(id), metadata_json JSON NOT NULL,
    prediction_status VARCHAR NOT NULL DEFAULT 'no_prediction', created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_provenance_records_owner_user_id ON provenance_records(owner_user_id);
CREATE TABLE distribution_comparisons (
    id VARCHAR PRIMARY KEY, owner_user_id VARCHAR NOT NULL REFERENCES users(id),
    reference_dataset_id VARCHAR NOT NULL REFERENCES datasets(id),
    comparison_dataset_id VARCHAR NOT NULL REFERENCES datasets(id), metrics_json JSON NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE impact_metrics (
    id VARCHAR PRIMARY KEY, owner_user_id VARCHAR NOT NULL REFERENCES users(id),
    dataset_id VARCHAR NOT NULL REFERENCES datasets(id), metrics_json JSON NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE report_metadata (
    id VARCHAR PRIMARY KEY, owner_user_id VARCHAR NOT NULL REFERENCES users(id),
    dataset_id VARCHAR REFERENCES datasets(id), title VARCHAR NOT NULL, format VARCHAR NOT NULL,
    content_json JSON NOT NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
