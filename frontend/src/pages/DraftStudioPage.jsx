import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AppSidebar from '../components/AppSidebar';
import DraftViewer from '../components/chat/DraftViewer';
import {
  createCase, resetCasePromise, storeCaseId,
  listTemplates, downloadBlankTemplate, openTemplateDraft,
} from '../api/client';

/* ── Presentational helpers (UI only, matches ChatPage / ReportsPage) ── */
const Icon = ({ d, className = 'w-4 h-4' }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {[].concat(d).map((p, i) => <path key={i} d={p} />)}
  </svg>
);

const I = {
  template: ['M9 3h6a2 2 0 0 1 2 2v1h2a1 1 0 0 1 1 1v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a1 1 0 0 1 1-1h2V5a2 2 0 0 1 2-2z', 'M9 12h6M9 16h4'],
  file: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6', 'M8 13h8', 'M8 17h5'],
  download: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M7 10l5 5 5-5', 'M12 15V3'],
  edit: ['M12 20h9', 'M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z'],
  check: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M8 12l3 3 5-6'],
  spinner: 'M20 12a8 8 0 1 1-8-8',
  alert: ['M12 9v4', 'M12 17h.01', 'M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'],
};

const BentoCard = ({ children, className = '', style }) => (
  <div style={style} className={`rounded-2xl border border-slate-200 bg-white shadow-sm transition-all duration-200 hover:shadow-md ${className}`}>
    {children}
  </div>
);

const typeLabel = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : 'Legal');

export default function DraftStudioPage() {
  const navigate = useNavigate();
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyName, setBusyName] = useState(null);
  const [viewer, setViewer] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await listTemplates();
      setTemplates(r.catalog || []);
      setError('');
    } catch (e) {
      setError(e.message || 'Could not load the template folder.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openCaseInChat = (id) => {
    storeCaseId(id);
    resetCasePromise();
    navigate('/chat');
  };

  const newCaseInChat = async () => {
    const snap = await createCase();
    storeCaseId(snap.case_id);
    resetCasePromise();
    navigate('/chat');
  };

  const download = async (tpl) => {
    setBusyName(tpl.path);
    setError('');
    try {
      const blob = await downloadBlankTemplate(tpl.path);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = tpl.path;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message || 'The download failed.');
    } finally {
      setBusyName(null);
    }
  };

  // "Edit draft" opens the blank template (from the Templates folder) in the
  // shared side editor on a fresh conversation — no field Q&A, no AI generation.
  const editDraft = async (tpl) => {
    setBusyName(tpl.path);
    setError('');
    try {
      const snap = await createCase();
      const opened = await openTemplateDraft(snap.case_id, tpl.path);
      setViewer({
        caseId: opened.case_id,
        draft: { generationId: opened.generation_id, templateLabel: tpl.name, filename: (opened.generation?.result?.filename) || '' },
      });
    } catch (e) {
      setError(e.message || 'The template could not be opened for editing.');
    } finally {
      setBusyName(null);
    }
  };

  return (
    <div className="flex h-full overflow-hidden bg-page text-slate-800 antialiased">

      <AppSidebar
        activeCaseId={null}
        onOpenCase={openCaseInChat}
        onNewConversation={newCaseInChat}
      />

      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-16 flex-shrink-0 flex items-center justify-between px-6 md:px-8 bg-white/80 backdrop-blur border-b border-slate-200">
          <div className="flex items-center gap-3 min-w-0">
            <h1 className="text-[15px] font-semibold text-slate-900 truncate">Draft Studio</h1>
            <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-full px-2 py-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              {templates.length} templates
            </span>
            <span className="hidden md:inline text-xs text-slate-500">Edit a template in the side editor or download it blank</span>
          </div>
          <button
            onClick={() => navigate('/chat')}
            className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm transition-all duration-200 hover:border-slate-300 hover:shadow-md"
          >
            Open assistant
          </button>
        </header>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-5xl mx-auto px-6 md:px-8 py-8 flex flex-col gap-6">

            {error && (
              <BentoCard className="flex items-start gap-3 border-rose-200 bg-rose-50 p-4">
                <Icon d={I.alert} className="w-4 h-4 text-rose-600 mt-0.5" />
                <p className="text-[13px] text-rose-700">{error}</p>
              </BentoCard>
            )}

            {loading && (
              <div className="flex items-center justify-center gap-2 py-16 text-slate-400">
                <Icon d={I.spinner} className="w-5 h-5 animate-spin" />
                <span className="text-sm">Loading templates…</span>
              </div>
            )}

            {!loading && templates.length === 0 && (
              <BentoCard className="py-16 text-center">
                <div className="mx-auto mb-4 w-12 h-12 rounded-xl bg-green-50 border border-green-100 text-green-600 flex items-center justify-center">
                  <Icon d={I.template} className="w-6 h-6" />
                </div>
                <p className="text-[15px] font-semibold text-slate-900">No templates found</p>
                <p className="mt-1 text-sm text-slate-500">Add DOCX templates to the Templates folder and reload this page.</p>
              </BentoCard>
            )}

            {!loading && templates.length > 0 && (
              <div className={`grid gap-4 ${viewer ? 'grid-cols-1' : 'md:grid-cols-2'}`}>
                {templates.map((tpl) => {
                  const supported = Boolean(tpl.supported);
                  const busy = busyName === tpl.path;
                  return (
                    <BentoCard key={tpl.path} className="p-5 md:p-6 flex flex-col">
                      <div className="flex items-start gap-4">
                        <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-green-50 border border-green-100 text-green-600 flex items-center justify-center">
                          <Icon d={I.file} className="w-5 h-5" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                            <span className="text-[11px] font-medium text-green-600">{typeLabel(tpl.document_type)}</span>
                            <span className={`inline-flex items-center gap-1.5 text-xs rounded-full px-2 py-0.5 border ${
                              supported
                                ? 'text-emerald-700 bg-emerald-50 border-emerald-100'
                                : 'text-slate-600 bg-slate-50 border-slate-200'}`}>
                              <Icon d={supported ? I.check : I.download} className="w-3 h-3" />
                              {supported ? `${tpl.field_count || 0} fields · AI-ready` : 'Manual fill'}
                            </span>
                          </div>
                          <h2 className="text-[15px] font-semibold text-slate-900 break-words">{tpl.name}</h2>
                        </div>
                      </div>

                      <p className="mt-3 text-[13px] leading-6 text-slate-600 flex-1">
                        {tpl.description || 'A ready-made legal document template.'}
                      </p>

                      <div className="mt-4 flex flex-wrap items-center gap-2">
                        <button
                          onClick={() => editDraft(tpl)}
                          disabled={busy}
                          className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98] disabled:opacity-50"
                        >
                          <Icon d={busy ? I.spinner : I.edit} className={`w-4 h-4 ${busy ? 'animate-spin' : ''}`} />
                          Edit draft
                        </button>
                        <button
                          onClick={() => download(tpl)}
                          disabled={busy}
                          className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm transition-all duration-200 hover:border-green-300 hover:text-green-700 hover:bg-green-50 disabled:opacity-50"
                        >
                          <Icon d={I.download} className="w-4 h-4" />
                          Download template
                        </button>
                      </div>
                    </BentoCard>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </main>

      {viewer && (
        <DraftViewer
          caseId={viewer.caseId}
          draft={viewer.draft}
          onClose={() => setViewer(null)}
        />
      )}
    </div>
  );
}
