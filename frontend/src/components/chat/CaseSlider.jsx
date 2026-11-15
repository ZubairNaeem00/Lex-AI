import React, { useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Loader2, Scale } from 'lucide-react';
import { retrieveCases } from '../../api/client';
import CaseCard from './CaseCard';
import CaseDetailModal from './CaseDetailModal';

const K_OPTIONS = [3, 5, 10, 15, 20];

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
    const step = (card ? card.getBoundingClientRect().width : 360) + 12;
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
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xl shadow-slate-300/60 ring-1 ring-slate-900/5">
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
            <div key={item.case_id} className="w-[360px] max-w-full shrink-0 snap-start">
              <CaseCard item={item} rank={index + 1} onOpen={setSelected} />
            </div>
          ))}
        </div>
      )}

      {selected && <CaseDetailModal item={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}