import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';

const REPORTS = [
  {
    type: 'Bail Application',
    title: 'Bail Petition — Muhammad Arif vs. State',
    caseNo: '0234/2024',
    court: 'Lahore High Court',
    date: '12 Mar 2026',
    status: 'Ready',
    pages: 4,
    snippet: 'In the matter of Muhammad Arif s/o Abdul Aziz, the applicant is accused under PPC §302 and §34. It is respectfully submitted that the applicant was falsely implicated and the prosecution evidence remains circumstantial in nature…',
  },
  {
    type: 'Case Summary',
    title: 'Case Summary — FIR No. 0234/2024',
    caseNo: '0234/2024',
    court: 'Sessions Court Lahore',
    date: '12 Mar 2026',
    status: 'Ready',
    pages: 6,
    snippet: 'This case involves alleged Qatl-e-Amd occurring on 12 March 2024 within the jurisdiction of PS Data Ganj Bakhsh. Applicable statutes: PPC §302, §34, §109. Three eyewitnesses cited…',
  },
  {
    type: 'Legal Brief',
    title: 'Defence Arguments — Preliminary Hearing',
    caseNo: '0234/2024',
    court: 'Sessions Court Lahore',
    date: '11 Mar 2026',
    status: 'Draft',
    pages: 3,
    snippet: 'Defence intends to challenge admissibility of confession on grounds of duress (Article 38, Qanun-e-Shahadat). No independent corroboration exists for the sole eyewitness testimony…',
  },
  {
    type: 'Case Summary',
    title: 'Case Summary — FIR No. 0189/2024',
    caseNo: '0189/2024',
    court: 'Magistrate Court Lahore',
    date: '8 Feb 2026',
    status: 'Ready',
    pages: 2,
    snippet: "Theft case under PPC §379. Accused Ali Hassan allegedly stole property valued at Rs. 85,000 from complainant's residence. Two witnesses. CCTV evidence available…",
  },
];

const FILTERS = ['All', 'Bail Application', 'Case Summary', 'Legal Brief', 'Ready', 'Draft'];

/* ── Presentational helpers (UI only, matches ChatPage) ── */
const Icon = ({ d, className = 'w-4 h-4' }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {[].concat(d).map((p, i) => <path key={i} d={p} />)}
  </svg>
);

const I = {
  file: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6', 'M8 13h8', 'M8 17h5'],
  download: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M7 10l5 5 5-5', 'M12 15V3'],
  plus: 'M12 5v14M5 12h14',
  check: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M8 12l3 3 5-6'],
  clock: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 7v5l3 2'],
  calendar: ['M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z', 'M16 3v4M8 3v4M3 11h18'],
  court: ['M3 9l9-6 9 6H3z', 'M3 21h18', 'M5 18v-6M10 18v-6M14 18v-6M19 18v-6'],
  edit: ['M16 3l5 5L9 20l-6 1 1-6z'],
  spinner: 'M20 12a8 8 0 1 1-8-8',
  chat: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z',
  chart: ['M3 3v18h18', 'M7 15l4-4 3 3 5-6'],
  upload: ['M12 16V4', 'M6 10l6-6 6 6', 'M4 20h16'],
  user: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6'],
};

const BentoCard = ({ children, className = '', style }) => (
  <div style={style} className={`rounded-2xl border border-slate-200 bg-white shadow-sm transition-all duration-200 hover:shadow-md ${className}`}>
    {children}
  </div>
);

export default function ReportsPage() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('All');
  const [spinning, setSpinning] = useState(false);

  const filtered = filter === 'All'
    ? REPORTS
    : REPORTS.filter(r => r.type === filter || r.status === filter);

  const handleGenerate = () => {
    setSpinning(true);
    setTimeout(() => setSpinning(false), 2000);
  };

  return (
    <div className="flex h-full overflow-hidden bg-slate-50 text-slate-800 antialiased">

      {/* ── Sidebar navigation ── */}
      <nav className="w-[260px] flex-shrink-0 hidden md:flex flex-col bg-white border-r border-slate-200">
        <div className="flex items-center gap-2.5 px-5 h-16 border-b border-slate-200">
          <div className="w-7 h-7 rounded-lg bg-green-600 text-white flex items-center justify-center text-xs font-bold">L</div>
          <span className="text-[15px] font-semibold tracking-tight text-slate-900">LexAI</span>
          <span className="ml-auto text-[10px] font-medium text-green-600 bg-green-50 border border-green-100 rounded-md px-1.5 py-0.5">Beta</span>
        </div>

        <div className="p-4">
          <button
            onClick={handleGenerate}
            disabled={spinning}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-green-600 text-white text-sm font-medium py-2.5 shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98] disabled:opacity-70"
          >
            <Icon d={spinning ? I.spinner : I.plus} className={`w-4 h-4 ${spinning ? 'animate-spin' : ''}`} />
            {spinning ? 'Generating…' : 'New report'}
          </button>
        </div>

        <div className="px-3 pb-2">
          <p className="px-2 mb-1 text-[11px] font-medium text-slate-400">Workspace</p>
          {[
            { label: 'Assistant', icon: I.chat, to: '/chat' },
            { label: 'Reports', icon: I.chart, active: true },
            { label: 'Upload', icon: I.upload, to: '/upload' },
          ].map(item => (
            <button
              key={item.label}
              onClick={() => item.to && navigate(item.to)}
              className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-sm transition-colors duration-150
                ${item.active ? 'bg-slate-100 text-slate-900 font-medium' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'}`}
            >
              <Icon d={item.icon} className={`w-4 h-4 ${item.active ? 'text-green-600' : 'text-slate-400'}`} />
              {item.label}
            </button>
          ))}
        </div>

        <div className="px-3 pt-4 flex-1 overflow-y-auto">
          <p className="px-2 mb-1 text-[11px] font-medium text-slate-400">Filters</p>
          {FILTERS.map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`w-full text-left px-2.5 py-2 rounded-lg text-[13px] truncate transition-colors duration-150
                ${filter === f ? 'bg-green-50 text-green-700 font-medium' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'}`}
            >
              {f}
            </button>
          ))}
        </div>

        <div className="p-4 border-t border-slate-200">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-500">
              <Icon d={I.user} />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-medium text-slate-900 truncate">LexAI Co-Counsel</p>
              <p className="text-[11px] text-slate-500">PPC · CrPC · LHC · SC</p>
            </div>
          </div>
        </div>
      </nav>

      {/* ── Main ── */}
      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-16 flex-shrink-0 flex items-center justify-between px-6 md:px-8 bg-white/80 backdrop-blur border-b border-slate-200">
          <div className="flex items-center gap-3 min-w-0">
            <h1 className="text-[15px] font-semibold text-slate-900 truncate">Legal Reports</h1>
            <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-full px-2 py-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              3 ready
            </span>
            <span className="hidden md:inline text-xs text-slate-500">Case files · Bail · Briefs</span>
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
              {[['Total Reports', '4', I.file], ['Ready', '3', I.check], ['Drafts', '1', I.edit], ['This Week', '2', I.calendar]].map(([l, v, ic]) => (
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

            {/* Filter chips */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-medium text-slate-500">Your documents</h3>
                <span className="text-xs text-slate-400" aria-live="polite">{filtered.length} {filtered.length === 1 ? 'report' : 'reports'}</span>
              </div>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {FILTERS.map(f => (
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

            {/* Report cards */}
            <div className="flex flex-col gap-4">
              {filtered.map(r => (
                <BentoCard key={r.title} className="p-5 md:p-6">
                  <div className="flex items-start gap-4">
                    <div className="hidden sm:flex w-10 h-10 flex-shrink-0 rounded-xl bg-green-50 border border-green-100 text-green-600 items-center justify-center">
                      <Icon d={I.file} className="w-5 h-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                        <span className="text-[11px] font-medium text-green-600">{r.type}</span>
                        <span className={`inline-flex items-center gap-1.5 text-xs rounded-full px-2 py-0.5 border
                          ${r.status === 'Ready'
                            ? 'text-emerald-700 bg-emerald-50 border-emerald-100'
                            : 'text-amber-700 bg-amber-50 border-amber-100'}`}>
                          <Icon d={r.status === 'Ready' ? I.check : I.clock} className="w-3 h-3" />
                          {r.status}
                        </span>
                      </div>
                      <h2 className="text-[15px] font-semibold text-slate-900 break-words">{r.title}</h2>
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-slate-500">
                        <span className="inline-flex items-center gap-1.5"><Icon d={I.calendar} className="w-3.5 h-3.5 text-slate-400" />{r.date}</span>
                        <span className="inline-flex items-center gap-1.5"><Icon d={I.file} className="w-3.5 h-3.5 text-slate-400" />Case {r.caseNo}</span>
                        <span className="inline-flex items-center gap-1.5"><Icon d={I.court} className="w-3.5 h-3.5 text-slate-400" />{r.court}</span>
                        <span className="inline-flex items-center gap-1.5"><Icon d={I.file} className="w-3.5 h-3.5 text-slate-400" />{r.pages} pages</span>
                      </div>

                      <p className="mt-4 rounded-xl bg-slate-50 border border-slate-100 px-4 py-3 text-[13px] leading-6 text-slate-600">
                        {r.snippet}
                      </p>

                      <div className="mt-4 flex flex-wrap items-center gap-2">
                        <button className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98]">
                          <Icon d={I.download} />Download PDF
                        </button>
                        <button className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm transition-all duration-200 hover:border-slate-300 hover:shadow-md">
                          <Icon d={I.file} />Download DOCX
                        </button>
                        <button
                          onClick={() => navigate('/chat')}
                          className="sm:ml-auto inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm transition-all duration-200 hover:border-green-300 hover:text-green-700 hover:bg-green-50"
                        >
                          <Icon d={I.edit} />Edit via AI Chat
                        </button>
                      </div>
                    </div>
                  </div>
                </BentoCard>
              ))}
            </div>

            {filtered.length === 0 && (
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