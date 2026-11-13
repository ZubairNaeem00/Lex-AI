import React from 'react';
import { useNavigate } from 'react-router-dom';

const STATS = [
  { label: 'Total Cases',      value: '13',  icon: '⚖️', sub: '+2 this month',    sub_color: 'text-jade' },
  { label: 'Documents',        value: '47',  icon: '📁', sub: '4 pending review', sub_color: 'text-gold' },
  { label: 'Reports Generated',value: '28',  icon: '📋', sub: '3 this week',      sub_color: 'text-jade' },
  { label: 'Avg. NLP Accuracy',value: '91%', icon: '🎯', sub: 'Above target',     sub_color: 'text-jade' },
];

const CASES = [
  { id: '0234/2024', title: 'State vs. Muhammad Arif', type: 'Murder · PPC §302',  status: 'Active', court: 'Sessions Lahore',    docs: 3 },
  { id: '0189/2024', title: 'Ali Hassan vs. State',    type: 'Theft · PPC §379',   status: 'Active', court: 'Magistrate Lahore', docs: 2 },
  { id: '0107/2023', title: 'Khalid Mehmood — Bail',   type: 'CNSA §9(c)',         status: 'Closed', court: 'LHC',               docs: 5 },
];

const ACTIVITY = [
  { icon: '📄', text: 'FIR_0234 analysed — 14 entities extracted',          time: '2 min ago' },
  { icon: '📋', text: 'Bail application generated for Case 0234',            time: '15 min ago' },
  { icon: '🔍', text: '3 LHC precedents retrieved for §302 case',            time: '1 hr ago' },
  { icon: '🖼️', text: 'OCR completed — WitnessStatement.jpg',               time: '2 hr ago' },
  { icon: '🎙️', text: 'Voice input processed — Case 0189 details recorded', time: '3 hr ago' },
];

const QUICK_ACTIONS = [
  { icon: '📤', title: 'Upload Document',  desc: 'FIR, court order, witness statement', path: '/upload' },
  { icon: '💬', title: 'AI Legal Chat',    desc: 'Ask about statutes or precedents',    path: '/chat' },
  { icon: '📋', title: 'View Reports',     desc: 'Download case files and drafts',      path: '/reports' },
];

/* ── Presentational helpers (UI only, no logic) ── */
// Maps the old theme colour names in STATS to the new palette (data untouched).
const SUB_TONE = {
  'text-jade': 'text-emerald-700 bg-emerald-50 border-emerald-100',
  'text-gold': 'text-amber-700 bg-amber-50 border-amber-100',
};

const BentoCard = ({ children, className = '' }) => (
  <div className={`rounded-2xl border border-slate-200 bg-white shadow-sm transition-all duration-200 hover:shadow-md ${className}`}>
    {children}
  </div>
);

const CardHeader = ({ title, action }) => (
  <div className="flex items-center justify-between px-6 pt-5 pb-4">
    <h2 className="text-[15px] font-semibold tracking-tight text-slate-900">{title}</h2>
    {action}
  </div>
);

const GhostButton = ({ children, onClick }) => (
  <button
    onClick={onClick}
    className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm transition-all duration-200 hover:border-slate-300 hover:bg-slate-50 hover:shadow-md"
  >
    {children}
  </button>
);

const PrimaryButton = ({ children, onClick, small }) => (
  <button
    onClick={onClick}
    className={`rounded-xl bg-green-600 font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98]
      ${small ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm'}`}
  >
    {children}
  </button>
);

export default function DashboardPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-full bg-slate-50 text-slate-800 antialiased">
      <div className="max-w-[1200px] mx-auto px-8 py-10">

        {/* Header */}
        <header className="flex flex-wrap items-end justify-between gap-6 mb-10">
          <div>
            <p className="text-sm font-medium text-green-600 mb-2">Overview</p>
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Good morning, Counsellor</h1>
            <p className="mt-2 text-sm text-slate-500">
              Thursday, 12 March 2026 ·{' '}
              <span className="font-medium text-slate-700">2 active cases</span> need attention
            </p>
          </div>
          <div className="flex items-center gap-3">
            <GhostButton onClick={() => navigate('/upload')}>Upload document</GhostButton>
            <PrimaryButton onClick={() => navigate('/chat')}>Ask AI</PrimaryButton>
          </div>
        </header>

        {/* Stats */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {STATS.map(s => (
            <BentoCard key={s.label} className="p-5 hover:-translate-y-0.5">
              <div className="flex items-center justify-between mb-6">
                <p className="text-sm text-slate-500">{s.label}</p>
                <span className="w-9 h-9 rounded-xl bg-slate-50 border border-slate-200 flex items-center justify-center text-base">
                  {s.icon}
                </span>
              </div>
              <p className="text-3xl font-semibold tracking-tight text-slate-900">{s.value}</p>
              <span className={`mt-3 inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${SUB_TONE[s.sub_color] || 'text-slate-600 bg-slate-50 border-slate-200'}`}>
                {s.sub}
              </span>
            </BentoCard>
          ))}
        </div>

        {/* Bento: cases + activity */}
        <div className="grid lg:grid-cols-[1fr_340px] gap-4 mb-6">

          {/* Cases */}
          <BentoCard className="overflow-hidden">
            <CardHeader title="Active cases" action={<GhostButton>View all</GhostButton>} />
            <div className="px-3 pb-3">
              {CASES.map((c, i) => (
                <div
                  key={c.id}
                  className={`flex items-center gap-4 px-3 py-4 rounded-xl transition-colors duration-150 hover:bg-slate-50
                    ${i < CASES.length - 1 ? 'border-b border-slate-100' : ''}`}
                >
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-lg flex-shrink-0 border
                    ${c.status === 'Active' ? 'bg-green-50 border-green-100' : 'bg-slate-50 border-slate-200 grayscale'}`}>
                    ⚖️
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-900 truncate">{c.title}</p>
                    <p className="mt-0.5 text-xs text-slate-500 truncate">
                      <span className="font-mono text-slate-400">{c.id}</span> · {c.type} · {c.court}
                    </p>
                  </div>
                  <div className="hidden sm:flex flex-col items-end gap-1 flex-shrink-0">
                    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium
                      ${c.status === 'Active'
                        ? 'text-emerald-700 bg-emerald-50 border-emerald-100'
                        : 'text-slate-500 bg-slate-50 border-slate-200'}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${c.status === 'Active' ? 'bg-emerald-500' : 'bg-slate-400'}`} />
                      {c.status}
                    </span>
                    <span className="text-[11px] text-slate-400">{c.docs} docs</span>
                  </div>
                  <PrimaryButton small onClick={() => navigate('/upload')}>Open</PrimaryButton>
                </div>
              ))}
            </div>
          </BentoCard>

          {/* Activity timeline */}
          <BentoCard className="overflow-hidden">
            <CardHeader title="Recent activity" />
            <ol className="relative px-6 pb-5">
              <span className="absolute left-[39px] top-2 bottom-7 w-px bg-slate-200" />
              {ACTIVITY.map((a, i) => (
                <li key={i} className="relative flex gap-3.5 py-2.5">
                  <span className="relative z-10 w-8 h-8 flex-shrink-0 rounded-full bg-white border border-slate-200 shadow-sm flex items-center justify-center text-sm">
                    {a.icon}
                  </span>
                  <div className="min-w-0 pt-1">
                    <p className="text-[13px] leading-snug text-slate-700">{a.text}</p>
                    <p className="mt-1 text-[11px] text-slate-400">{a.time}</p>
                  </div>
                </li>
              ))}
            </ol>
          </BentoCard>
        </div>

        {/* Quick actions */}
        <div className="grid md:grid-cols-3 gap-4">
          {QUICK_ACTIONS.map(q => (
            <button
              key={q.title}
              onClick={() => navigate(q.path)}
              className="group text-left rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition-all duration-200 hover:-translate-y-1 hover:border-green-200 hover:shadow-md"
            >
              <div className="flex items-start justify-between">
                <span className="w-11 h-11 rounded-xl bg-green-50 border border-green-100 flex items-center justify-center text-xl transition-transform duration-200 group-hover:scale-105">
                  {q.icon}
                </span>
                <span className="text-slate-300 transition-all duration-200 group-hover:text-green-600 group-hover:translate-x-0.5">→</span>
              </div>
              <p className="mt-5 text-[15px] font-semibold tracking-tight text-slate-900">{q.title}</p>
              <p className="mt-1 text-sm text-slate-500 leading-relaxed">{q.desc}</p>
            </button>
          ))}
        </div>

      </div>
    </div>
  );
}