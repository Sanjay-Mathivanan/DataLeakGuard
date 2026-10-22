from pydantic import BaseModel
from typing import Dict, Any, Optional


class EvidenceResponse(BaseModel):
    finding_id: str
    dataset_id: str
    finding_type: str
    severity: str
    status: str
    source_file: Optional[str] = None
    source_file_sha256: Optional[str] = None
    detector_evidence: Optional[Dict[str, Any]] = None
