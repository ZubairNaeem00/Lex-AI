import React from 'react';
import { Bookmark, X } from 'lucide-react';
import { toggleSavedCase, useIsSaved } from '../../savedCases';
import { cleanCitation } from './CaseCard';

export default function CaseDetailModal({ item, onClose }) {
  const saved = useIsSaved(item.case_id);
  if (!item) return null;
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" role="dialog" aria-modal="true"
         aria-label={item.case_name}>
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative flex max-h-[85vh] w-full max-w-2xl flex-col rounded-2xl border border-slate-200 bg-white shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 p-5">
          <div className="min-w-0">
            <h3 className="text-[15px] font-semibold leading-snug text-slate-900">{item.case_name}</h3>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-500">{cleanCitation(item.citation)}</p>
            <p className="mt-1.5 text-[11px] text-slate-500">
              {Math.round((item.score || 0) * 100)}% match · matched in {item.matched_section} ·{' '}
              {item.chunk_count} indexed passage{item.chunk_count === 1 ? '' : 's'}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              onClick={() => toggleSavedCase(item)}
              aria-label={saved ? 'Remove from saved cases' : 'Save case'}
              aria-pressed={saved}
              title={saved ? 'Remove from saved cases' : 'Save case'}
              className={`rounded-lg p-1.5 transition-colors ${saved
                ? 'text-green-600 hover:bg-green-50'
                : 'text-slate-400 hover:bg-slate-100 hover:text-green-600'}`}
            >
              <Bookmark className={`h-4 w-4 ${saved ? 'fill-current' : ''}`} />
            </button>
            <button onClick={onClose} aria-label="Close"
                    className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5 scrollbar-light">
          <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Summary</h4>
          <p className="mb-5 whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700">
            {item.summary || 'No summary was provided in the source record.'}
          </p>
          <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Full description</h4>
          <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700">
            {item.description || 'No description was provided in the source record.'}
          </p>
        </div>
      </div>
    </div>
  );
}
