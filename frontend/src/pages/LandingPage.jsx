import React from 'react';
import { useNavigate } from 'react-router-dom';

const FEATURES = [
  { icon: '🔍', title: 'Smart NLP Extraction',    desc: 'Identifies accused, victims, dates, locations, and applicable law sections from FIRs and court documents automatically.' },
  { icon: '🗂️', title: 'RAG Precedent Retrieval', desc: 'Semantic FAISS vector search across thousands of Pakistani court judgments — relevant precedents surfaced in milliseconds.' },
  { icon: '📸', title: 'OCR for Scanned Docs',    desc: 'EasyOCR + Tesseract converts scanned FIRs, handwritten notes, and court stamps into fully processable text.' },
  { icon: '🎙️', title: 'Voice Input',             desc: 'Dictate case details directly. Google Speech-to-Text converts spoken input into structured legal context instantly.' },
  { icon: '📝', title: 'Auto Draft Generation',   desc: 'Professional bail applications, case summaries, and legal briefs generated in proper Pakistani court format.' },
  { icon: '⚖️', title: 'PPC / CrPC Matching',     desc: 'Real-time cross-referencing against Pakistan Penal Code and Code of Criminal Procedure with full section descriptions.' },
];

const STATS = [
  { value: '85%+', label: 'Extraction Accuracy' },
  { value: '80%+', label: 'Retrieval Precision' },
  { value: '10×',  label: 'Faster Drafting' },
];

/* ── Presentational helpers (UI only, no logic) ── */
const PrimaryButton = ({ children, onClick }) => (
  <button
    onClick={onClick}
    className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-5 py-3 text-sm font-medium text-white shadow-md transition-all duration-200 hover:bg-green-700 hover:-translate-y-0.5 hover:shadow-lg active:scale-[0.98]"
  >
    {children}
  </button>
);

const SecondaryButton = ({ children, onClick }) => (
  <button
    onClick={onClick}
    className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-5 py-3 text-sm font-medium text-slate-700 shadow-sm transition-all duration-200 hover:border-slate-300 hover:bg-slate-50 hover:-translate-y-0.5"
  >
    {children}
  </button>
);

const Eyebrow = ({ children }) => (
  <p className="text-sm font-medium text-green-600 mb-3">{children}</p>
);

const Pill = ({ children }) => (
  <span className="inline-flex items-center rounded-lg border border-green-100 bg-green-50 px-2.5 py-1 font-mono text-[11px] font-medium text-green-700">
    {children}
  </span>
);

export default function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-white text-slate-800 antialiased">

      {/* ══ HERO ══ */}
      <section className="relative overflow-hidden border-b border-slate-200">
        {/* faint grid */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage: 'linear-gradient(#e2e8f0 1px, transparent 1px), linear-gradient(90deg, #e2e8f0 1px, transparent 1px)',
            backgroundSize: '56px 56px',
            maskImage: 'radial-gradient(ellipse 70% 60% at 50% 0%, black, transparent 75%)',
            WebkitMaskImage: 'radial-gradient(ellipse 70% 60% at 50% 0%, black, transparent 75%)',
            opacity: 0.6,
          }}
        />

        <div className="relative max-w-6xl mx-auto px-6 sm:px-10 pt-24 pb-24 grid lg:grid-cols-[1.05fr_.95fr] gap-16 items-center">

          {/* ── Left copy ── */}
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 shadow-sm mb-8">
              <span className="w-1.5 h-1.5 rounded-full bg-green-600 animate-pulse" />
              AI-Powered · RAG · NLP · OCR
            </span>

            <h1 className="text-[clamp(40px,5vw,64px)] font-semibold leading-[1.05] tracking-tight text-slate-900 mb-6">
              Pakistan's First
              <span className="block text-green-600">Intelligent Legal Agent</span>
            </h1>

            <p className="text-[17px] leading-relaxed text-slate-500 max-w-lg mb-10">
              Automate legal research, extract critical facts from FIRs, match applicable PPC/CrPC
              statutes, retrieve precedents, and generate professional case files —{' '}
              <span className="text-slate-800 font-medium">all in one platform.</span>
            </p>

            <div className="flex flex-wrap gap-3 mb-14">
              <PrimaryButton onClick={() => navigate('/dashboard')}>Open Dashboard →</PrimaryButton>
              <SecondaryButton onClick={() => navigate('/signup')}>Get Started Free</SecondaryButton>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-3 gap-6 pt-8 border-t border-slate-200">
              {STATS.map(s => (
                <div key={s.label}>
                  <div className="text-3xl font-semibold tracking-tight text-slate-900">{s.value}</div>
                  <div className="mt-1 text-xs text-slate-500">{s.label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* ── Right – product preview (bento) ── */}
          <div className="relative">
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xl shadow-slate-200/60">
              <div className="flex items-center justify-between mb-5">
                <span className="text-sm font-medium text-slate-900">Live analysis</span>
                <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-100 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Active
                </span>
              </div>

              {/* Document rows */}
              <div className="flex flex-col gap-2.5">
                {[
                  { icon: '📄', name: 'FIR_0234_Lahore.pdf',  meta: 'Criminal · 3 pages',   status: 'Analysed' },
                  { icon: '🖼️', name: 'WitnessStatement.jpg', meta: 'OCR complete · 1.2MB', status: 'OCR Done' },
                ].map(doc => (
                  <div
                    key={doc.name}
                    className="flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50/60 p-3 transition-all duration-200 hover:border-slate-300 hover:bg-white hover:shadow-sm"
                  >
                    <div className="w-10 h-10 flex-shrink-0 rounded-lg border border-slate-200 bg-white flex items-center justify-center text-lg">
                      {doc.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-900 truncate">{doc.name}</p>
                      <p className="mt-0.5 text-[11px] text-slate-500">{doc.meta}</p>
                    </div>
                    <span className="flex-shrink-0 rounded-md border border-green-100 bg-green-50 px-2 py-0.5 text-[11px] font-medium text-green-700">
                      {doc.status}
                    </span>
                  </div>
                ))}
              </div>

              {/* Chat preview */}
              <div className="mt-4 rounded-xl border border-slate-200 p-4">
                <div className="flex gap-3">
                  <div className="w-7 h-7 flex-shrink-0 rounded-lg bg-green-600 text-white flex items-center justify-center text-[10px] font-semibold">
                    AI
                  </div>
                  <div className="text-[13px] leading-relaxed text-slate-600">
                    Identified <span className="font-semibold text-slate-900">§302 PPC</span> (Qatl-e-Amd)
                    + <span className="font-semibold text-slate-900">§34 PPC</span>.
                    Found <span className="font-semibold text-slate-900">3 LHC precedents</span>.
                  </div>
                </div>
                <div className="flex gap-1.5 pl-10 mt-3">
                  {[0, 1, 2].map(i => (
                    <span key={i} className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce"
                          style={{ animationDelay: `${i * .2}s` }} />
                  ))}
                </div>
              </div>

              {/* Statute pills */}
              <div className="flex flex-wrap gap-2 mt-4">
                {['§302 PPC', '§34 PPC', '§497 CrPC'].map(s => (
                  <Pill key={s}>{s}</Pill>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ══ FEATURES (bento grid) ══ */}
      <section className="bg-slate-50 border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-6 sm:px-10 py-24">
          <div className="max-w-xl mb-14">
            <Eyebrow>Core capabilities</Eyebrow>
            <h2 className="text-4xl font-semibold tracking-tight text-slate-900 mb-4">Everything you need</h2>
            <p className="text-base leading-relaxed text-slate-500">
              Built specifically for Pakistan's legal system — PPC, CrPC, and local precedents at your fingertips.
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {FEATURES.map((f, i) => (
              <div
                key={f.title}
                className={`group rounded-2xl border border-slate-200 bg-white p-7 shadow-sm transition-all duration-200 hover:-translate-y-1 hover:border-green-200 hover:shadow-md
                  ${i === 0 ? 'lg:col-span-2' : ''} ${i === 5 ? 'lg:col-span-2' : ''}`}
              >
                <div className="w-11 h-11 rounded-xl border border-green-100 bg-green-50 flex items-center justify-center text-xl mb-5 transition-transform duration-200 group-hover:scale-105">
                  {f.icon}
                </div>
                <h3 className="text-[16px] font-semibold tracking-tight text-slate-900 mb-2">{f.title}</h3>
                <p className="text-sm leading-relaxed text-slate-500 max-w-md">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ══ HOW IT WORKS ══ */}
      <section className="border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-6 sm:px-10 py-24">
          <div className="text-center mb-14">
            <Eyebrow>Workflow</Eyebrow>
            <h2 className="text-4xl font-semibold tracking-tight text-slate-900">Three steps to legal clarity</h2>
          </div>

          <div className="grid md:grid-cols-3 gap-4">
            {[
              { step: '01', icon: '📤', title: 'Upload Document', desc: 'Upload a FIR, scanned image, or dictate via voice.' },
              { step: '02', icon: '🔬', title: 'AI Analyses',     desc: 'NLP extracts entities, RAG retrieves precedents, statutes are matched.' },
              { step: '03', icon: '📋', title: 'Download Report', desc: 'Get a professional bail application, case summary, or brief.' },
            ].map(s => (
              <div key={s.step} className="group rounded-2xl border border-slate-200 bg-white p-7 shadow-sm transition-all duration-200 hover:shadow-md">
                <div className="flex items-center justify-between mb-8">
                  <span className="w-12 h-12 rounded-xl border border-slate-200 bg-slate-50 flex items-center justify-center text-2xl transition-transform duration-200 group-hover:-translate-y-0.5">
                    {s.icon}
                  </span>
                  <span className="font-mono text-xs font-medium text-slate-300 group-hover:text-green-600 transition-colors">{s.step}</span>
                </div>
                <h4 className="text-[16px] font-semibold tracking-tight text-slate-900 mb-2">{s.title}</h4>
                <p className="text-sm leading-relaxed text-slate-500">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ══ CTA ══ */}
      <section className="px-6 sm:px-10 py-24">
        <div className="max-w-5xl mx-auto rounded-3xl bg-green-600 px-8 py-16 text-center shadow-xl shadow-green-600/20">
          <h2 className="text-4xl font-semibold tracking-tight text-white mb-4">
            Ready to modernize legal work?
          </h2>
          <p className="text-base text-green-100 mb-10 max-w-xl mx-auto">
            Join legal professionals automating Pakistan's judicial system.
          </p>
          <div className="flex flex-wrap gap-3 justify-center">
            <button
              onClick={() => navigate('/signup')}
              className="rounded-xl bg-white px-5 py-3 text-sm font-medium text-green-700 shadow-md transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg"
            >
              Create Free Account
            </button>
            <button
              onClick={() => navigate('/dashboard')}
              className="rounded-xl border border-green-400 px-5 py-3 text-sm font-medium text-white transition-all duration-200 hover:bg-green-500 hover:-translate-y-0.5"
            >
              Explore Dashboard
            </button>
          </div>
        </div>
      </section>

    </div>
  );
}