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
  targetColumn?: string | null;
  targetClassCounts?: Record<string, number>;
  splitColumn?: string | null;
  splitRowCounts?: Record<string, number>;
  datasetName?: string | null;
  rowCount?: number;
  columnCount?: number;
  fileFormat?: string | null;
  fileSizeBytes?: number | null;
  memoryUsageBytes?: number | null;
  duplicateRowCount?: number;
  totalMissingValues?: number;
  dataQuality?: {
    completenessPercentage?: number | null;
    duplicateRowPercentage?: number | null;
    summary?: string;
  };
  profiledAt?: string;
  columnProfiles?: Array<{
    name: string;
    dtype: string;
    kind: 'numeric' | 'categorical' | 'datetime' | 'other';
    nonNullCount: number;
    missingCount: number;
    missingPercentage: number | null;
    uniqueCount: number;
    duplicateValueCount: number;
    statistics: Record<string, unknown>;
  }>;
  analysisColumns?: {
    entityColumn?: string | null;
    entityColumns?: string[];
    contaminationKeyColumns?: string[];
    splitColumn?: string | null;
    targetColumn?: string | null;
    timeColumn?: string | null;
    temporalObjective?: 'future_prediction' | 'randomized_holdout' | null;
  };
  splitStrategy?: Record<string, unknown>;
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
  columns?: {
    name: string;
    type: string;
    kind?: 'numeric' | 'categorical' | 'datetime' | 'other';
    missingCount: number;
    nonNullCount?: number;
    missingPercentage?: number | null;
    uniqueCount: number;
    duplicateValueCount?: number;
    statistics?: {
      kind: 'numeric' | 'categorical' | 'datetime' | 'other';
      min?: number | null;
      max?: number | null;
      mean?: number | null;
      median?: number | null;
      standardDeviation?: number | null;
      quantiles?: Record<string, number | null>;
      zeroCount?: number;
      negativeCount?: number;
      topValues?: Array<{ value: string; count: number; percentage?: number }>;
      categoryCount?: number;
      categoriesTruncated?: boolean;
      mostFrequent?: { value: string; count: number; percentage: number } | null;
      rareCategories?: Array<{ value: string; count: number; percentage: number }>;
      minimum?: string | null;
      maximum?: string | null;
      invalidOrUnparseableCount?: number;
      missingTimestampCount?: number;
      timeRangeSeconds?: number | null;
    };
  }[];
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

export interface FindingCounts {
  total: number;
  open: number;
  resolved: number;
  low: number;
  medium: number;
  high: number;
  otherSeverity: number;
  statusCounts: Record<string, number>;
  detectorCounts: Record<string, number>;
}

export interface DatasetFindingPage {
  items: PersistedFinding[];
  total: number;
  skip: number;
  limit: number;
  datasetSummary: FindingCounts;
  matchingSummary: FindingCounts;
  detectorSummary?: FindingCounts;
}

export interface FindingPageFilters {
  skip?: number;
  limit?: number;
  search?: string;
  findingType?: string;
  severity?: string;
  status?: string;
}

export interface DatasetHistoryItem {
  id: string;
  eventType: string;
  outcome: string;
  details: Record<string, unknown> | null;
  createdAt: string;
  completedAt: string | null;
  datasetId: string;
  datasetName: string;
  findingId: string | null;
  operationId: string | null;
  userId: string | null;
  failureReason: string | null;
}

export interface DatasetHistoryPage {
  items: DatasetHistoryItem[];
  total: number;
  skip: number;
  limit: number;
}

export type DetectorColumnRole = 'target' | 'entity' | 'split' | 'timestamp';
export type RecommendationConfidence = 'high' | 'medium' | 'low' | 'not_recommended';

export interface ColumnRecommendationCandidate {
  columnName: string;
  role: DetectorColumnRole;
  score: number;
  confidence: RecommendationConfidence;
  explanation: string;
  supportingSignals: string[];
  warnings: string[];
  profile: {
    dataType: string;
    kind: string;
    uniqueCount: number | null;
    uniqueRatio: number | null;
    missingCount: number | null;
    missingRatio: number | null;
    sampleCount: number | null;
    recognizedSplitLabels: string[];
    datetimeParseableSampleCount: number;
    previewRowsConsidered: number;
  };
}

export interface ColumnRoleRecommendations {
  recommendation: ColumnRecommendationCandidate | null;
  candidates: ColumnRecommendationCandidate[];
  warnings: string[];
}

export interface ColumnRecommendationsResponse {
  profiledColumnCount: number;
  sampleCount: number | null;
  roles: Record<DetectorColumnRole, ColumnRoleRecommendations>;
  limitations: string[];
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
  splitStrategy?: 'existing' | 'generated' | 'none';
  splitConfiguration?: Record<string, unknown>;
  skippedDetectors?: string[];
  splitExplanation?: string | null;
  analysisConfiguration?: Record<string, unknown>;
  detectorApplicability?: Record<string, unknown>;
}

export interface SplitGenerationOperation {
  id: string;
  datasetId: string;
  operationType: string;
  status: string;
  splitColumn: string;
  testRatio: number;
  randomSeed: number;
  algorithm: string;
  rowCount: number;
  splitRowCounts: Record<string, number>;
  inputFileSha256: string;
  outputFileSha256: string;
  outputFilename: string;
  createdAt: string | null;
  completedAt: string | null;
  reused: boolean;
}

export type FindingOperationType = 'repair' | 'quarantine';

export interface SkippedRepairFinding {
  findingId: string;
  reason: string;
}

export interface CombinedRepairMetadata {
  selectedFindingIds?: string[];
  appliedFindingIds?: string[];
  skippedFindings: SkippedRepairFinding[];
  skippedFindingsRecorded?: boolean;
  originalRowCount?: number;
  finalRowCount?: number;
  duplicateRowsRemoved?: number;
  evidenceReferenceFindingIds?: string[];
  repairStrategy?: string;
  verificationStatus?: string;
  verification?: Record<string, unknown>;
}

export interface CombinedRepairPreview {
  datasetId: string;
  inputFileSha256: string;
  selectedFindingIds: string[];
  appliedFindingIds: string[];
  skippedFindings: SkippedRepairFinding[];
  originalRowCount: number;
  finalRowCount: number;
  duplicateRowsRemoved: number;
  affectedRowIndicesPreview?: number[];
  affectedRowIndicesCount?: number;
  affectedRowIndicesTruncated?: boolean;
  affectedRowIndicesSha256?: string;
  operationType: string;
  status: 'preview' | 'not_eligible';
  previewToken: string | null;
  explanation: string;
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

export type RemediationActionName =
  | 'exact_duplicate_keep_first'
  | 'quarantine_evidenced_rows'
  | 'rebuild_group_split'
  | 'exclude_target_features'
  | 'rebuild_chronological_split'
  | 'exclude_contaminated_copies'
  | 'review_only';

export interface RemediationActionRequest {
  action: RemediationActionName;
  selection_mode?: 'explicit' | 'all_eligible';
  finding_ids?: string[];
  finding_type?: string;
  entity_column?: string;
  entity_columns?: string[];
  split_column?: string;
  target_column?: string;
  feature_columns?: string[];
  time_column?: string;
  cutoff?: string;
  retained_partition?: string;
  test_ratio?: number;
  random_seed?: number;
  train_label?: string;
  test_label?: string;
}

export interface RemediationPlanActionSummary {
  action: RemediationActionName;
  selectionMode: 'explicit' | 'all_eligible';
  findingType: string | null;
  selectedCount: number;
  appliedCount: number;
  configuration: Record<string, unknown>;
}

export interface RemediationSkippedFinding {
  findingId: string;
  reason: string;
}

export interface RemediationPlanSummary {
  planId: string;
  version: number;
  executionStatus: string;
  userConfirmation: boolean;
  previewDigest: string;
  previewToken: string | null;
  originalFileSha256: string;
  finalFileSha256?: string;
  repairReportSha256?: string;
  manifestSha256?: string;
  quarantineOutputSha256?: string | null;
  originalRowCount: number;
  expectedFinalRowCount: number;
  finalRowCount?: number;
  originalColumnCount: number;
  expectedFinalColumnCount: number;
  finalColumnCount?: number;
  removedRowCount?: number;
  quarantinedRowCount?: number;
  affectedSourceRowPositionsPreview: number[];
  affectedSourceRowPositionsCount: number;
  affectedSourceRowPositionsTruncated: boolean;
  affectedSourceRowPositionsSha256: string;
  excludedFeatureColumns: string[];
  featureExclusionReasons?: Record<string, {
    reason: string;
    evidenceSignal?: string;
    findingIds?: string[];
  }>;
  analysisConfiguration?: Record<string, unknown>;
  remediationConfiguration?: Record<string, unknown>;
  detectorCountsBefore?: Record<string, Record<string, number>>;
  missingValueCountsBefore?: Record<string, number>;
  missingValueCountsAfter?: Record<string, number>;
  expectedOutputChange?: boolean;
  sourceOutputIdentical?: boolean;
  splitUpdateCount: number;
  unresolvedFindingsCount: number;
  unresolvedFindingIds?: string[];
  verifiedFindingIds?: string[];
  finalStatus?: string;
  verification?: Record<string, unknown>;
  completedAt?: string;
  failureReason?: string;
  selectedCount: number;
  selectedFindingIdsPreview: string[];
  selectedFindingIdsTruncated: boolean;
  detectorTypes: string[];
  appliedCount: number;
  skippedFindings: RemediationSkippedFinding[];
  skippedFindingsTruncated: boolean;
  splitConfigurations: Array<Record<string, unknown>>;
  actions: RemediationPlanActionSummary[];
}

export interface RemediationPlanRecord {
  id: string;
  datasetId: string;
  operationType: string;
  status: string;
  createdAt: string | null;
  completedAt: string | null;
  originalFileSha256: string | null;
  outputFileSha256: string | null;
  outputFilename: string | null;
  plan: RemediationPlanSummary;
  artifactHashes?: {
    dataset?: string;
    repairReport?: string;
    manifest?: string;
  };
}

export interface RemediationPlanPage {
  items: RemediationPlanRecord[];
  total: number;
  skip: number;
  limit: number;
}

export type ImputationMethod = 'mean' | 'median' | 'mode' | 'constant' | 'leave_missing';

export interface ImputationColumnSelection {
  column: string;
  method: ImputationMethod;
  constantValue?: string | number | boolean;
}

export interface ImputationRequest {
  splitColumn: string;
  trainingPartition: string;
  splitOperationId?: string;
  columns: ImputationColumnSelection[];
}

export interface ImputationStrategyResult {
  column: string;
  method: ImputationMethod;
  fittedValue: string | number | null;
  fitPartition: 'training_partition_only';
  trainingObservedCount: number;
  trainingMissingCount: number;
  sourceMissingCount: number;
}

export interface ImputationPreview {
  previewToken: string;
  sourceFileSha256: string;
  splitColumn: string;
  trainingPartition: string;
  fitRowCount: number;
  strategies: ImputationStrategyResult[];
  missingCountsBefore: Record<string, number>;
  missingCountsAfter: Record<string, number>;
  expectedRowCount: number;
  expectedColumnCount: number;
  protectedColumns: string[];
  confirmationRequired: true;
}

export interface ImputationOperation {
  id: string;
  datasetId: string;
  operationType: 'train_only_imputation';
  status: string;
  outputFilename: string | null;
  inputFileSha256: string | null;
  outputFileSha256: string | null;
  affectedRows: number;
  affectedColumns: string[];
  operationMetadata: Record<string, unknown>;
  createdAt: string | null;
  completedAt: string | null;
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
  confidence: number | null;
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
  verificationStatus: 'Verified' | 'Tampered' | 'Replay Detected' | 'Metadata persisted';
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
  psiScore: number | null; // Mean of persisted numeric-column PSI values, if available
  wassersteinDistance: number | null;
  oodRate: number | null; // percentage
  classBalanceShift: {
    className: string;
    referencePct: number;
    currentPct: number;
  }[];
  featureShifts: {
    featureName: string;
    driftScore: number;
    metricKind: 'PSI' | 'Distribution delta';
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

export interface PersistedReportDataset {
  id: string;
  name: string;
  format: string;
  sha256: string | null;
}

export interface PersistedReportImpact {
  findings_total?: number;
  findings_open?: number;
  findings_high_severity?: number;
  operations_total?: number;
  operations_completed?: number;
  affected_rows?: number;
}

export interface PersistedReportContent {
  datasets: PersistedReportDataset[];
  impact: PersistedReportImpact[];
  snapshot?: Record<string, unknown>;
}

export interface AssuranceReport {
  id: string;
  title: string;
  datasetId: string;
  datasetName: string;
  modelId: string;
  modelName: string;
  createdAt: string;
  assessmentStatus: 'REVIEW REQUIRED' | 'POTENTIALLY ACCEPTABLE' | 'QUARANTINE RECOMMENDED' | 'NOT ASSESSED';
  disposition: 'ACCEPT' | 'REVIEW' | 'QUARANTINE' | 'NOT ASSESSED';
  confidenceScore: number | null;
  projectDefinedRisk: 'LOW' | 'MODERATE' | 'ELEVATED' | 'HIGH' | 'NOT ASSESSED';
  executiveSummary: string;
  findingsCount: {
    critical: number | null;
    high: number | null;
    medium: number | null;
    low: number | null;
  };
  persistedContent?: PersistedReportContent;
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
  type: string;
  title: string;
  description: string;
  timestamp: string;
  targetId?: string;
  severity?: SeverityLevel;
}
