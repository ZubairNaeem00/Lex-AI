import React, { useEffect } from 'react';

/* Small blocking yes/no dialog used for destructive actions (sign out, delete). */
export default function ConfirmDialog({
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  busy = false,
  danger = false,
  icon,
  onConfirm,
  onCancel,
}) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape' && !busy) onCancel();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={busy ? undefined : onCancel} />
      <div className="relative w-full max-w-sm rounded-2xl bg-white shadow-xl border border-slate-200 p-6 animate-fade-up">
        {icon && (
          <div className={`mb-3.5 w-10 h-10 rounded-xl flex items-center justify-center ${danger ? 'bg-rose-50 text-rose-600' : 'bg-green-50 text-green-600'}`}>
            {icon}
          </div>
        )}
        <h3 className="text-[16px] font-semibold text-slate-900 leading-snug">{title}</h3>
        {message && <p className="mt-1.5 text-[13px] leading-relaxed text-slate-500">{message}</p>}

        <div className="mt-5 flex gap-2.5">
          <button
            autoFocus
            onClick={onCancel}
            disabled={busy}
            className="flex-1 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[13px] font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-60"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className={`flex-1 rounded-xl px-3.5 py-2 text-[13px] font-medium text-white shadow-sm transition-colors disabled:opacity-60 ${danger ? 'bg-rose-600 hover:bg-rose-700' : 'bg-green-600 hover:bg-green-700'}`}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
