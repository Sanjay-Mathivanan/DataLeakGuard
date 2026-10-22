from app.schemas.evidence import EvidenceResponse


def create_evidence_response(finding, dataset) -> EvidenceResponse:
    return EvidenceResponse(
        finding_id=finding.id,
        dataset_id=finding.dataset_id,
        finding_type=finding.finding_type,
        severity=finding.severity,
        status=finding.status,
        source_file=getattr(dataset, 'storage_filename', None),
        source_file_sha256=getattr(dataset, 'file_sha256', None),
        detector_evidence=getattr(finding, 'evidence', None),
    )
