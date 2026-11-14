import React, { useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Loader2, Scale, X } from 'lucide-react';
import { retrieveCases } from '../../api/client';

const K_OPTIONS = [3, 5, 10, 15, 20];
const clamp = { display: '-webkit-box', WebkitLineClamp: 4, WebkitBoxOrient: 'vertical', overflow: 'hidden' };

/* Horizontal slider of similar cases. Every value shown comes straight from the
   FAISS index records — nothing here is generated or rewritten. */
export default function CaseSlider({ retrieval }) {
  const [data, setData] = useState(retrieval);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const track = useRef(null);

  const cases = data?.cases || [];
  const scroll = (direction) => {
    const card = track.current?.firstElementChild;
    const step = (card ? card.getBoundingClientRect().width : 290) + 12;
    track.current?.scrollBy({ left: direction * step, behavior: 'smooth' });
  };

  const changeK = async (k) => {
    setBusy(true);
    setError(null);
    try {
      setData(await retrieveCases(data.query, k));
      track.current?.scrollTo({ left: 0 });
    } catch (e) {
      setError(e.message || 'Could not load cases. Please retry.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Scale className="h-4 w-4 shrink-0 text-green-600" />
          <p className="truncate text-[13px] font-semibold text-slate-900">
            Similar cases · {data?.count ?? cases.length}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500">
            Cases
            <select
              value={data?.k || 5}
              onChange={(e) => changeK(Number(e.target.value))}
              disabled={busy}
              className="rounded-lg border border-slate-200 bg-white px-1.5 py-1 text-[11px] font-medium text-slate-700 outline-none hover:border-green-300 disabled:opacity-60"
            >
              {K_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
          </label>
          <button onClick={() => scroll(-1)} aria-label="Previous cases"
                  className="rounded-lg border border-slate-200 p-1.5 text-slate-500 transition-colors hover:border-green-300 hover:text-green-700">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button onClick={() => scroll(1)} aria-label="Next cases"
                  className="rounded-lg border border-slate-200 p-1.5 text-slate-500 transition-colors hover:border-green-300 hover:text-green-700">
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      <p className="mb-3 text-[11px] leading-relaxed text-slate-500">
        Matched on “{data?.query}”
        {data?.index?.total_cases ? ` · ${data.index.total_cases.toLocaleString()} judgments searched` : ''}
      </p>

      {error && <p className="mb-3 rounded-xl bg-rose-50 px-3 py-2 text-[12px] text-rose-700">{error}</p>}
      {busy && (
        <p className="mb-3 flex items-center gap-2 text-[12px] text-slate-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Searching the case index…
        </p>
      )}

      {cases.length === 0 && !busy ? (
        <p className="rounded-xl bg-slate-50 px-3 py-4 text-[13px] text-slate-500">
          No matching cases were found. Try describing the legal issue or the facts in different words.
        </p>
      ) : (
        <div ref={track} className="flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2 scrollbar-light">
          {cases.map((item, index) => (
            <button
              key={item.case_id}
              onClick={() => setSelected(item)}
              className="w-[290px] max-w-full shrink-0 snap-start rounded-xl border border-slate-200 bg-slate-50/60 p-3.5 text-left transition-all duration-200 hover:border-green-300 hover:bg-green-50/40"
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="rounded-md bg-green-100 px-1.5 py-0.5 text-[10px] font-semibold text-green-700">
                  #{index + 1}
                </span>
                <span className="text-[10px] font-medium text-slate-500">
                  {Math.round((item.score || 0) * 100)}% match
                </span>
              </div>
              <p className="mb-1.5 text-[13px] font-semibold leading-snug text-slate-900" style={clamp}>
                {item.case_name || 'Unnamed case'}
              </p>
              <p className="mb-2 text-[11px] leading-relaxed text-slate-500" style={{ ...clamp, WebkitLineClamp: 2 }}>
                {item.citation}
              </p>
              <p className="text-[12px] leading-relaxed text-slate-600" style={clamp}>
                {item.summary || item.description || 'No summary was provided in the source record.'}
              </p>
              <span className="mt-2.5 inline-block text-[11px] font-medium text-green-700">
                Read full case →
              </span>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true"
             aria-label={selected.case_name}>
          <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={() => setSelected(null)} />
          <div className="relative flex max-h-[85vh] w-full max-w-2xl flex-col rounded-2xl border border-slate-200 bg-white shadow-xl">
            <div className="flex items-start justify-between gap-3 border-b border-slate-200 p-5">
              <div className="min-w-0">
                <h3 className="text-[15px] font-semibold leading-snug text-slate-900">{selected.case_name}</h3>
                <p className="mt-1 text-[12px] leading-relaxed text-slate-500">{selected.citation}</p>
                <p className="mt-1.5 text-[11px] text-slate-500">
                  {Math.round((selected.score || 0) * 100)}% match · matched in {selected.matched_section} ·
                  {' '}{selected.chunk_count} indexed passage{selected.chunk_count === 1 ? '' : 's'}
                </p>
              </div>
              <button onClick={() => setSelected(null)} aria-label="Close"
                      className="shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-5 scrollbar-light">
              <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Summary</h4>
              <p className="mb-5 whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700">
                {selected.summary || 'No summary was provided in the source record.'}
              </p>
              <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Full description
              </h4>
              <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700">
                {selected.description || 'No description was provided in the source record.'}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}