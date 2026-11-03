import React, { useState, useEffect } from 'react';
import {
  Play,
  ShieldCheck,
  Copy,
  Info,
  Check
} from 'lucide-react';
import { InferenceRecord, Model } from '../types';
import {
  getInferenceRecords,
  getDatasets,
  createProvenanceRecord,
  getModels
} from '../services/api';
import { StatusBadge } from '../components/common/StatusBadge';
import { TableSkeleton } from '../components/common/LoadingSkeleton';
import { useToast } from '../context/ToastContext';

export const InferenceProvenancePage: React.FC = () => {
  const { success, warning, error, info } = useToast();

  const [records, setRecords] = useState<InferenceRecord[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [datasetId, setDatasetId] = useState('');
  const [datasets, setDatasets] = useState<Awaited<ReturnType<typeof getDatasets>>>([]);
  const [loading, setLoading] = useState(true);

  // Metadata entry controls
  const [selectedModelId, setSelectedModelId] = useState('');
  const [selectedInputName, setSelectedInputName] = useState('');
  const [selectedConfig, setSelectedConfig] = useState('');
  const [isSimulating, setIsSimulating] = useState(false);

  // Active / Selected record for audit
  const [activeRecord, setActiveRecord] = useState<InferenceRecord | null>(null);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const fetchRecords = async () => {
    try {
      const [recs, mdls, ownedDatasets] = await Promise.all([getInferenceRecords(), getModels(), getDatasets()]);
      setRecords(recs);
      setModels(mdls);
      setDatasets(ownedDatasets);
      setDatasetId((current) => current || ownedDatasets[0]?.id || '');
      if (recs.length > 0 && !activeRecord) {
        setActiveRecord(recs[0]);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRecords();
  }, []);

  const handleRunInference = async () => {
    setIsSimulating(true);
    try {
      if (!datasetId) throw new Error('Select an owned dataset first.');
      const newRec = await createProvenanceRecord(datasetId, {
        model_id: selectedModelId,
        input_filename: selectedInputName,
        preprocessing: selectedConfig,
      });
      success('Provenance Record Generated', `Metadata record ${newRec.id} was persisted with no_prediction status.`);
      await fetchRecords();
    } catch {
      error('Provenance Error', 'Could not persist provenance metadata.');
    } finally {
      setIsSimulating(false);
    }
  };

  const copyField = (label: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(label);
    setTimeout(() => setCopiedField(null), 1500);
    info('Copied', `${label} copied to clipboard.`);
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-xs font-mono text-teal-700 uppercase tracking-wider font-semibold">
            Provenance Metadata Node
          </span>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 font-mono mt-1">
            Inference Provenance Metadata
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Review persisted provenance metadata. This screen does not execute inference or create signatures.
          </p>
        </div>

        <span className="text-xs font-mono px-3 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 self-start sm:self-auto flex items-center gap-1.5 font-medium">
          <ShieldCheck className="w-4 h-4 text-emerald-600" />
          <span>Prediction engine not configured</span>
        </span>
      </div>

      {/* Simulator Section */}
      <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
        <div className="flex items-center justify-between pb-3 border-b border-slate-200">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">
              Save Provenance Metadata
            </h3>
            <p className="text-xs text-slate-500">
              Persist metadata for a future inference run. No inference is executed and no prediction or signature is generated.
            </p>
          </div>
          <span className="text-xs font-mono text-teal-700 font-medium">Metadata Registry</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Owned Dataset</label>
            <select value={datasetId} onChange={(e) => setDatasetId(e.target.value)} className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-xs">
              <option value="">Select dataset</option>
              {datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">
              Select Input Vector / Radiograph
            </label>
            <input
              aria-label="Input asset name"
              value={selectedInputName}
              onChange={(e) => setSelectedInputName(e.target.value)}
              className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-xs text-slate-900 focus:outline-none focus:border-teal-600"
              placeholder="Optional input asset name"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">
              Referenced Model Artifact
            </label>
            <select
              value={selectedModelId}
              onChange={(e) => setSelectedModelId(e.target.value)}
              className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-xs text-slate-900 focus:outline-none focus:border-teal-600"
            >
              <option value="">No model selected</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.format})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">
              Preprocessing Pipeline Spec
            </label>
            <input
              aria-label="Preprocessing specification"
              value={selectedConfig}
              onChange={(e) => setSelectedConfig(e.target.value)}
              className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-xs text-slate-900 focus:outline-none focus:border-teal-600"
              placeholder="Optional preprocessing metadata"
            />
          </div>
        </div>

        <div className="flex justify-end pt-2">
          <button
            onClick={handleRunInference}
            disabled={isSimulating || !datasetId}
            className="px-4 py-2 text-xs font-semibold rounded-lg bg-teal-700 hover:bg-teal-800 disabled:opacity-50 text-white transition-colors flex items-center gap-2 shadow-xs"
          >
            <Play className={`w-3.5 h-3.5 ${isSimulating ? 'animate-spin' : ''}`} />
            <span>{isSimulating ? 'Saving Metadata...' : 'Save Provenance Metadata'}</span>
          </button>
        </div>
      </div>

      {/* Selected Provenance Record Details */}
      {activeRecord && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Prediction and Visual Representation */}
          <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <div>
                <span className="text-[10px] font-mono uppercase tracking-wider text-teal-700 font-semibold">
                  Provenance Metadata Record
                </span>
                <h3 className="text-base font-bold font-mono text-slate-900">
                  {activeRecord.id}
                </h3>
              </div>
              <StatusBadge status={activeRecord.verificationStatus} size="sm" />
            </div>

            {/* Prediction Card */}
            <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">Primary Classification:</span>
                <span className="text-sm font-bold font-mono text-teal-800">
                  {activeRecord.prediction.label}
                </span>
              </div>

              <div>
                <div className="flex justify-between text-xs font-mono mb-1">
                  <span className="text-slate-500">Confidence Score:</span>
                  <span className="tabular-nums font-bold text-slate-900">
                    {activeRecord.prediction.confidence == null
                      ? 'Not available'
                      : `${(activeRecord.prediction.confidence * 100).toFixed(1)}%`}
                  </span>
                </div>
                {activeRecord.prediction.confidence != null && (
                  <div className="w-full h-2 bg-slate-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-teal-600 rounded-full transition-all"
                      style={{ width: `${activeRecord.prediction.confidence * 100}%` }}
                    />
                  </div>
                )}
              </div>

              {activeRecord.prediction.secondaryClass && (
                <div className="flex justify-between text-[11px] text-slate-500 font-mono pt-1">
                  <span>Alt: {activeRecord.prediction.secondaryClass}</span>
                  <span>{((activeRecord.prediction.secondaryConfidence || 0) * 100).toFixed(1)}%</span>
                </div>
              )}

              {/* Bounding box mock indicator for CV models */}
              {activeRecord.prediction.boundingBoxes && activeRecord.prediction.boundingBoxes.length > 0 && (
                <div className="pt-2 border-t border-slate-200">
                  <span className="text-[10px] font-mono text-slate-500 block mb-1">
                    Detected Bounding Annotations:
                  </span>
                  <div className="space-y-1">
                    {activeRecord.prediction.boundingBoxes.map((b, idx) => (
                      <div key={idx} className="flex justify-between text-[11px] font-mono text-slate-700">
                        <span>{b.label}</span>
                        <span className="text-teal-700 tabular-nums">{(b.confidence * 100).toFixed(0)}% [x:{b.box[0]}, y:{b.box[1]}]</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Input metadata details */}
            <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs space-y-1.5 font-mono">
              <div className="flex justify-between text-slate-500">
                <span>Input Asset:</span>
                <span className="text-slate-800 truncate max-w-[160px]">{activeRecord.inputMetadata.filename}</span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>Dimensions:</span>
                <span className="text-slate-800">{activeRecord.inputMetadata.dimensions}</span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>Timestamp:</span>
                <span className="text-slate-700">{activeRecord.timestamp}</span>
              </div>
            </div>
          </div>

          {/* Supplied Metadata */}
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4 shadow-xs">
              <div className="flex items-center justify-between pb-3 border-b border-slate-200">
                <h3 className="text-sm font-semibold text-slate-900">
                  Supplied Provenance Metadata
                </h3>
                <span className="text-xs font-mono text-slate-500">
                  Sequence #{activeRecord.sequenceNumber}
                </span>
              </div>

              {/* Hash Chain Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg">
                  <div className="flex items-center justify-between text-slate-500 text-[11px] mb-1">
                    <span>Input Hash (SHA-256)</span>
                    <button onClick={() => copyField('Input Hash', activeRecord.inputHash)} className="hover:text-teal-700">
                      {copiedField === 'Input Hash' ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3 text-slate-400" />}
                    </button>
                  </div>
                  <span className="font-mono text-teal-800 break-all text-[11px] block font-medium">
                    {activeRecord.inputHash}
                  </span>
                </div>

                <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg">
                  <div className="flex items-center justify-between text-slate-500 text-[11px] mb-1">
                    <span>Output Hash (SHA-256)</span>
                    <button onClick={() => copyField('Output Hash', activeRecord.outputHash)} className="hover:text-teal-700">
                      {copiedField === 'Output Hash' ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3 text-slate-400" />}
                    </button>
                  </div>
                  <span className="font-mono text-teal-800 break-all text-[11px] block font-medium">
                    {activeRecord.outputHash}
                  </span>
                </div>

                <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg">
                  <div className="flex items-center justify-between text-slate-500 text-[11px] mb-1">
                    <span>Configuration Hash</span>
                    <button onClick={() => copyField('Config Hash', activeRecord.configHash)} className="hover:text-teal-700">
                      {copiedField === 'Config Hash' ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3 text-slate-400" />}
                    </button>
                  </div>
                  <span className="font-mono text-slate-700 break-all text-[11px] block">
                    {activeRecord.configHash}
                  </span>
                </div>

                <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg">
                  <div className="flex justify-between text-slate-500 text-[11px] mb-1">
                    <span>Nonce & Sequence:</span>
                    <span className="text-slate-400 font-mono">Sequence metadata</span>
                  </div>
                  <span className="font-mono text-slate-800 block text-xs">
                    {activeRecord.nonce} · Seq: {activeRecord.sequenceNumber}
                  </span>
                </div>
              </div>

              <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-600">
                Metadata-only record. No inference execution, prediction, signature, or cryptographic verification is performed.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Provenance History Table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs">
        <div className="p-4 border-b border-slate-200 flex items-center justify-between">
          <h3 className="text-xs font-semibold text-slate-700 uppercase tracking-wider font-mono">
            Historical Provenance Ledger
          </h3>
          <span className="text-xs text-slate-500 font-mono">
            {records.length} Persisted Metadata Records
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-500 font-mono uppercase tracking-wider border-b border-slate-200">
              <tr>
                <th className="px-4 py-3 font-semibold">Record ID</th>
                <th className="px-4 py-3 font-semibold">Timestamp</th>
                <th className="px-4 py-3 font-semibold">Model</th>
                <th className="px-4 py-3 font-semibold">Input Hash</th>
                <th className="px-4 py-3 font-semibold">Output Hash</th>
                <th className="px-4 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {records.map((r) => {
                const isSelected = activeRecord?.id === r.id;
                return (
                  <tr
                    key={r.id}
                    onClick={() => {
                      setActiveRecord(r);
                    }}
                    className={`cursor-pointer transition-colors ${
                      isSelected
                        ? 'bg-teal-50/60 border-l-2 border-l-teal-600'
                        : 'hover:bg-slate-50/80'
                    }`}
                  >
                    <td className="px-4 py-3 font-mono font-semibold text-teal-800 whitespace-nowrap">
                      {r.id}
                    </td>
                    <td className="px-4 py-3 font-mono text-slate-500 text-[11px] whitespace-nowrap">
                      {r.timestamp}
                    </td>
                    <td className="px-4 py-3 text-slate-700 whitespace-nowrap font-medium">
                      {r.modelName.split(' ')[0]}
                    </td>
                    <td className="px-4 py-3 font-mono text-slate-600 truncate max-w-[120px]">
                      {r.inputHash}
                    </td>
                    <td className="px-4 py-3 font-mono text-slate-600 truncate max-w-[120px]">
                      {r.outputHash}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <StatusBadge status={r.verificationStatus} size="sm" />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
