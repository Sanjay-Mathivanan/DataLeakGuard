from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class LeakageFindingBase(BaseModel):
    id: str
    dataset_id: str
    finding_type: str
    severity: str
    status: str
    description: str
    evidence: Dict[str, Any]
    created_at: Optional[datetime] = None

    model_config = {
        "from_attributes": True,
    }


class LeakageFindingRead(LeakageFindingBase):
    pass


class LeakageAnalysisResponse(BaseModel):
    dataset_id: str
    rows_examined: int
    duplicate_group_count: int
    duplicated_row_count: int
    findings: List[LeakageFindingRead]

    model_config = {
        "from_attributes": True,
    }