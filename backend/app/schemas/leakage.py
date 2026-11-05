from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
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
    split_strategy: Literal["existing", "generated", "none"] = "none"
    split_configuration: Dict[str, Any] = Field(default_factory=dict)
    skipped_detectors: List[str] = Field(default_factory=list)
    split_explanation: Optional[str] = None
    analysis_configuration: Dict[str, Any] = Field(default_factory=dict)
    detector_applicability: Dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "from_attributes": True,
    }
