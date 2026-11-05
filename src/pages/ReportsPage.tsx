import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FileText,
  Plus,
  Download,
  Trash2,
  Eye,
  CheckCircle2,
  AlertTriangle,
  Clock,
  ShieldCheck,
  Search
} from 'lucide-react';
import { AssuranceReport, Dataset } from '../types';
import { getDatasets, getReports, deleteReport, downloadReport, generateAssuranceReport } from '../services/api';
import { StatusBadge } from '../components/common/StatusBadge';
import { ConfirmModal } from '../components/common/ConfirmModal';
import { TableSkeleton } from '../components/common/LoadingSkeleton';
import { useToast } from '../context/ToastContext';

export const ReportsPage: React.FC = () => {
  const navigate = useNavigate();
  const { success, error } = useToast();

  const [reports, setReports] = useState<AssuranceReport[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [search, setSearch] = useState('');
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  const fetchReports = async () => {
    setLoadError('');
    try {
      const [data, ownedDatasets] = await Promise.all([getReports(), getDatasets()]);
      setReports(data);
      setDatasets(ownedDatasets);
    } catch (fetchError) {
      setLoadError(fetchError instanceof Error ? fetchError.message : 'Could not load persisted reports.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReports();
  }, []);

  const handleGenerate = async () => {
    setIsGenerating(true);
    try {
      if (!selectedDatasetId) throw new Error('Select the dataset this report should describe.');
      const created = await generateAssuranceReport(selectedDatasetId, '');
      success('Report Generated', `Persisted dataset snapshot ${created.id}.`);
      await fetchReports();
      navigate(`/reports/${created.id}`);
    } catch (generationError) {
      error(
        'Report Generation Error',
        generationError instanceof Error ? generationError.message : 'Could not compile the persisted report.'
      );
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteId) return;
    try {
      await deleteReport(deleteId);
      success('Report Deleted', 'Report removed from repository.');
      setDeleteId(null);
      await fetchReports();
    } catch {
      error('Delete Error', 'Could not remove report.');
    }
  };

  const handleDownloadReport = async (reportId: string, title: string) => {
    try {
      await downloadReport(reportId, 'pdf');
      success('Report Downloaded', `${title} was downloaded as PDF.`);
    } catch (downloadError) {
      error(
        'Download Error',
        downloadError instanceof Error ? downloadError.message : 'Could not download the persisted report.'
      );
    }
  };

  const filteredReports = reports.filter(
    (r) =>
      r.id.toLowerCase().includes(search.toLowerCase()) ||
      r.title.toLowerCase().includes(search.toLowerCase()) ||
      r.datasetName.toLowerCase().includes(search.toLowerCase()) ||
      r.modelName.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-xs font-mono text-teal-700 uppercase tracking-wider font-semibold">
            Persisted Records
          </span>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 font-mono mt-1">
            Dataset Integrity Reports
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Reports snapshot available profiling, findings, partition comparisons, remediation and verification records. Model evaluation and assurance ratings are not generated.
          </p>
        </div>

        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
          <label className="text-xs text-slate-600">
            Report dataset
            <select
              aria-label="Report dataset"
              value={selectedDatasetId}
              onChange={(event) => setSelectedDatasetId(event.target.value)}
              className="mt-1 block min-w-56 rounded-lg border border-slate-300 bg-white px-3 py-2"
            >
              <option value="">Select an owned dataset</option>
              {datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}
            </select>
          </label>
          <button
            onClick={handleGenerate}
            disabled={isGenerating || !selectedDatasetId}
            className="self-end rounded-lg bg-teal-700 px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-teal-800 disabled:opacity-50 sm:self-end"
          >
            <span className="flex items-center gap-2">
              <Plus className="h-4 w-4" />
              {isGenerating ? 'Generating…' : 'Generate Report'}
            </span>
          </button>
        </div>
      </div>

      {/* Search Input */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
        <div className="relative max-w-md">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
          <input
            type="text"
            placeholder="Search reports by ID, dataset, or model name..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:border-teal-600"
          />
        </div>
      </div>

      {/* Reports Table */}
      {loadError ? (
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-800">{loadError}</div>
      ) : loading ? (
        <TableSkeleton rows={3} />
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-500 font-mono uppercase tracking-wider border-b border-slate-200">
                <tr>
                  <th className="px-5 py-3 font-semibold">Report ID</th>
                  <th className="px-5 py-3 font-semibold">Audit Title</th>
                  <th className="px-5 py-3 font-semibold">Dataset & Model</th>
                  <th className="px-5 py-3 font-semibold">Created Date</th>
                  <th className="px-5 py-3 font-semibold">Assessment</th>
                  <th className="px-5 py-3 font-semibold">Confidence</th>
                  <th className="px-5 py-3 font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredReports.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-5 py-8 text-center text-slate-500">
                      {reports.length === 0 ? 'No persisted reports yet. Generate a snapshot from an owned dataset.' : 'No reports match this search.'}
                    </td>
                  </tr>
                ) : filteredReports.map((rep) => (
                  <tr key={rep.id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="px-5 py-3 font-mono font-semibold text-teal-800 whitespace-nowrap">
                      {rep.id}
                    </td>

                    <td className="px-5 py-3">
                      <button
                        onClick={() => navigate(`/reports/${rep.id}`)}
                        className="font-semibold text-slate-900 hover:text-teal-700 text-left transition-colors max-w-xs truncate block"
                      >
                        {rep.title}
                      </button>
                    </td>

                    <td className="px-5 py-3 whitespace-nowrap">
                      <p className="text-slate-800 font-medium">{rep.datasetName.split('(')[0]}</p>
                      <p className="text-[10px] font-mono text-slate-500">{rep.modelName.split('(')[0]}</p>
                    </td>

                    <td className="px-5 py-3 text-slate-500 font-mono text-[11px] whitespace-nowrap">
                      {rep.createdAt.split(' ')[0]}
                    </td>

                    <td className="px-5 py-3 whitespace-nowrap">
                      <StatusBadge status={rep.disposition} size="sm" />
                    </td>

                    <td className="px-5 py-3 font-mono tabular-nums text-slate-900 font-semibold whitespace-nowrap">
                      {rep.confidenceScore == null ? 'Not assessed' : `${rep.confidenceScore}%`}
                    </td>

                    <td className="px-5 py-3 text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          onClick={() => navigate(`/reports/${rep.id}`)}
                          className="p-1.5 text-slate-400 hover:text-teal-700 hover:bg-slate-100 rounded transition-colors"
                          title="View Report Preview"
                        >
                          <Eye className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => handleDownloadReport(rep.id, rep.title)}
                          className="p-1.5 text-slate-400 hover:text-emerald-600 hover:bg-slate-100 rounded transition-colors"
                          title="Download PDF report"
                        >
                          <Download className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => setDeleteId(rep.id)}
                          className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-slate-100 rounded transition-colors"
                          title="Delete Report"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Confirmation Modal */}
      <ConfirmModal
        isOpen={!!deleteId}
        title="Delete Assurance Report"
        message="Are you sure you want to permanently delete this persisted report snapshot?"
        confirmLabel="Delete Report"
        isDestructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteId(null)}
      />
    </div>
  );
};
