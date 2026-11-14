import React, { useRef, useState } from 'react';

const Icon = ({ d, className = 'w-4 h-4' }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {[].concat(d).map((p, i) => <path key={i} d={p} />)}
  </svg>
);

const I = {
  upload: ['M12 16V4', 'M6 10l6-6 6 6', 'M4 20h16'],
  folder: 'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z',
  file: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6'],
  close: 'M18 6L6 18M6 6l12 12',
};

const ALLOWED = ['.pdf', '.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff'];

/* Upload a document and run the LlamaParse + Groq analysis.
   Calls onAnalyzed(result) with the /api/analyze response on success. */
export default function AnalyzeModal({ open, busy, onClose, onAnalyze }) {
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);

  if (!open) return null;

  const pick = (files) => {
    const next = files && files[0];
    if (!next) return;
    setFile(next);
  };

  const canSubmit = Boolean(file) && !busy;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 md:p-8">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={busy ? undefined : onClose} />
      <div className="relative w-full max-w-lg rounded-2xl bg-white shadow-xl border border-slate-200 p-6 md:p-7 animate-fade-up">
        <div className="flex items-start justify-between mb-1">
          <div>
            <h2 className="text-[17px] font-semibold tracking-tight text-slate-900">Document Analysis</h2>
            <p className="mt-1 text-[13px] text-slate-500 leading-relaxed">
              Upload an FIR, court order, or statement. LexAI extracts the text, analyzes it, and adds an
              editable report to this chat.
            </p>
          </div>
          <button
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:opacity-50"
          >
            <Icon d={I.close} className="w-4 h-4" />
          </button>
        </div>

        <div
          onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={e => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files); }}
          onClick={() => !busy && inputRef.current?.click()}
          className={`
            mt-5 rounded-2xl border-2 border-dashed p-8 text-center cursor-pointer bg-slate-50/60
            transition-all duration-200
            ${dragging
              ? 'border-green-500 bg-green-50/70 scale-[1.01]'
              : 'border-slate-200 hover:border-green-300 hover:bg-green-50/40'}
            ${busy ? 'pointer-events-none opacity-60' : ''}
          `}
        >
          <input ref={inputRef} type="file" className="absolute w-0 h-0 opacity-0" accept={ALLOWED.join(',')}
                 aria-label="Choose a document to analyse"
                 onChange={e => { pick(e.target.files); e.target.value = ''; }} />
          <div className="mx-auto mb-3 w-11 h-11 rounded-xl bg-green-50 border border-green-100 text-green-600 flex items-center justify-center">
            <Icon d={file ? I.file : I.folder} className="w-5 h-5" />
          </div>
          {file ? (
            <>
              <p className="text-sm font-medium text-slate-900 break-all">{file.name}</p>
              <p className="mt-1 text-xs text-slate-500">{Math.max(1, Math.round(file.size / 1024)).toLocaleString()} KB · click to replace</p>
            </>
          ) : (
            <>
              <p className="text-sm font-medium text-slate-800">Drop your document here</p>
              <p className="mt-1 text-xs text-slate-500">or click to browse · PDF, PNG, JPG, WEBP, TIFF · max 25 MB</p>
            </>
          )}
        </div>

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            disabled={busy}
            className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition-all duration-200 hover:border-slate-300 hover:bg-slate-50 disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            onClick={() => onAnalyze(file)}
            disabled={!canSubmit}
            className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? (
              <>
                <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                Analyzing…
              </>
            ) : (
              <>
                <Icon d={I.upload} className="w-4 h-4" />
                Start Analysis
              </>
            )}
          </button>
        </div>
        <p className="mt-3 text-center text-[11px] text-slate-400">
          Extraction uses LlamaParse (Urdu/English OCR); analysis may take up to a minute.
        </p>
      </div>
    </div>
  );
}
