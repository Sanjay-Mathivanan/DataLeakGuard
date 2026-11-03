from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DatasetHistoryItem(BaseModel):
    id: str
    event_type: str
    outcome: str
    details: dict | None = None
    created_at: datetime
    completed_at: datetime | None = None
    dataset_id: str
    dataset_name: str
    finding_id: str | None = None
    operation_id: str | None = None
    user_id: str | None = None
    failure_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DatasetHistoryPage(BaseModel):
    items: list[DatasetHistoryItem]
    total: int
    skip: int
    limit: int
