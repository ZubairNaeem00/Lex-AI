import React, { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

const INITIAL_DOCS = [
  { name: 'FIR_0234_Lahore_2024.pdf', type: 'PDF', size: '240 KB', progress: 100, status: 'done' },
  { name: 'WitnessStatement_Scan.jpg', type: 'IMG', size: '1.2 MB', progress: 100, status: 'done' },
  { name: 'CourtOrder_LHC_March2024.pdf', type: 'PDF', size: '1.1 MB', progress: 68, status: 'processing' },
];

const ANALYSIS = {
  entities: [
    ['Accused',        'Muhammad Arif s/o Abdul Aziz'],
    ['Complainant',    'Shahid Mehmood'],
    ['Date',           '12 March 2024, ~22:30'],
    ['Location',       'Plot 44-A, Gulshan Ravi, Lahore'],
    ['Police Station', 'Data Ganj Bakhsh, Lahore'],
    ['Witnesses',      '3 eyewitnesses cited'],
  ],
  statutes: ['PPC §302 — Qatl-e-Amd', 'PPC §34 — Common Intention', 'PPC §109 — Abetment', 'CrPC §154 — FIR Procedure'],
  summary: 'FIR registered by Shahid Mehmood alleging Qatl-e-Amd by Muhammad Arif. Incident at Gulshan Ravi, Lahore at 22:30 hrs. Three eyewitnesses. Weapon: .30 bore pistol recovered. No prior record on file.',
};

const STATUTES = [
  ['PPC §302',  'Qatl-e-Amd — Death or life imprisonment'],
  ['PPC §34',   'Acts in furtherance of common intention'],
  ['PPC §109',  'Punishment of abetment'],
  ['CrPC §497', 'Bail in non-bailable offence'],
];

const PRECEDENTS = [
  ['State vs. Ghulam Hussain', 'LHC 2019 · PLC (Cr.) 445', 92],
  ['Muhammad Aslam vs. State', 'SC 2021 · SCMR 887',       78],
  ['Tariq Bashir vs. State',   'LHC 2022 · YLR 1204',      71],
];

/* ── Presentational helpers (UI only, matches ChatPage / ReportsPage) ── */
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
  clock: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 7v5l3 2'],
  mic: ['M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z', 'M19 10v2a7 7 0 0 1-14 0v-2', 'M12 19v4', 'M8 23h8'],
  stop: ['M7 7h10v10H7z'],
  chat: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z',
  chart: ['M3 3v18h18', 'M7 15l4-4 3 3 5-6'],
  scale: ['M12 3v18', 'M5 21h14', 'M12 6h-5l-3 6a3.5 3.5 0 0 0 6 0l-3-6', 'M17 6h5l-3 6a3.5 3.5 0 0 0 6 0l-3-6', 'M7 6h10'],
  user: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6'],
  folder: 'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z',
  book: ['M4 19.5A2.5 2.5 0 0 1 6.5 17H20', 'M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z'],
  doc: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6', 'M16 13H8', 'M16 17H8', 'M10 9H8'],
};

const BentoCard = ({ children, className = '', style }) => (
  <div style={style} className={`rounded-2xl border border-slate-200 bg-white shadow-sm transition-all duration-200 hover:shadow-md ${className}`}>
    {children}
  </div>
);

const SectionLabel = ({ children }) => (
  <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-3">{children}</p>
);

const ProgressBar = ({ value }) => (
  <div className="mt-2 h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
    <div
      className={`h-full rounded-full transition-all duration-300 ${value >= 100 ? 'bg-emerald-500' : 'bg-green-600'}`}
      style={{ width: `${value}%` }}
    />
  </div>
);

const SimilarityBar = ({ value }) => (
  <div>
    <div className="h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
      <div className="h-full rounded-full bg-green-600" style={{ width: `${value}%` }} />
    </div>
    <p className="mt-1 text-[10px] font-medium text-slate-400">{value}% similarity</p>
  </div>
);

const typeIcon = (t) => (t === 'IMG' ? I.image : I.file);

export default function UploadPage() {
  const navigate  = useNavigate();
  const inputRef  = useRef(null);
  const [docs, setDocs]           = useState(INITIAL_DOCS);
  const [dragging, setDragging]   = useState(false);
  const [expanded, setExpanded]   = useState(null);
  const [recording, setRecording] = useState(false);

  const addDoc = (name, size) => {
    const ext = name.split('.').pop().toUpperCase();
    setDocs(d => [...d, { name, type: ext, size: `${Math.round(size / 1024)} KB`, progress: 0, status: 'processing' }]);
    let p = 0;
    const iv = setInterval(() => {
      p += Math.random() * 18;
      if (p >= 100) {
        p = 100;
        clearInterval(iv);
        setDocs(d => d.map(x => x.name === name ? { ...x, progress: 100, status: 'done' } : x));
      } else {
        setDocs(d => d.map(x => x.name === name ? { ...x, progress: Math.round(p) } : x));
      }
    }, 220);
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    Array.from(e.dataTransfer.files).forEach(f => addDoc(f.name, f.size));
  };

  const readyCount = docs.filter(d => d.status === 'done').length;

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
            onClick={() => inputRef.current?.click()}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-green-600 text-white text-sm font-medium py-2.5 shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98]"
          >
            <Icon d={I.upload} className="w-4 h-4" />
            Upload document
          </button>
        </div>

        <div className="px-3 pb-2">
          <p className="px-2 mb-1 text-[11px] font-medium text-slate-400">Workspace</p>
          {[
            { label: 'Assistant', icon: I.chat,   to: '/chat' },
            { label: 'Reports',   icon: I.chart,  to: '/reports' },
            { label: 'Upload',    icon: I.upload, active: true },
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
          <p className="px-2 mb-1 text-[11px] font-medium text-slate-400">Analysis</p>
          <div className="rounded-xl bg-slate-50 border border-slate-100 p-3 mb-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] text-slate-500">Documents ready</span>
              <span className="text-sm font-semibold text-slate-900">{readyCount}<span className="text-slate-400">/{docs.length}</span></span>
            </div>
            <ProgressBar value={docs.length ? Math.round((readyCount / docs.length) * 100) : 0} />
          </div>
          {STATUTES.slice(0, 2).map(([code]) => (
            <div key={code} className="flex items-center gap-2 px-2.5 py-1.5 text-[13px] text-slate-600">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0" />
              {code}
            </div>
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
            <h1 className="text-[15px] font-semibold text-slate-900 truncate">Upload Legal Documents</h1>
            <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-full px-2 py-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              {readyCount} ready
            </span>
            <span className="hidden md:inline text-xs text-slate-500">FIRs · Court orders · Statements</span>
          </div>
          <button
            onClick={() => navigate('/chat')}
            className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm transition-all duration-200 hover:border-slate-300 hover:shadow-md"
          >
            Open assistant
          </button>
        </header>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-6xl mx-auto px-6 md:px-8 py-8 grid lg:grid-cols-[1fr_300px] gap-6 items-start">

            {/* Left column */}
            <div className="flex flex-col gap-6 min-w-0">

              {/* Drop zone */}
              <div
                onDragOver={e => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                onClick={() => inputRef.current?.click()}
                className={`
                  rounded-2xl border-2 border-dashed p-10 text-center cursor-pointer bg-white shadow-sm
                  transition-all duration-200
                  ${dragging
                    ? 'border-green-500 bg-green-50/70 scale-[1.01] shadow-md'
                    : 'border-slate-200 hover:border-green-300 hover:bg-green-50/30'}
                `}
              >
                <input ref={inputRef} type="file" multiple className="hidden"
                       onChange={e => Array.from(e.target.files).forEach(f => addDoc(f.name, f.size))} />
                <div className="mx-auto mb-4 w-12 h-12 rounded-xl bg-green-50 border border-green-100 text-green-600 flex items-center justify-center">
                  <Icon d={I.folder} className="w-6 h-6" />
                </div>
                <h3 className="text-lg font-semibold tracking-tight text-slate-900 mb-1.5">Upload Legal Documents</h3>
                <p className="text-slate-500 text-sm mb-5 leading-relaxed">
                  Drop FIRs, court orders, witness statements,<br />or scanned images here
                </p>
                <div className="flex gap-2 justify-center flex-wrap mb-6">
                  {['.pdf', '.jpg/.png', '.docx', '.txt'].map(t => (
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

              {/* Voice input */}
              <BentoCard className="p-5">
                <div className="flex items-center justify-between mb-4">
                  <p className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                    <Icon d={I.mic} className="w-4 h-4 text-green-600" />
                    Voice Input
                  </p>
                  <span className="text-xs text-slate-500">Supports Urdu &amp; English</span>
                </div>
                <div className="flex items-center gap-5">
                  <button
                    onClick={() => setRecording(r => !r)}
                    aria-pressed={recording}
                    className={`
                      w-14 h-14 rounded-full flex items-center justify-center flex-shrink-0
                      border-2 transition-all duration-300
                      ${recording
                        ? 'border-red-200 bg-red-50 text-red-600 shadow-[0_0_0_8px_rgba(239,68,68,.08)]'
                        : 'border-green-200 bg-green-50 text-green-600 hover:bg-green-100 hover:shadow-md'}
                    `}
                  >
                    <Icon d={recording ? I.stop : I.mic} className="w-5 h-5" />
                  </button>
                  <div>
                    <p className={`text-sm font-medium mb-1 ${recording ? 'text-red-600' : 'text-slate-900'}`}>
                      {recording ? 'Recording in progress…' : 'Click to start recording'}
                    </p>
                    <p className="text-xs text-slate-500">
                      {recording ? 'Live — speak your case details clearly' : 'Dictate FIR details, accused info, or case notes'}
                    </p>
                  </div>
                </div>
              </BentoCard>

              {/* Document list */}
              <div>
                <SectionLabel>Uploaded Documents ({docs.length})</SectionLabel>
                <div className="flex flex-col gap-3">
                  {docs.map(doc => (
                    <div
                      key={doc.name}
                      className={`
                        rounded-2xl border bg-white shadow-sm transition-all duration-200 cursor-pointer hover:shadow-md
                        ${expanded === doc.name ? 'border-green-300 ring-4 ring-green-100' : 'border-slate-200'}
                      `}
                      onClick={() => setExpanded(e => e === doc.name ? null : doc.name)}
                    >
                      <div className="flex items-center gap-4 p-4">
                        <div className="w-11 h-11 bg-green-50 border border-green-100 rounded-xl flex items-center justify-center text-green-600 flex-shrink-0">
                          <Icon d={typeIcon(doc.type)} className="w-5 h-5" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-slate-900 mb-0.5 truncate">{doc.name}</p>
                          <p className="text-xs text-slate-500">{doc.type} · {doc.size}</p>
                          <ProgressBar value={doc.progress} />
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          {doc.status === 'done' ? (
                            <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-full px-2 py-0.5">
                              <Icon d={I.check} className="w-3 h-3" />
                              Ready
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-full px-2 py-0.5 font-mono">
                              <Icon d={I.clock} className="w-3 h-3" />
                              {doc.progress}%
                            </span>
                          )}
                          <button
                            onClick={e => { e.stopPropagation(); doc.status === 'done' && setExpanded(doc.name); }}
                            className="inline-flex items-center gap-1.5 rounded-xl bg-green-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 active:scale-[0.98] disabled:opacity-50"
                            disabled={doc.status !== 'done'}
                          >
                            Analyse
                          </button>
                          <button
                            onClick={e => e.stopPropagation()}
                            aria-label="Download document"
                            className="rounded-xl border border-slate-200 bg-white p-2 text-slate-500 shadow-sm transition-all duration-200 hover:border-slate-300 hover:text-slate-700 hover:shadow-md"
                          >
                            <Icon d={I.download} className="w-4 h-4" />
                          </button>
                        </div>
                      </div>

                      {/* Expanded analysis panel */}
                      {expanded === doc.name && doc.status === 'done' && (
                        <div className="px-5 pb-5 border-t border-slate-100 pt-4" onClick={e => e.stopPropagation()}>
                          {/* Summary */}
                          <div className="rounded-xl bg-slate-50 border border-slate-100 p-4 mb-4">
                            <SectionLabel>AI Case Summary</SectionLabel>
                            <p className="text-sm text-slate-600 leading-relaxed">{ANALYSIS.summary}</p>
                          </div>

                          {/* Entities grid */}
                          <SectionLabel>Extracted Entities</SectionLabel>
                          <div className="grid grid-cols-2 lg:grid-cols-3 gap-2.5 mb-4">
                            {ANALYSIS.entities.map(([label, value]) => (
                              <div key={label} className="rounded-xl bg-white border border-slate-200 p-3 shadow-sm">
                                <p className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">{label}</p>
                                <p className="text-sm font-medium text-slate-800 leading-snug">{value}</p>
                              </div>
                            ))}
                          </div>

                          {/* Statutes */}
                          <SectionLabel>Matched Statutes</SectionLabel>
                          <div className="flex flex-wrap gap-2 mb-5">
                            {ANALYSIS.statutes.map(s => (
                              <span key={s} className="inline-flex items-center gap-1.5 rounded-full border border-green-100 bg-green-50 px-3 py-1 text-xs font-medium text-green-700">
                                <Icon d={I.book} className="w-3 h-3" />
                                {s}
                              </span>
                            ))}
                          </div>

                          <div className="flex gap-3">
                            <button
                              onClick={() => navigate('/reports')}
                              className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98]"
                            >
                              <Icon d={I.doc} className="w-4 h-4" />
                              Generate Report
                            </button>
                            <button
                              onClick={() => navigate('/chat')}
                              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm transition-all duration-200 hover:border-green-300 hover:text-green-700 hover:bg-green-50"
                            >
                              <Icon d={I.chat} className="w-4 h-4" />
                              Discuss with AI
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Right column — Matched Statutes & Similar Precedents */}
            <aside className="hidden lg:flex flex-col gap-5 lg:sticky lg:top-0">
              <BentoCard className="p-5">
                <SectionLabel>Matched Statutes</SectionLabel>
                <div className="flex flex-col gap-2.5">
                  {STATUTES.map(([code, desc]) => (
                    <div key={code} className="rounded-xl border border-slate-200 bg-slate-50/50 p-3.5 cursor-pointer transition-all duration-200 hover:border-green-300 hover:bg-green-50/50">
                      <p className="text-xs font-semibold text-green-700 mb-1">{code}</p>
                      <p className="text-xs text-slate-500 leading-snug">{desc}</p>
                    </div>
                  ))}
                </div>
              </BentoCard>

              <BentoCard className="p-5">
                <SectionLabel>Similar Precedents</SectionLabel>
                <div className="flex flex-col gap-2.5">
                  {PRECEDENTS.map(([name, meta, score]) => (
                    <div key={name} className="rounded-xl border border-slate-200 bg-slate-50/50 p-3.5 cursor-pointer transition-all duration-200 hover:border-green-300 hover:bg-green-50/50">
                      <p className="text-sm font-medium text-slate-900 mb-1">{name}</p>
                      <p className="text-[11px] text-slate-500 mb-2">{meta}</p>
                      <SimilarityBar value={score} />
                    </div>
                  ))}
                </div>
              </BentoCard>
            </aside>
          </div>
        </div>
      </main>
    </div>
  );
}