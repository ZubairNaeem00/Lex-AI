import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bookmark, X, Download, FileText, Sparkles, Loader2, MessageSquarePlus, Check } from 'lucide-react';
import { toggleSavedCase, useIsSaved } from '../../savedCases';
import { cleanCitation } from './CaseCard';
import CaseAnalysisReport from './CaseAnalysisReport';
import {
  ensureCase, storeCaseId, analyzeCaseText, exportCaseDocx,
  downloadGeneratedDocument, addPrecedent,
} from '../../api/client';

const precedentPayload = (item) => ({
  case_id: item.case_id ?? null,
  citation: cleanCitation(item.citation),
  case_name: item.case_name || '',
  summary: item.summary || '',
  description: item.description || '',
  matched_section: item.matched_section || '',
  chunk_count: item.chunk_count || 0,
  score: item.score || 0,
});

export default function CaseDetailModal({ item, onClose }) {
  const navigate = useNavigate();
  const saved = useIsSaved(item?.case_id);
  const [tab, setTab] = useState('text');
  const [report, setReport] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState('');
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState('');
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState(false);
  const [addError, setAddError] = useState('');

  if (!item) return null;

  const runAnalysis = async () => {
    setAnalyzing(true);
    setAnalysisError('');
    try {
      const text = [item.summary, item.description].filter(Boolean).join('\n\n').slice(0, 60000);
      const data = await analyzeCaseText(text, { title: item.case_name, citation: cleanCitation(item.citation) });
      setReport(data.report);
    } catch (e) {
      setAnalysisError(e.message || 'The case text could not be analyzed.');
    } finally {
      setAnalyzing(false);
    }
  };

  const switchTab = (next) => {
    setTab(next);
    if (next === 'analysis' && !report && !analyzing && !analysisError) runAnalysis();
  };

  const handleExport = async () => {
    setExporting(true);
    setExportError('');
    try {
      const caseId = await ensureCase();
      const meta = await exportCaseDocx(caseId, precedentPayload(item), report || undefined);
      const blob = await downloadGeneratedDocument(caseId, meta.filename);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = meta.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError(e.message || 'The export could not be created.');
    } finally {
      setExporting(false);
    }
  };

  const handleAdd = async () => {
    setAdding(true);
    setAddError('');
    try {
      const caseId = await ensureCase();
      await addPrecedent(caseId, precedentPayload(item));
      storeCaseId(caseId);
      setAdded(true);
      window.dispatchEvent(new CustomEvent('lexai:precedent-added'));
      window.dispatchEvent(new CustomEvent('lexai:refresh-chat'));
      navigate('/chat');
      onClose();
    } catch (e) {
      setAddError(e.message || 'The precedent could not be added.');
    } finally {
      setAdding(false);
    }
  };

  const tabClass = (active) =>
    `inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition-colors ${
      active ? 'bg-green-600 text-white shadow-sm' : 'text-slate-500 hover:bg-slate-100 hover:text-green-700'
    }`;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={item.case_name}>
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative flex max-h-[88vh] w-full max-w-2xl flex-col rounded-2xl border border-slate-200 bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 p-5">
          <div className="min-w-0">
            <h3 className="text-[15px] font-semibold leading-snug text-slate-900">{item.case_name}</h3>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-500">{cleanCitation(item.citation)}</p>
            <p className="mt-1.5 text-[11px] text-slate-500">
              {Math.round((item.score || 0) * 100)}% match · matched in {item.matched_section} ·{' '}
              {item.chunk_count} indexed passage{item.chunk_count === 1 ? '' : 's'}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              onClick={handleExport}
              disabled={exporting}
              title={report ? 'Export case text and AI analysis as Word' : 'Export case text as Word'}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[12px] font-medium text-slate-600 transition-colors hover:border-green-300 hover:bg-green-50 hover:text-green-700 disabled:opacity-60"
            >
              {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
              {exporting ? 'Exporting…' : 'Export'}
            </button>
            <button
              onClick={() => toggleSavedCase(item)}
              aria-label={saved ? 'Remove from saved cases' : 'Save case'}
              aria-pressed={saved}
              title={saved ? 'Remove from saved cases' : 'Save case'}
              className={`rounded-lg p-1.5 transition-colors ${saved ? 'text-green-600 hover:bg-green-50' : 'text-slate-400 hover:bg-slate-100 hover:text-green-600'}`}
            >
              <Bookmark className={`h-4 w-4 ${saved ? 'fill-current' : ''}`} />
            </button>
            <button onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1.5 border-b border-slate-100 px-5 py-2.5">
          <button onClick={() => switchTab('text')} className={tabClass(tab === 'text')} aria-pressed={tab === 'text'}>
            <FileText className="h-3.5 w-3.5" />
            Case text
          </button>
          <button onClick={() => switchTab('analysis')} className={tabClass(tab === 'analysis')} aria-pressed={tab === 'analysis'}>
            <Sparkles className="h-3.5 w-3.5" />
            AI analysis
          </button>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto p-5 scrollbar-light">
          {tab === 'text' ? (
            <>
              <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-green-700">Summary</h4>
              <p className="mb-5 whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700">
                {item.summary || 'No summary was provided in the source record.'}
              </p>
              <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-green-700">Full description</h4>
              <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700">
                {item.description || 'No description was provided in the source record.'}
              </p>
            </>
          ) : analyzing ? (
            <div className="flex flex-col items-center justify-center gap-3 py-14 text-center">
              <Loader2 className="h-7 w-7 animate-spin text-green-600" />
              <p className="text-[13px] font-medium text-slate-600">Analyzing the case text…</p>
              <p className="max-w-xs text-[11.5px] leading-relaxed text-slate-400">
                The same agent used for document analysis is reading this judgement.
              </p>
            </div>
          ) : analysisError ? (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-4">
              <p className="text-[12.5px] leading-relaxed text-rose-700">{analysisError}</p>
              <button onClick={runAnalysis} className="mt-3 rounded-lg bg-rose-600 px-3 py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-rose-700">
                Try again
              </button>
            </div>
          ) : report ? (
            <CaseAnalysisReport report={report} />
          ) : (
            <div className="flex flex-col items-center justify-center gap-3 py-14 text-center">
              <Sparkles className="h-7 w-7 text-green-600" />
              <p className="text-[13px] text-slate-600">Generate an AI analysis of this case text.</p>
              <button onClick={runAnalysis} className="rounded-lg bg-green-600 px-3.5 py-2 text-[12.5px] font-medium text-white transition-colors hover:bg-green-700">
                Analyze case text
              </button>
            </div>
          )}

          {exportError && (
            <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[12.5px] text-rose-700">{exportError}</p>
          )}
        </div>

        {/* Footer: add to chat as precedent */}
        <div className="flex flex-wrap items-center gap-3 border-t border-slate-200 px-5 py-3.5">
          <button
            onClick={handleAdd}
            disabled={adding || added}
            className={`inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-[13px] font-medium shadow-sm transition-all duration-200 disabled:opacity-70 ${
              added ? 'bg-green-100 text-green-700' : 'bg-green-600 text-white hover:bg-green-700'
            }`}
          >
            {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : added ? <Check className="h-4 w-4" /> : <MessageSquarePlus className="h-4 w-4" />}
            {adding ? 'Adding…' : added ? 'Added as precedent' : 'Add to chat as precedent'}
          </button>
          <p className="min-w-0 flex-1 text-[11px] leading-relaxed text-slate-400">
            Attached as a past judgement for reference — it never replaces your current case or its facts.
          </p>
          {addError && <p className="w-full text-[12px] text-rose-600">{addError}</p>}
        </div>
      </div>
    </div>
  );
}