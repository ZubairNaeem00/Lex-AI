import React from 'react';
import { Link } from 'react-router-dom';
import { Scale, FileText, MessageSquare, Search, FileDown, ShieldCheck, GraduationCap, Landmark } from 'lucide-react';

const FEATURES = [
  {
    icon: FileText,
    title: 'Document Analysis',
    body: 'Upload an FIR, court order or witness statement and LexAI extracts the text, identifies the parties, statutes and unclear details, and returns a structured, editable case report.',
  },
  {
    icon: MessageSquare,
    title: 'AI Co-Counsel',
    body: 'Ask questions in plain language and discuss any analysed document in a dedicated conversation. Answers are grounded in Pakistani statutes and the case context you provide.',
  },
  {
    icon: Search,
    title: 'Case Retrieval',
    body: 'Search a local index of 43,978 Pakistani judgments to surface similar precedents, with the matching passages and citations ready to open and read.',
  },
  {
    icon: FileDown,
    title: 'Word Reports',
    body: 'Turn an analysis into a formatted Word document you can download, refine and file — bail applications, case summaries and legal briefs.',
  },
];

const STEPS = [
  { n: '01', title: 'Upload', body: 'Drop a PDF or scanned image (up to 10 MB). The file is checked the moment you add it.' },
  { n: '02', title: 'Analyse', body: 'The document-analysis module extracts text and builds a structured report with statutes and fields.' },
  { n: '03', title: 'Review & discuss', body: 'Correct any field, open the report in a new AI conversation, and pull similar precedents.' },
  { n: '04', title: 'Generate', body: 'Export the finished analysis as a Word document, ready to download and edit.' },
];

const FeatureCard = ({ icon: Icon, title, body }) => (
  <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5">
    <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-green-50 border border-green-100 text-green-600">
      <Icon className="h-5 w-5" />
    </div>
    <h3 className="text-[15px] font-semibold text-slate-900">{title}</h3>
    <p className="mt-2 text-sm leading-6 text-slate-600">{body}</p>
  </div>
);

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-page text-slate-800 antialiased">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-6 py-12 sm:px-8">
          <Link to="/" className="text-sm font-medium text-green-700 hover:text-green-800">
            ← Back to LexAI
          </Link>
          <p className="mt-8 inline-flex items-center gap-2 text-sm font-medium text-green-700">
            <Scale className="h-4 w-4" /> About LexAI
          </p>
          <h1 className="mt-2 text-4xl font-semibold tracking-tight text-slate-900">
            Pakistan Legal Intelligence
          </h1>
          <p className="mt-5 max-w-3xl text-sm leading-7 text-slate-600">
            LexAI is a legal co-counsel for Pakistani law. It reads case documents, answers
            research questions against statutes and precedent, and drafts the paperwork that
            follows — so advocates and students spend less time on routine reading and more
            time on argument.
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-10 sm:px-8 sm:py-14">
        <section>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">What LexAI does</h2>
          <p className="mt-2 max-w-3xl text-sm leading-7 text-slate-600">
            Four connected tools cover the life of a case file, from the first scan to a
            filed document.
          </p>
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {FEATURES.map((f) => <FeatureCard key={f.title} {...f} />)}
          </div>
        </section>

        <section className="mt-14">
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">How a file moves through LexAI</h2>
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s) => (
              <div key={s.n} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <span className="text-xs font-semibold tracking-widest text-green-600">{s.n}</span>
                <h3 className="mt-2 text-[15px] font-semibold text-slate-900">{s.title}</h3>
                <p className="mt-1.5 text-[13px] leading-6 text-slate-600">{s.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-14 grid gap-4 lg:grid-cols-2">
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="mb-3 flex items-center gap-2.5 text-slate-900">
              <Landmark className="h-5 w-5 text-green-600" />
              <h2 className="text-[15px] font-semibold">Grounded in Pakistani law</h2>
            </div>
            <p className="text-sm leading-7 text-slate-600">
              The assistant works with the Pakistan Penal Code, the Code of Criminal Procedure,
              the Qanun-e-Shahadat and related statutes, and retrieves from a local index of
              43,978 judgments from the Lahore High Court and Supreme Court. Citations are
              surfaced so you can verify every authority yourself.
            </p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="mb-3 flex items-center gap-2.5 text-slate-900">
              <GraduationCap className="h-5 w-5 text-green-600" />
              <h2 className="text-[15px] font-semibold">A final-year project</h2>
            </div>
            <p className="text-sm leading-7 text-slate-600">
              LexAI is built as a LegalLens final-year project: a full-stack application with a
              FastAPI backend, a React frontend, MongoDB persistence and a retrieval-augmented
              legal agent. It demonstrates how modern language models can assist — not replace —
              careful legal work.
            </p>
          </div>
        </section>

        <section className="mt-10 rounded-2xl border border-amber-200 bg-amber-50 p-6">
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
            <div>
              <h2 className="text-[15px] font-semibold text-amber-900">Assistive tool, not legal advice</h2>
              <p className="mt-2 text-sm leading-7 text-amber-900">
                LexAI helps you read, research and draft, but it is not a lawyer and its output
                may contain errors. Always review generated material and verify citations
                against the primary sources before relying on it. Only upload documents you
                are authorized to share.
              </p>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-6 py-6 text-sm text-slate-500 sm:px-8">
          <span>LexAI · Pakistan Legal Intelligence</span>
          <div className="flex gap-5">
            <Link to="/privacy-policy" className="font-medium text-green-700 hover:text-green-800">Privacy</Link>
            <Link to="/" className="font-medium text-green-700 hover:text-green-800">Home</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}