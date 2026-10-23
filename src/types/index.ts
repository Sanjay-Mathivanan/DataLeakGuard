export type DatasetType = 'tabular' | 'computer-vision';

export type IntegrityStatus = 'Clean' | 'Review' | 'Issues Found' | 'Processing';

export type SeverityLevel = 'Low' | 'Medium' | 'High' | 'Critical';

export type RiskLevel = 'LOW' | 'MODERATE' | 'ELEVATED' | 'HIGH' | 'CRITICAL';

export type VerificationState = 'Verified' | 'Changed' | 'Review Required' | 'Not Available';

export interface CVStats {
  imageCount: number;
  classes: string[];
  annotationsCount: number;
  resolutionDistribution: { label: string; count: number }[];
  nearDuplicatePairsCount: number;
}

/** Basic image-ZIP profile fields returned by the backend profiler. */
export interface DatasetProfile {
  imageCount?: number;
  format?: string;
  widthMin?: number | null;
  widthMax?: number | null;
  heightMin?: number | null;
  heightMax?: number | null;
  sampledImages?: number;
  error?: string;
}

export interface Dataset {
  id: string;
  name: string;
  type: DatasetType;
  format: 'CSV' | 'XLSX' | 'ZIP' | 'YOLO' | 'COCO';
  sampleCount?: number | null;
  featureCount?: number | null;
  classCount?: number | null;
  status?: string | null;
  issuesCount: number;
  uploadedAt: string;
  lastAnalysis?: string | null;
  description?: string | null;
  previewRows?: Record<string, string | number>[];
  columns?: { name: string; type: string; missingCount: number; uniqueCount: number }[];
  cvStats?: CVStats | null;
  profile?: DatasetProfile | null;
}

export type LeakageType = 
  | 'duplicate'
  | 'entity'
  | 'target'
  | 'temporal'
  | 'preprocessing'
  | 'contamination'
  | 'cv-near-duplicate'
  | 'label-anomaly'
  | 'ood-sample';

export interface LeakageFinding {
  id: string;
  datasetId: string;
  type: LeakageType;
  trainSampleId: string;
  testSampleId: string;
  similarity: number; // 0 to 100
  evidence: string;
  severity: SeverityLevel;
  status: 'Detected' | 'Under Review' | 'Repaired' | 'Quarantined';
  explanation: string;
  trainRecordDetails?: Record<string, string | number>;
  testRecordDetails?: Record<string, string | number>;
  featureImpact?: string[];
}

export interface LeakageCategoryOverview {
  type: LeakageType;
  label: string;
  status: 'Detected' | 'Not Detected' | 'Review Required';
  findingsCount: number;
  confidence: number;
  severity: SeverityLevel;
  shortExplanation: string;
}

/** Finding fields returned by the persisted backend findings API. */
export interface PersistedFinding {
  id: string;
  datasetId: string;
  findingType: string;
  severity: string;
  status: string;
  description: string;
  evidence: Record<string, unknown> | null;
  createdAt: string | null;
}

/** A count derived only from persisted findings; it does not imply detector coverage. */
export interface FindingCategorySummary {
  findingType: string;
  label: string;
  findingsCount: number;
}

export interface AnalysisStage {
  id: number;
  name: string;
  status: 'not_run' | 'needs_configuration' | 'running' | 'completed' | 'failed' | 'skipped';
  findingsCount?: number;
  description: string;
}

export interface AnalysisResult {
  id: string;
  datasetId: string;
  timestamp: string;
  stages: AnalysisStage[];
  findings: PersistedFinding[];
  summary: {
    totalFindings: number;
    duplicateFindings: number;
  };
}

export type FindingOperationType = 'repair' | 'quarantine';

export interface SkippedRepairFinding {
  findingId: string;
  reason: string;
}

export interface CombinedRepairMetadata {
  selectedFindingIds: string[];
  appliedFindingIds: string[];
  skippedFindings: SkippedRepairFinding[];
  originalRowCount: number;
  finalRowCount: number;
  duplicateRowsRemoved: number;
}

/** Fields returned by the persisted repair/quarantine operation APIs. */
export interface DatasetOperationRecord {
  id: string;
  datasetId: string;
  findingId?: string | null;
  operationType: string;
  status: string;
  inputFile?: string | null;
  inputFileSha256?: string | null;
  outputFilename?: string | null;
  outputFileSha256?: string | null;
  affectedRows?: number | null;
  operationMetadata?: CombinedRepairMetadata | null;
  createdAt?: string | null;
  completedAt?: string | null;
}

export interface Model {
  id: string;
  name: string;
  version: string;
  format: 'ONNX' | 'PyTorch' | 'TorchScript';
  sha256: string;
  status: VerificationState;
  lastVerified: string;
  architecture: string;
  parameters: string;
  framework: string;
  uploadedAt: string;
  referenceHash: string;
  fingerprintMatch: boolean;
  behaviorDriftScore: number; // 0 to 1
  referenceBehaviors: { testInput: string; expectedOutput: string; actualOutput: string; match: boolean }[];
}

export interface BoundingBox {
  label: string;
  box: [number, number, number, number]; // [x, y, w, h] in %
  confidence: number;
}

export interface InferencePrediction {
  label: string;
  confidence: number;
  secondaryClass?: string;
  secondaryConfidence?: number;
  boundingBoxes?: BoundingBox[];
}

export interface InferenceRecord {
  id: string;
  timestamp: string;
  modelId: string;
  modelName: string;
  inputHash: string;
  outputHash: string;
  configHash: string;
  nonce: string;
  sequenceNumber: number;
  digitalSignature: string;
  verificationStatus: 'Verified' | 'Tampered' | 'Replay Detected';
  prediction: InferencePrediction;
  inputMetadata: {
    filename: string;
    dimensions: string;
    sizeKb: number;
    preprocessingConfig: string;
  };
  tamperedFields?: string[];
}

export interface DistributionShift {
  id: string;
  referenceDatasetId: string;
  currentDatasetId: string;
  overallShiftDetected: boolean;
  shiftLevel: 'No Significant Shift' | 'Potential Shift' | 'Review Required';
  psiScore: number; // Population Stability Index
  wassersteinDistance: number;
  oodRate: number; // percentage
  classBalanceShift: {
    className: string;
    referencePct: number;
    currentPct: number;
  }[];
  featureShifts: {
    featureName: string;
    driftScore: number;
    threshold: number;
    status: 'Nominal' | 'Shift Detected' | 'Requires Review';
  }[];
}

export interface MetricComparison {
  metric: string;
  contaminated: number;
  corrected: number;
  difference: number;
  percentageInflation: number;
}

export interface ImpactAnalysis {
  datasetId: string;
  modelName: string;
  taskType: string;
  metrics: MetricComparison[];
  evaluationInflationSummary: {
    accuracyDifference: number;
    f1Difference: number;
    rocAucDifference: number;
    statement: string;
    nuance: string;
  };
}

export interface AssuranceReport {
  id: string;
  title: string;
  datasetId: string;
  datasetName: string;
  modelId: string;
  modelName: string;
  createdAt: string;
  assessmentStatus: 'REVIEW REQUIRED' | 'POTENTIALLY ACCEPTABLE' | 'QUARANTINE RECOMMENDED';
  disposition: 'ACCEPT' | 'REVIEW' | 'QUARANTINE';
  confidenceScore: number;
  projectDefinedRisk: 'LOW' | 'MODERATE' | 'ELEVATED' | 'HIGH';
  executiveSummary: string;
  findingsCount: {
    critical: number;
    high: number;
    medium: number;
    low: number;
  };
  sections: {
    datasetIntegrity: string;
    leakageFindings: string;
    datasetAnomalies: string;
    modelIntegrity: string;
    inferenceProvenance: string;
    distributionShift: string;
    performanceImpact: string;
    evidence: string;
    riskAssessment: string;
    limitations: string[];
    recommendedDisposition: string;
  };
}

export interface Activity {
  id: string;
  type: 'dataset_analyzed' | 'model_verified' | 'leakage_detected' | 'provenance_verified' | 'report_generated' | 'repair_completed';
  title: string;
  description: string;
  timestamp: string;
  targetId?: string;
  severity?: SeverityLevel;
}
