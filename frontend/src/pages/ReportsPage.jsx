import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AppSidebar from '../components/AppSidebar';
import {
  createCase, resetCasePromise, storeCaseId,
  listReports, downloadGeneratedDocumentById,
} from '../api/client';

/* ── Presentational helpers (UI only, matches ChatPage) ── */
const Icon = ({ d, className = 'w-4 h-4' }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {[].concat(d).map((p, i) => <path key={i} d={p} />)}
  </svg>
);

const I = {
  file: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6', 'M8 13h8', 'M8 17h5'],
  download: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M7 10l5 5 5-5', 'M12 15V3'],
  check: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M8 12l3 3 5-6'],
  clock: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 7v5l3 2'],
  alert: ['M12 9v4', 'M12 17h.01', 'M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'],
  calendar: ['M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z', 'M16 3v4M8 3v4M3 11h18'],
  court: ['M3 9l9-6 9 6H3z', 'M3 21h18', 'M5 18v-6M10 18v-6M14 18v-6M19 18v-6'],
  edit: ['M16 3l5 5L9 20l-6 1 1-6z'],
  spinner: 'M20 12a8 8 0 1 1-8-8',
};

const BentoCard = ({ children, className = '', style }) => (
  <div style={style} className={`rounded-2xl border border-slate-200 bg-white shadow-sm transition-all duration-200 hover:shadow-md ${className}`}>
    {children}
  </div>
);

const formatDate = (iso) => {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
};

/* Colour + icon per server status label. Ready is green, in-progress is amber,
   anything needing attention (missing file / failed generation) is rose. */
const statusStyle = (status) => {
  if (status === 'Ready') return { chip: 'text-emerald-700 bg-emerald-50 border-emerald-100', icon: I.check };
  if (status === 'File missing' || status === 'Needs attention') return { chip: 'text-rose-700 bg-rose-50 border-rose-100', icon: I.alert };
  return { chip: 'text-amber-700 bg-amber-50 border-amber-100', icon: I.clock };
};

export default function ReportsPage() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('All');
  const [reports, setReports] = useState([]);
  const [summary, setSummary] = useState({ total: 0, ready: 0, drafts: 0, this_week: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    listReports()
      .then((r) => {
        if (!alive) return;
        setReports(r.reports || []);
        setSummary(r.summary || { total: 0, ready: 0, drafts: 0, this_week: 0 });
      })
      .catch((e) => { if (alive) setError(e.message || 'Could not load your reports.'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const filters = useMemo(() => {
    const types = [...new Set(reports.map((r) => r.type))];
    const statuses = [...new Set(reports.map((r) => r.status))];
    return ['All', ...types, ...statuses];
  }, [reports]);

  const filtered = filter === 'All'
    ? reports
    : reports.filter((r) => r.type === filter || r.status === filter);

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

  const openReportInChat = (report) => {
    if (report.runtime_case_id) openCaseInChat(report.runtime_case_id);
    else navigate('/chat');
  };

  const download = async (report) => {
    setBusyId(report.id);
    try {
      const blob = await downloadGeneratedDocumentById(report.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = report.filename || `${report.title.replace(/[^\w.-]+/g, '_') || 'report'}.docx`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message || 'The download failed.');
    } finally {
      setBusyId(null);
    }
  };

  const stats = [
    ['Total Reports', summary.total, I.file],
    ['Ready', summary.ready, I.check],
    ['Drafts', summary.drafts, I.edit],
    ['This Week', summary.this_week, I.calendar],
  ];

  return (
    <div className="flex h-full overflow-hidden bg-page text-slate-800 antialiased">

      <AppSidebar
        activeCaseId={null}
        onOpenCase={openCaseInChat}
        onNewConversation={newCaseInChat}
      />

      {/* ── Main ── */}
      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-16 flex-shrink-0 flex items-center justify-between px-6 md:px-8 bg-white/80 backdrop-blur border-b border-slate-200">
          <div className="flex items-center gap-3 min-w-0">
            <h1 className="text-[15px] font-semibold text-slate-900 truncate">Legal Reports</h1>
            <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-full px-2 py-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              {summary.ready} ready
            </span>
            <span className="hidden md:inline text-xs text-slate-500">Drafts you have generated</span>
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

            {/* Stats */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {stats.map(([l, v, ic]) => (
                <BentoCard key={l} className="p-5">
                  <div className="flex items-center justify-between mb-3">
                    <p className="text-xs font-medium text-slate-500">{l}</p>
                    <div className="w-7 h-7 rounded-lg bg-green-50 text-green-600 flex items-center justify-center">
                      <Icon d={ic} className="w-3.5 h-3.5" />
                    </div>
                  </div>
                  <p className="text-2xl font-semibold tracking-tight text-slate-900">{v}</p>
                </BentoCard>
              ))}
            </div>

            {error && (
              <BentoCard className="flex items-start gap-3 border-rose-200 bg-rose-50 p-4">
                <Icon d={I.alert} className="w-4 h-4 text-rose-600 mt-0.5" />
                <p className="text-[13px] text-rose-700">{error}</p>
              </BentoCard>
            )}

            {/* Filter chips */}
            {!loading && reports.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-xs font-medium text-slate-500">Your documents</h3>
                  <span className="text-xs text-slate-400" aria-live="polite">{filtered.length} {filtered.length === 1 ? 'report' : 'reports'}</span>
                </div>
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {filters.map(f => (
                    <button
                      key={f}
                      onClick={() => setFilter(f)}
                      aria-pressed={filter === f}
                      className={`flex-shrink-0 rounded-full border px-3.5 py-1.5 text-xs font-medium shadow-sm transition-all duration-200
                        ${filter === f
                          ? 'border-green-600 bg-green-600 text-white'
                          : 'border-slate-200 bg-white text-slate-600 hover:border-green-300 hover:text-green-700 hover:bg-green-50 hover:-translate-y-0.5'}`}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Loading */}
            {loading && (
              <div className="flex items-center justify-center gap-2 py-16 text-slate-400">
                <Icon d={I.spinner} className="w-5 h-5 animate-spin" />
                <span className="text-sm">Loading your reports…</span>
              </div>
            )}

            {/* Report cards */}
            {!loading && filtered.length > 0 && (
              <div className="flex flex-col gap-4">
                {filtered.map(r => {
                  const tone = statusStyle(r.status);
                  return (
                    <BentoCard key={`${r.kind}-${r.id}`} className="p-5 md:p-6">
                      <div className="flex items-start gap-4">
                        <div className="hidden sm:flex w-10 h-10 flex-shrink-0 rounded-xl bg-green-50 border border-green-100 text-green-600 items-center justify-center">
                          <Icon d={I.file} className="w-5 h-5" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                            <span className="text-[11px] font-medium text-green-600">{r.type}</span>
                            <span className={`inline-flex items-center gap-1.5 text-xs rounded-full px-2 py-0.5 border ${tone.chip}`}>
                              <Icon d={tone.icon} className="w-3 h-3" />
                              {r.status}
                            </span>
                          </div>
                          <h2 className="text-[15px] font-semibold text-slate-900 break-words">{r.title}</h2>
                          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-slate-500">
                            {r.date && <span className="inline-flex items-center gap-1.5"><Icon d={I.calendar} className="w-3.5 h-3.5 text-slate-400" />{formatDate(r.date)}</span>}
                            {r.case_number && <span className="inline-flex items-center gap-1.5"><Icon d={I.file} className="w-3.5 h-3.5 text-slate-400" />FIR {r.case_number}</span>}
                            {r.court && <span className="inline-flex items-center gap-1.5"><Icon d={I.court} className="w-3.5 h-3.5 text-slate-400" />{r.court}</span>}
                          </div>

                          {r.snippet && (
                            <p className="mt-4 rounded-xl bg-slate-50 border border-slate-100 px-4 py-3 text-[13px] leading-6 text-slate-600">
                              {r.snippet}
                            </p>
                          )}

                          <div className="mt-4 flex flex-wrap items-center gap-2">
                            {r.kind === 'document' ? (
                              <button
                                onClick={() => download(r)}
                                disabled={!r.downloadable || busyId === r.id}
                                title={r.downloadable ? '' : 'The generated file is no longer available on the server.'}
                                className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-green-600"
                              >
                                <Icon d={busyId === r.id ? I.spinner : I.download} className={`w-4 h-4 ${busyId === r.id ? 'animate-spin' : ''}`} />
                                {r.downloadable ? 'Download DOCX' : 'File unavailable'}
                              </button>
                            ) : (
                              <button
                                onClick={() => openReportInChat(r)}
                                className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98]"
                              >
                                <Icon d={I.edit} />Continue drafting
                              </button>
                            )}
                            <button
                              onClick={() => openReportInChat(r)}
                              className="sm:ml-auto inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm transition-all duration-200 hover:border-green-300 hover:text-green-700 hover:bg-green-50"
                            >
                              <Icon d={I.edit} />Edit via AI Chat
                            </button>
                          </div>
                        </div>
                      </div>
                    </BentoCard>
                  );
                })}
              </div>
            )}

            {/* Empty states */}
            {!loading && reports.length === 0 && (
              <BentoCard className="py-16 text-center">
                <div className="mx-auto mb-4 w-12 h-12 rounded-xl bg-green-50 border border-green-100 text-green-600 flex items-center justify-center">
                  <Icon d={I.file} className="w-6 h-6" />
                </div>
                <p className="text-[15px] font-semibold text-slate-900">No reports yet</p>
                <p className="mt-1 text-sm text-slate-500">Draft a bail application or other document in the assistant and it will appear here.</p>
                <button
                  onClick={() => navigate('/chat')}
                  className="mt-5 inline-flex items-center gap-2 rounded-xl bg-green-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md"
                >
                  Open assistant
                </button>
              </BentoCard>
            )}

            {!loading && reports.length > 0 && filtered.length === 0 && (
              <BentoCard className="py-16 text-center">
                <div className="mx-auto mb-4 w-12 h-12 rounded-xl bg-green-50 border border-green-100 text-green-600 flex items-center justify-center">
                  <Icon d={I.file} className="w-6 h-6" />
                </div>
                <p className="text-[15px] font-semibold text-slate-900">No reports match this filter</p>
                <p className="mt-1 text-sm text-slate-500">Try a different filter or generate a new report.</p>
              </BentoCard>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
