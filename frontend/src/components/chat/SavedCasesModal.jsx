import React, { useState } from 'react';
import { Bookmark, X } from 'lucide-react';
import { useSavedCases } from '../../savedCases';
import CaseCard from './CaseCard';
import CaseDetailModal from './CaseDetailModal';

export default function SavedCasesModal({ open, onClose }) {
  const saved = useSavedCases();
  const [selected, setSelected] = useState(null);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true"
         aria-label="Saved cases">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl border border-slate-200 bg-white shadow-xl">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 p-5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-green-100 bg-green-50 text-green-600">
              <Bookmark className="h-4 w-4 fill-current" />
            </span>
            <h3 className="text-[15px] font-semibold text-slate-900">Saved cases</h3>
            <span className="rounded-md bg-green-100 px-1.5 py-0.5 text-[11px] font-semibold text-green-700">{saved.length}</span>
          </div>
          <button onClick={onClose} aria-label="Close"
                  className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-5 scrollbar-light">
          {saved.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-6 py-12 text-center">
              <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl border border-green-100 bg-green-50 text-green-600">
                <Bookmark className="h-5 w-5" />
              </span>
              <p className="text-[14px] font-semibold text-slate-900">No saved cases yet</p>
              <p className="mt-1 max-w-xs text-[12px] leading-relaxed text-slate-500">
                Tap the bookmark icon on any case card to keep it here for quick reference.
              </p>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {saved.map((item) => (
                <CaseCard key={item.case_id} item={item} onOpen={setSelected} showMatch={false} />
              ))}
            </div>
          )}
        </div>
      </div>

      {selected && <CaseDetailModal item={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
