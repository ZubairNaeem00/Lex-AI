import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  analyzeDocument, createCase, discussDocument, downloadGeneratedDocument,
  generateAnalysisDocx, getCase, resetCasePromise, retrieveCases, storeCaseId,
} from '../api/client';
import AppSidebar from '../components/AppSidebar';
import AnalysisCard from '../components/chat/AnalysisCard';
import CaseSlider from '../components/chat/CaseSlider';

const WORKSPACE_KEY = 'lexai.upload_case';
const ALLOWED = ['.pdf', '.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff'];

const Icon = ({ d, className = 'w-4 h-4' }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {[].concat(d).map((p, i) => <path key={i} d={p} />)}
  </svg>
);

const I = {
  file: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6', 'M8 13h8', 'M8 17h5'],
  image: ['M3 5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5z', 'M8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z', 'M21 15l-5-5L5 21'],
  download: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M7 10l5 5 5-5', 'M12 15V3'],
  upload: ['M12 16V4', 'M6 10l6-6 6 6', 'M4 20h16'],
  check: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M8 12l3 3 5-6'],
  chat: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z',
  folder: 'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z',
  doc: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6', 'M16 13H8', 'M16 17H8', 'M10 9H8'],
  warn: ['M12 9v4', 'M12 17h.01', 'M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'],
  x: ['M18 6L6 18', 'M6 6l12 12'],
};

const BentoCard = ({ children, className = '' }) => (
  <div className={`rounded-2xl border border-slate-200 bg-white shadow-sm transition-all duration-200 hover:shadow-md ${className}`}>
    {children}
  </div>
);

const SectionLabel = ({ children }) => (
  <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-3">{children}</p>
);

const ProgressBar = ({ value }) => (
  <div className="mt-2 h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
    <div className={`h-full rounded-full transition-all duration-300 ${value >= 100 ? 'bg-emerald-500' : 'bg-green-600'}`}
         style={{ width: `${value}%` }} />
  </div>
);

const Spinner = ({ className = 'w-3.5 h-3.5' }) => (
  <span className={`${className} border-2 border-current border-t-transparent rounded-full animate-spin opacity-70`} />
);

const fmtSize = (bytes) => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);
const typeOf = (name) => {
  const ext = name.split('.').pop().toLowerCase();
  if (ext === 'pdf') return 'PDF';
  if (['png', 'jpg', 'jpeg', 'webp', 'tif', 'tiff'].includes(ext)) return 'IMG';
  return ext.toUpperCase();
};
const typeIcon = (t) => (t === 'IMG' ? I.image : I.file);

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function UploadPage() {
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [workspaceId, setWorkspaceId] = useState(null);
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [notice, setNotice] = useState('');
  const [busyKey, setBusyKey] = useState(null);
  const [precedents, setPrecedents] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const stored = localStorage.getItem(WORKSPACE_KEY);
      if (stored) {
        try {
          const snap = await getCase(stored);
          if (cancelled) return;
          setWorkspaceId(snap.case_id);
          const restored = (snap.documents || []).map(d => ({
            key: d.document_id, document_id: d.document_id, filename: d.filename,
            type: typeOf(d.filename), size: '', status: 'analyzed',
            report: d.report, edits: d.edits || [],
          }));
          setDocs(restored);
          const first = restored.find(d => d.report);
          if (first) loadPrecedents(first.report);
        } catch (e) {
          localStorage.removeItem(WORKSPACE_KEY);
        }
      }
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
  }, []);

  const patchDoc = (key, patch) => setDocs(list => list.map(d => (d.key === key ? { ...d, ...patch } : d)));

  const ensureWorkspace = async () => {
    const stored = localStorage.getItem(WORKSPACE_KEY);
    if (stored) { setWorkspaceId(stored); return stored; }
    const snap = await createCase();
    localStorage.setItem(WORKSPACE_KEY, snap.case_id);
    setWorkspaceId(snap.case_id);
    return snap.case_id;
  };

  const addFiles = (fileList) => {
    const added = [];
    for (const file of Array.from(fileList)) {
      const ext = `.${file.name.split('.').pop().toLowerCase()}`;
      if (!ALLOWED.includes(ext)) {
        setNotice(`“${file.name}” is not supported. Upload PDF, JPG, PNG, WEBP or TIFF files.`);
        continue;
      }
      added.push({
        key: `${file.name}-${Date.now()}-${added.length}`, filename: file.name,
        type: typeOf(file.name), size: fmtSize(file.size), status: 'ready', progress: 100, file,
      });
    }
    if (added.length) { setNotice(''); setDocs(list => [...list, ...added]); }
  };

  const loadPrecedents = async (report) => {
    const query = report?.summary || report?.title;
    if (!query) return;
    try { setPrecedents(await retrieveCases(query, 3)); } catch (e) { setPrecedents(null); }
  };

  const analyse = async (doc) => {
    patchDoc(doc.key, { status: 'analyzing', error: '' });
    try {
      const caseId = await ensureWorkspace();
      const res = await analyzeDocument(caseId, doc.file);
      patchDoc(doc.key, {
        status: 'analyzed', document_id: res.document_id, report: res.report, edits: res.edits || [],
      });
      setExpanded(doc.key);
      loadPrecedents(res.report);
    } catch (e) {
      patchDoc(doc.key, { status: 'error', error: e.message || 'Analysis failed. Please retry.' });
    }
  };

  const generate = async (doc) => {
    const meta = await generateAnalysisDocx(workspaceId, doc.document_id);
    patchDoc(doc.key, { generated: meta });
    return meta;
  };

  const download = async (doc) => {
    setBusyKey(doc.key);
    setNotice('');
    try {
      if (!doc.document_id) { saveBlob(doc.file, doc.filename); return; }
      const meta = doc.generated || await generate(doc);
      saveBlob(await downloadGeneratedDocument(workspaceId, meta.filename), meta.filename);
    } catch (e) {
      setNotice(e.message || 'The Word report could not be downloaded.');
    } finally {
      setBusyKey(null);
    }
  };

  const generateOnly = async (doc) => {
    setBusyKey(doc.key);
    setNotice('');
    try { await generate(doc); } catch (e) {
      setNotice(e.message || 'The Word report could not be generated.');
    } finally { setBusyKey(null); }
  };

  const discuss = async (doc) => {
    setBusyKey(doc.key);
    setNotice('');
    try {
      const res = await discussDocument(workspaceId, doc.document_id);
      storeCaseId(res.case_id);
      resetCasePromise();
      navigate('/chat');
    } catch (e) {
      setNotice(e.message || 'Could not open the discussion.');
      setBusyKey(null);
    }
  };

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

  const handleWorkspaceRemoved = () => {
    localStorage.removeItem(WORKSPACE_KEY);
    setWorkspaceId(null);
    setDocs([]);
    setPrecedents(null);
    setExpanded(null);
  };

  return (
    <div className="flex h-full overflow-hidden bg-slate-50 text-slate-800 antialiased">

      <AppSidebar
        activeCaseId={workspaceId}
        onOpenCase={openCaseInChat}
        onNewConversation={newCaseInChat}
        onActiveCaseRemoved={handleWorkspaceRemoved}
      />

      {/* ── Main ─ */}
      <main className="flex-1 flex flex-col min-w-0">
        <div className="flex-1 overflow-y-auto scrollbar-light">
          <div className="max-w-6xl mx-auto px-6 md:px-8 py-8 grid lg:grid-cols-[1fr_300px] gap-6 items-start">

            {/* Left column */}
            <div className="flex flex-col gap-6 min-w-0">

              {notice && (
                <div className="flex items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3">
                  <Icon d={I.warn} className="w-4 h-4 text-rose-600 mt-0.5 flex-shrink-0" />
                  <p className="flex-1 text-[13px] leading-relaxed text-rose-700">{notice}</p>
                  <button onClick={() => setNotice('')} aria-label="Dismiss" className="text-rose-400 hover:text-rose-600">
                    <Icon d={I.x} className="w-4 h-4" />
                  </button>
                </div>
              )}

              {/* Drop zone */}
              <div
                onDragOver={e => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={e => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
                onClick={() => inputRef.current?.click()}
                className={`
                  rounded-2xl border-2 border-dashed p-10 text-center cursor-pointer bg-white shadow-sm
                  transition-all duration-200
                  ${dragging
                    ? 'border-green-500 bg-green-50/70 scale-[1.01] shadow-md'
                    : 'border-slate-200 hover:border-green-300 hover:bg-green-50/30'}
                `}
              >
                <input ref={inputRef} type="file" multiple accept={ALLOWED.join(',')} className="hidden"
                       onChange={e => { addFiles(e.target.files); e.target.value = ''; }} />
                <div className="mx-auto mb-4 w-12 h-12 rounded-xl bg-green-50 border border-green-100 text-green-600 flex items-center justify-center">
                  <Icon d={I.folder} className="w-6 h-6" />
                </div>
                <h3 className="text-lg font-semibold tracking-tight text-slate-900 mb-1.5">Upload Legal Documents</h3>
                <p className="text-slate-500 text-sm mb-5 leading-relaxed">
                  Drop FIRs, court orders, witness statements,<br />or scanned images here
                </p>
                <div className="flex gap-2 justify-center flex-wrap mb-6">
                  {['.pdf', '.jpg/.png', '.webp', '.tiff'].map(t => (
                    <span key={t} className="text-[11px] font-medium bg-slate-50 border border-slate-200 px-3 py-1 rounded-lg text-slate-500">{t}</span>
                  ))}
                </div>
                <button
                  onClick={e => { e.stopPropagation(); inputRef.current?.click(); }}
                  className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98]"
                >
                  <Icon d={I.upload} className="w-4 h-4" />
                  Browse Files
                </button>
              </div>

              {/* Document list */}
              <div>
                <SectionLabel>Uploaded Documents ({docs.length})</SectionLabel>
                {loading ? (
                  <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-500">
                    <Spinner className="w-4 h-4" /> Loading your documents…
                  </div>
                ) : !docs.length ? (
                  <div className="rounded-2xl border border-slate-200 bg-white p-6 text-center">
                    <p className="text-sm font-medium text-slate-700 mb-1">No documents yet</p>
                    <p className="text-xs text-slate-500">Drop a file above or use Browse Files. Once uploaded, press Analyse to extract the case report.</p>
                  </div>
                ) : (
                  <div className="flex flex-col gap-3">
                    {docs.map(doc => (
                      <div
                        key={doc.key}
                        className={`
                          rounded-2xl border bg-white shadow-sm transition-all duration-200 hover:shadow-md
                          ${expanded === doc.key ? 'border-green-300 ring-4 ring-green-100' : 'border-slate-200'}
                        `}
                      >
                        <div
                          className="flex items-center gap-4 p-4 cursor-pointer"
                          onClick={() => doc.status === 'analyzed' && setExpanded(e => (e === doc.key ? null : doc.key))}
                        >
                          <div className="w-11 h-11 bg-green-50 border border-green-100 rounded-xl flex items-center justify-center text-green-600 flex-shrink-0">
                            <Icon d={typeIcon(doc.type)} className="w-5 h-5" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-slate-900 mb-0.5 truncate">{doc.filename}</p>
                            <p className="text-xs text-slate-500">
                              {doc.type}{doc.size ? ` · ${doc.size}` : ''}
                              {doc.status === 'analyzed' ? ' · analysed' : ''}
                            </p>
                            {doc.status === 'analyzing' && <ProgressBar value={60} />}
                          </div>
                          <div className="flex items-center gap-2 flex-shrink-0">
                            {doc.status === 'analyzed' && (
                              <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-full px-2 py-0.5">
                                <Icon d={I.check} className="w-3 h-3" />
                                Analysed
                              </span>
                            )}
                            {doc.status === 'ready' && (
                              <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-full px-2 py-0.5">
                                <Icon d={I.check} className="w-3 h-3" />
                                Ready
                              </span>
                            )}
                            {doc.status === 'analyzing' && (
                              <span className="inline-flex items-center gap-1.5 text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-full px-2 py-0.5">
                                <Spinner className="w-3 h-3" />
                                Analysing…
                              </span>
                            )}
                            {doc.status === 'error' && (
                              <span className="inline-flex items-center gap-1.5 text-xs text-rose-700 bg-rose-50 border border-rose-100 rounded-full px-2 py-0.5">
                                <Icon d={I.warn} className="w-3 h-3" />
                                Failed
                              </span>
                            )}
                            {doc.status !== 'analyzed' && (
                              <button
                                onClick={e => { e.stopPropagation(); analyse(doc); }}
                                disabled={doc.status === 'analyzing'}
                                className="inline-flex items-center gap-1.5 rounded-xl bg-green-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 active:scale-[0.98] disabled:opacity-50"
                              >
                                {doc.status === 'analyzing' ? <Spinner className="w-3 h-3" /> : null}
                                {doc.status === 'error' ? 'Retry' : 'Analyse'}
                              </button>
                            )}
                            <button
                              onClick={e => { e.stopPropagation(); download(doc); }}
                              disabled={busyKey === doc.key || doc.status === 'analyzing'}
                              aria-label={doc.document_id ? 'Download Word report' : 'Download document'}
                              title={doc.document_id ? 'Download Word report' : 'Download document'}
                              className="rounded-xl border border-slate-200 bg-white p-2 text-slate-500 shadow-sm transition-all duration-200 hover:border-slate-300 hover:text-slate-700 hover:shadow-md disabled:opacity-50"
                            >
                              {busyKey === doc.key ? <Spinner className="w-4 h-4" /> : <Icon d={I.download} className="w-4 h-4" />}
                            </button>
                          </div>
                        </div>

                        {doc.status === 'error' && doc.error && (
                          <p className="px-5 pb-4 text-[12px] leading-relaxed text-rose-600">{doc.error}</p>
                        )}

                        {/* Expanded analysis */}
                        {expanded === doc.key && doc.status === 'analyzed' && (
                          <div className="px-5 pb-5 border-t border-slate-100 pt-4">
                            <div className="flex flex-wrap gap-2 mb-4">
                              <button
                                onClick={() => discuss(doc)}
                                disabled={busyKey === doc.key}
                                className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98] disabled:opacity-60"
                              >
                                {busyKey === doc.key ? <Spinner /> : <Icon d={I.chat} className="w-4 h-4" />}
                                Discuss with AI
                              </button>
                              <button
                                onClick={() => generateOnly(doc)}
                                disabled={busyKey === doc.key}
                                className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm transition-all duration-200 hover:border-green-300 hover:text-green-700 hover:bg-green-50 disabled:opacity-60"
                              >
                                <Icon d={I.doc} className="w-4 h-4" />
                                {doc.generated ? 'Regenerate Word' : 'Generate Word'}
                              </button>
                              <button
                                onClick={() => download(doc)}
                                disabled={busyKey === doc.key}
                                className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm transition-all duration-200 hover:border-green-300 hover:text-green-700 hover:bg-green-50 disabled:opacity-60"
                              >
                                <Icon d={I.download} className="w-4 h-4" />
                                Download
                              </button>
                            </div>
                            {doc.generated && (
                              <p className="mb-4 rounded-xl border border-green-200 bg-green-50 px-3.5 py-2 text-[12px] text-green-700">
                                Word report ready: {doc.generated.filename}
                              </p>
                            )}
                            <AnalysisCard
                              caseId={workspaceId}
                              document={{ document_id: doc.document_id, filename: doc.filename, report: doc.report, edits: doc.edits }}
                              onSaved={(updated) => patchDoc(doc.key, { report: updated.report, edits: updated.edits })}
                            />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Right column — FAISS precedents */}
            <aside className="hidden lg:flex flex-col gap-5 lg:sticky lg:top-0">
              <BentoCard className="p-5">
                <SectionLabel>Similar Precedents</SectionLabel>
                {precedents ? (
                  <CaseSlider retrieval={precedents} />
                ) : (
                  <p className="text-xs leading-relaxed text-slate-500">
                    After an analysis, matching judgments from the 43,978-case index appear here. Open a card to read the full case.
                  </p>
                )}
              </BentoCard>
            </aside>
          </div>
        </div>
      </main>
    </div>
  );
}