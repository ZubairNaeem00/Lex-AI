import React, { useState } from 'react';
import { downloadGeneratedDocument } from '../../api/client';

const Icon = ({ d, className = 'w-4 h-4' }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {[].concat(d).map((p, i) => <path key={i} d={p} />)}
  </svg>
);

const I = {
  download: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'M7 10l5 5 5-5', 'M12 15V3'],
  edit: ['M16 3l5 5L9 20l-6 1 1-6z'],
  check: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M8 12l3 3 5-6'],
  spinner: 'M20 12a8 8 0 1 1-8-8',
};

const STATUS_META = {
  collecting:  { label: 'Collecting details', chip: 'text-amber-700 bg-amber-50 border-amber-200' },
  review:      { label: 'Ready for review',   chip: 'text-green-700 bg-green-50 border-green-200' },
  generating:  { label: 'Generating',         chip: 'text-green-700 bg-green-50 border-green-200' },
  completed:   { label: 'Ready to download',  chip: 'text-green-700 bg-green-50 border-green-200' },
  error:       { label: 'Needs attention',    chip: 'text-rose-700 bg-rose-50 border-rose-200' },
  cancelled:   { label: 'Cancelled',          chip: 'text-slate-500 bg-slate-100 border-slate-200' },
};

/* Multi-turn document-generation card rendered inside the chat stream.
   Field values are never shown here; they are only visible in the review modal. */
export default function GenerationCard({ caseId, generation, onEdit, onCancel, onRetry, onView }) {
  const status = generation.status || 'collecting';
  const meta = STATUS_META[status] || STATUS_META.collecting;
  const result = generation.result || {};
  const progress = generation.progress || { completed: 0, total: 0 };
  const pct = progress.total ? Math.round((progress.completed / progress.total) * 100) : 0;
  const missing = generation.missing_fields || [];
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const openable = status === 'completed' && !!result.filename && !!onView;

  const parseDownload = () => {
    const match = /\/sessions\/([^/]+)\/download\/(.+)$/.exec(result.download_url || '');
    if (!match) return null;
    return { case: decodeURIComponent(match[1]), filename: decodeURIComponent(match[2]) };
  };

  // The download endpoint is account-scoped, so a plain <a href> navigation would 401.
  const handleDownload = async () => {
    const target = parseDownload() || { case: caseId, filename: result.filename };
    if (!target.case || !target.filename) {
      setSaveError('This draft has no downloadable file yet.');
      return;
    }
    setSaving(true);
    setSaveError('');
    try {
      const blob = await downloadGeneratedDocument(target.case, target.filename);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = target.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setSaveError(err.message || 'Could not download the document.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <article className="w-full max-w-[85%] rounded-2xl border border-green-200/70 bg-white shadow-sm overflow-hidden">
      <header className="flex items-start gap-3.5 px-5 pt-4 pb-3.5 bg-gradient-to-b from-green-50/70 to-white border-b border-slate-100">
        <div className="w-9 h-9 rounded-xl bg-green-600 text-white flex items-center justify-center flex-shrink-0 text-sm font-serif">
          §
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-[1.5px] text-green-700">Document draft</p>
          <h3 className="mt-0.5 text-[15px] font-semibold text-slate-900 leading-snug">
            {generation.template_label || 'Legal document'}{status === 'completed' ? ' — ready' : ''}
          </h3>
          <p className="mt-0.5 text-[11px] text-slate-500 break-words line-clamp-2">{generation.user_request || ''}</p>
        </div>
        <span className={`inline-flex items-center text-[10px] font-semibold uppercase tracking-wide rounded-full border px-2 py-0.5 flex-shrink-0 ${meta.chip}`}>
          {meta.label}
        </span>
      </header>

      <div className="px-5 py-4">
        {status !== 'completed' && progress.total > 0 && (
          <div className="flex items-center gap-3 mb-4">
            <div className="flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
              <div className="h-full rounded-full bg-gradient-to-r from-green-500 to-green-600 transition-all duration-300" style={{ width: `${pct}%` }} />
            </div>
            <span className="text-[10px] font-semibold text-slate-400 tabular-nums">{progress.completed} / {progress.total} details</span>
          </div>
        )}

        {status === 'collecting' && (
          <>
            {generation.question && (
              <div className="relative rounded-xl border border-green-100 bg-green-50/60 pl-4 pr-3 py-3 mb-3">
                <span className="absolute left-0 top-2.5 bottom-2.5 w-[3px] rounded-full bg-green-600" />
                <p className="text-[10px] font-semibold uppercase tracking-[1.5px] text-green-700 mb-1">Next required detail</p>
                <p className="text-[13.5px] font-medium text-slate-900 leading-relaxed">{generation.question}</p>
                <p className="mt-1.5 text-[11px] text-slate-500">Reply below, or use Edit details to fill several fields at once.</p>
              </div>
            )}
            {missing.length > 0 && (
              <details className="group rounded-xl border border-slate-100 bg-slate-50/60 px-3.5 py-2.5">
                <summary className="cursor-pointer text-[12px] font-medium text-slate-600 select-none">
                  Still required · {missing.length}
                </summary>
                <ul className="mt-2 space-y-1">
                  {missing.map(f => (
                    <li key={f.name} className="text-[12px] text-slate-600">
                      <span className="font-medium text-slate-800">{f.label}</span>
                      {f.description ? <span className="text-slate-400"> — {f.description}</span> : null}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <CardActions>
              {generation.can_edit !== false && <ActionButton onClick={() => onEdit(generation.id)} icon={I.edit}>Edit details</ActionButton>}
              <span className="flex-1" />
              {generation.can_cancel && <ActionButton onClick={onCancel} danger>Cancel draft</ActionButton>}
            </CardActions>
          </>
        )}

        {status === 'review' && (
          <>
            <div className="relative rounded-xl border border-green-100 bg-green-50/60 pl-4 pr-3 py-3 mb-1">
              <span className="absolute left-0 top-2.5 bottom-2.5 w-[3px] rounded-full bg-green-600" />
              <p className="text-[10px] font-semibold uppercase tracking-[1.5px] text-green-700 mb-1">Details ready</p>
              <p className="text-[13.5px] font-medium text-slate-900 leading-relaxed">All required details are collected. Review or edit them before the document is generated.</p>
              <p className="mt-1.5 text-[11px] text-slate-500">Your details are stored in this case but are not shown on this card.</p>
            </div>
            <CardActions>
              <button
                onClick={() => onEdit(generation.id)}
                className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-3.5 py-2 text-[13px] font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98]"
              >
                Review &amp; generate
              </button>
              <span className="flex-1" />
              {generation.can_cancel && <ActionButton onClick={onCancel} danger>Cancel draft</ActionButton>}
            </CardActions>
          </>
        )}

        {status === 'generating' && (
          <>
            <div className="flex items-center gap-2.5 py-1 text-[13px] text-slate-600">
              <span className="w-4 h-4 border-2 border-green-600/25 border-t-green-600 rounded-full animate-spin" />
              Preparing the document from the details collected…
            </div>
            {generation.can_cancel && (
              <CardActions>
                <span className="flex-1" />
                <ActionButton onClick={onCancel} danger>Cancel draft</ActionButton>
              </CardActions>
            )}
          </>
        )}

        {status === 'completed' && (
          <>
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-green-200 bg-green-50/70 p-1.5">
              <button
                type="button"
                onClick={openable ? () => onView({ generationId: generation.id, templateLabel: generation.template_label, filename: result.filename }) : undefined}
                disabled={!openable}
                title={openable ? 'Open this draft in the side editor' : 'Download this draft to view it'}
                className={`flex min-w-0 flex-1 items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-all duration-200
                  ${openable ? 'hover:bg-green-100/70' : 'cursor-default'}`}
              >
                <span className="w-8 h-8 rounded-full bg-green-600 text-white flex items-center justify-center flex-shrink-0">
                  <Icon d={I.check} className="w-4 h-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-semibold text-green-900">
                    {openable ? 'Document generated — click to view & edit' : 'Document generated'}
                  </p>
                  <p className="text-[11px] text-slate-500 break-all">{result.filename || 'document.docx'}</p>
                </div>
              </button>
              {result.download_url && (
                <button
                  onClick={handleDownload}
                  disabled={saving}
                  className="mr-1.5 inline-flex items-center gap-2 rounded-xl bg-green-600 px-3.5 py-2 text-[13px] font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98] disabled:opacity-60"
                >
                  <Icon d={I.download} className="w-4 h-4" />
                  {saving ? 'Preparing…' : 'Download DOCX'}
                </button>
              )}
            </div>
            {saveError && (
              <p className="mt-2 text-[12px] font-medium text-rose-600">{saveError}</p>
            )}
            <CardActions>
              {openable && <ActionButton onClick={() => onView({ generationId: generation.id, templateLabel: generation.template_label, filename: result.filename })} icon={I.edit}>View &amp; edit</ActionButton>}
              {generation.can_edit !== false && <ActionButton onClick={() => onEdit(generation.id)} icon={I.edit}>Edit &amp; regenerate</ActionButton>}
            </CardActions>
            <p className="mt-3 text-[11px] leading-relaxed text-slate-400">
              Details stay in this case but are not shown here. To draft for a different person, send a new request —
              answers from this draft are not reused automatically. Review the DOCX against the source documents before filing.
            </p>
          </>
        )}

        {status === 'error' && (
          <>
            <p className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-[13px] leading-relaxed text-rose-700">
              {generation.error || 'The document could not be generated. Your answers are saved.'}
            </p>
            <CardActions>
              {generation.can_edit !== false && <ActionButton onClick={() => onEdit(generation.id)} icon={I.edit}>Edit details</ActionButton>}
              <span className="flex-1" />
              {generation.can_retry && (
                <button
                  onClick={onRetry}
                  className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-3.5 py-2 text-[13px] font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700"
                >
                  Retry draft
                </button>
              )}
              {generation.can_cancel && <ActionButton onClick={onCancel} danger>Cancel draft</ActionButton>}
            </CardActions>
          </>
        )}

        {status === 'cancelled' && (
          <>
            <p className="text-[13px] text-slate-500">This draft was cancelled. Details already provided remain stored in the case.</p>
            {generation.can_edit !== false && (
              <CardActions>
                <ActionButton onClick={() => onEdit(generation.id)} icon={I.edit}>Edit details</ActionButton>
              </CardActions>
            )}
          </>
        )}
      </div>
    </article>
  );
}

const CardActions = ({ children }) => (
  <div className="flex flex-wrap items-center gap-2 mt-4 border-t border-slate-100 pt-3.5">{children}</div>
);

const ActionButton = ({ children, onClick, icon, danger, primary }) => (
  <button
    onClick={onClick}
    className={`inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-[13px] font-medium transition-all duration-200 active:scale-[0.98]
      ${primary
        ? 'bg-green-600 text-white shadow-sm hover:bg-green-700'
        : danger
          ? 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
          : 'border border-slate-200 bg-white text-slate-700 hover:border-green-300 hover:text-green-700 hover:bg-green-50'}`}
  >
    {icon && <Icon d={icon} className="w-3.5 h-3.5" />}
    {children}
  </button>
);
