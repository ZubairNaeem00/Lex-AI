import React, { useState } from 'react';
import { Scale, ArrowUpRight } from 'lucide-react';
import { cleanCitation } from './CaseCard';
import CaseDetailModal from './CaseDetailModal';

/* Chat-stream marker for a past judgement attached as reference precedent.
   It is explicitly not the current case; clicking opens the full case popup. */
export default function PrecedentCard({ precedent }) {
  const [open, setOpen] = useState(false);
  if (!precedent) return null;
  const summary = precedent.summary || precedent.description || '';

  return (
    <>
      <article className="w-full max-w-[85%] overflow-hidden rounded-2xl border border-green-200 bg-green-50/60 shadow-sm">
        <div className="flex items-start gap-3.5 px-5 py-4">
          <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-green-600 text-white">
            <Scale className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-semibold uppercase tracking-[1.5px] text-green-700">
              Precedent added · reference only
            </p>
            <h3 className="mt-0.5 break-words text-[14px] font-semibold leading-snug text-slate-900">
              {precedent.case_name || 'Past judgement'}
            </h3>
            {precedent.citation && (
              <p className="mt-0.5 text-[11.5px] leading-relaxed text-slate-500">{cleanCitation(precedent.citation)}</p>
            )}
            {summary && (
              <p className="mt-1.5 line-clamp-2 text-[12px] leading-relaxed text-slate-600">{summary}</p>
            )}
            <button
              onClick={() => setOpen(true)}
              className="mt-2.5 inline-flex items-center gap-1 rounded-lg border border-green-200 bg-white px-2.5 py-1.5 text-[12px] font-medium text-green-700 transition-colors hover:bg-green-50"
            >
              View case
              <ArrowUpRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </article>
      {open && <CaseDetailModal item={precedent} onClose={() => setOpen(false)} />}
    </>
  );
}