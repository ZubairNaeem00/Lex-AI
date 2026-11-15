import React from 'react';
import { Bookmark } from 'lucide-react';
import { toggleSavedCase, useIsSaved } from '../../savedCases';

const clamp = { display: '-webkit-box', WebkitLineClamp: 4, WebkitBoxOrient: 'vertical', overflow: 'hidden' };

/* The index records carry a scraped "Bookmark this Case" button label inside the
   citation; a real save icon replaces it, so strip that artifact from the text. */
export function cleanCitation(citation) {
  return String(citation || '').replace(/bookmark this case/gi, '').replace(/\s+/g, ' ').trim();
}

export default function CaseCard({ item, rank = null, showMatch = true, onOpen }) {
  const saved = useIsSaved(item.case_id);
  return (
    <div className="group flex h-full w-full flex-col rounded-xl border border-slate-200 bg-slate-50/60 p-4 transition-all duration-200 hover:border-green-300 hover:bg-green-50/40 hover:shadow-md">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {rank != null && (
            <span className="rounded-md bg-green-100 px-1.5 py-0.5 text-[10px] font-semibold text-green-700">#{rank}</span>
          )}
          {showMatch && (
            <span className="text-[10px] font-medium text-slate-500">{Math.round((item.score || 0) * 100)}% match</span>
          )}
        </div>
        <button
          onClick={() => toggleSavedCase(item)}
          aria-label={saved ? 'Remove from saved cases' : 'Save case'}
          aria-pressed={saved}
          title={saved ? 'Remove from saved cases' : 'Save case'}
          className={`rounded-lg p-1.5 transition-all duration-150 active:scale-90 ${saved
            ? 'text-green-600 hover:bg-green-100'
            : 'text-slate-400 hover:bg-slate-100 hover:text-green-600'}`}
        >
          <Bookmark className={`h-4 w-4 transition-all ${saved ? 'fill-current' : ''}`} />
        </button>
      </div>

      <button onClick={() => onOpen?.(item)} className="flex flex-1 flex-col text-left outline-none">
        <p className="mb-1.5 text-[13px] font-semibold leading-snug text-slate-900" style={clamp}>
          {item.case_name || 'Unnamed case'}
        </p>
        <p className="mb-2 text-[11px] leading-relaxed text-slate-500" style={{ ...clamp, WebkitLineClamp: 2 }}>
          {cleanCitation(item.citation)}
        </p>
        <p className="text-[12px] leading-relaxed text-slate-600" style={clamp}>
          {item.summary || item.description || 'No summary was provided in the source record.'}
        </p>
        <span className="mt-2.5 inline-block text-[11px] font-medium text-green-700 transition-colors group-hover:text-green-800">
          Read full case →
        </span>
      </button>
    </div>
  );
}
