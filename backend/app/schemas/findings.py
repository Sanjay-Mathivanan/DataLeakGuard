from pydantic import BaseModel, ConfigDict

from app.schemas.leakage import LeakageFindingRead


class FindingCounts(BaseModel):
    total: int
    open: int
    resolved: int
    low: int
    medium: int
    high: int
    other_severity: int
    status_counts: dict[str, int]
    detector_counts: dict[str, int]


class DatasetFindingPage(BaseModel):
    items: list[LeakageFindingRead]
    total: int
    skip: int
    limit: int
    dataset_summary: FindingCounts
    matching_summary: FindingCounts
    detector_summary: FindingCounts | None = None

    model_config = ConfigDict(from_attributes=True)
