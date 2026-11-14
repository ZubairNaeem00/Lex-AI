import React, { useEffect, useMemo, useState } from 'react';
import { getGenerationFields, updateGenerationFields } from '../../api/client';

/* Review/edit modal for a document generation.
   This is the only place collected field values are displayed. */
export default function ReviewFieldsModal({ caseId, generationId, onClose, onSaved }) {
  const [payload, setPayload] = useState(null);
  const [draft, setDraft] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getGenerationFields(caseId, generationId)
      .then(data => {
        if (cancelled) return;
        setPayload(data);
        const values = {};
        (data.fields || []).forEach(f => { values[f.name] = f.value || ''; });
        setDraft(values);
        setLoading(false);
      })
      .catch(e => {
        if (cancelled) return;
        setError(e.message || 'Could not load the draft details.');
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [caseId, generationId]);

  const fields = payload ? payload.fields || [] : [];
  const requiredCount = useMemo(() => fields.filter(f => f.required).length, [fields]);

  const setValue = (name, value) => setDraft(d => ({ ...d, [name]: value }));

  const clearAll = () => {
    if (!window.confirm('Clear every detail shown? Nothing changes until you save.')) return;
    const blank = {};
    fields.forEach(f => { blank[f.name] = ''; });
    setDraft(blank);
    setError('');
  };

  const save = async (generate) => {
    setSaving(true);
    setError('');
    try {
      const values = {};
      Object.entries(draft).forEach(([name, value]) => { values[name] = String(value || '').trim(); });
      const result = await updateGenerationFields(caseId, generationId, values, generate);
      const generation = result.generation || {};
      if (generate && generation.status === 'collecting') {
        const missing = (generation.missing_fields || []).map(f => f.label).join(', ');
        setError(`Please fill the remaining required details: ${missing}.`);
        if (onSaved) onSaved(result);
        return;
      }
      if (onSaved) onSaved(result);
      onClose();
    } catch (e) {
      setError(e.message || 'The draft details could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 md:p-8">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <div className="relative w-full max-w-2xl max-h-[90vh] flex flex-col rounded-2xl bg-white shadow-xl border border-slate-200 p-6 md:p-7 animate-fade-up">
        <div className="flex items-start justify-between mb-1">
          <div>
            <h2 className="text-[17px] font-semibold tracking-tight text-slate-900">
              Review {(payload && payload.template_label) || 'document'} details
            </h2>
            <p className="mt-1 text-[13px] text-slate-500">
              {requiredCount} required detail{requiredCount === 1 ? '' : 's'} · stored in this case only · not shown on the draft card
            </p>
          </div>
          <button
            onClick={onClose}
            disabled={saving}
            aria-label="Close"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:opacity-50"
          >
            <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M18 6L6 18M6 6l12 12" /></svg>
          </button>
        </div>

        {loading ? (
          <div className="flex items-center gap-3 py-14 justify-center text-[13px] text-slate-500">
            <span className="w-4 h-4 border-2 border-green-600/25 border-t-green-600 rounded-full animate-spin" />
            Loading draft details…
          </div>
        ) : (
          <>
            <div className="mt-4 flex-1 overflow-y-auto pr-1 flex flex-col gap-4">
              {fields.map(field => (
                <div key={field.name} className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                      {field.label || field.name}{field.required ? ' *' : ''}
                    </label>
                    {field.source && (
                      <span className={`text-[10px] font-semibold rounded-full border px-2 py-0.5
                        ${field.source === 'you'
                          ? 'text-amber-700 bg-amber-50 border-amber-200'
                          : 'text-slate-500 bg-slate-100 border-slate-200'}`}>
                        {field.source === 'you' ? 'your value' : field.source === 'case documents' ? 'from case documents' : 'from request'}
                      </span>
                    )}
                  </div>
                  <textarea
                    rows={field.name === 'applicants_address' ? 3 : 2}
                    value={draft[field.name] || ''}
                    maxLength={800}
                    onChange={e => setValue(field.name, e.target.value)}
                    placeholder={field.required ? 'Required' : field.default ? `Default: ${field.default}` : 'Optional'}
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-[13px] leading-relaxed text-slate-800 outline-none resize-y transition-colors focus:border-green-500 focus:ring-2 focus:ring-green-500/20"
                  />
                  {field.description && <p className="text-[11px] text-slate-400 border-l-2 border-slate-100 pl-2">{field.description}</p>}
                </div>
              ))}

              {error && (
                <p className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-[13px] leading-relaxed text-rose-700">{error}</p>
              )}
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
              <button
                onClick={clearAll}
                disabled={saving}
                className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[13px] font-medium text-slate-600 transition-all duration-200 hover:bg-slate-50 disabled:opacity-60"
              >
                Clear all
              </button>
              <span className="flex-1" />
              <button
                onClick={onClose}
                disabled={saving}
                className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[13px] font-medium text-slate-700 transition-all duration-200 hover:bg-slate-50 disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                onClick={() => save(false)}
                disabled={saving}
                className="rounded-xl border border-green-200 bg-green-50 px-3.5 py-2 text-[13px] font-medium text-green-700 transition-all duration-200 hover:bg-green-100 disabled:opacity-60"
              >
                {saving ? 'Saving…' : 'Save details'}
              </button>
              <button
                onClick={() => save(true)}
                disabled={saving}
                className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-4 py-2 text-[13px] font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98] disabled:opacity-50"
              >
                {saving && <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />}
                {saving ? 'Generating…' : 'Save & generate'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
