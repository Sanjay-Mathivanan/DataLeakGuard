export type DatasetWorkflow = 'dataset' | 'findings' | 'repair';

const workflowRoutes: Record<DatasetWorkflow, string> = {
  dataset: 'datasets',
  findings: 'leakage-analysis',
  repair: 'repair',
};

/** Route to a real dataset workflow, or to the dataset picker when none is selected. */
export function getDatasetWorkflowPath(
  workflow: DatasetWorkflow,
  datasetId?: string | null
): string {
  if (!datasetId?.trim()) {
    return '/datasets';
  }

  return `/${workflowRoutes[workflow]}/${encodeURIComponent(datasetId)}`;
}
