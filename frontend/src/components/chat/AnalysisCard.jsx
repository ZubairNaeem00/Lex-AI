import React, { useEffect, useMemo, useState } from 'react';
import { getDocumentText, saveReportEdits } from '../../api/client';

const Icon = ({ d, className = 'w-4 h-4' }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {[].concat(d).map((p, i) => <path key={i} d={p} />)}
  </svg>
);

const I = {
  file: ['M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z', 'M14 3v6h6', 'M8 13h8', 'M8 17h5'],
  edit: ['M16 3l5 5L9 20l-6 1 1-6z'],
  check: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M8 12l3 3 5-6'],
  spinner: 'M20 12a8 8 0 1 1-8-8',
  warn: ['M12 9v4', 'M12 17h.01', 'M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'],
};

/* Editable analysis report card rendered inside the chat stream.
   `document` is the snapshot document object: {document_id, filename, report, edits, ...}.
   `onSaved(updatedDoc)` lets the parent refresh its documents map. */
export default function AnalysisCard({ caseId, document, onSaved }) {
  const report = document.report || {};
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [draft, setDraft] = useState({});
  const [showSource, setShowSource] = useState(false);
  const [sourceText, setSourceText] = useState('');

  const sections = report.sections || [];
  const unclear = report.unclear_information || [];

  const fieldCount = useMemo(
    () => sections.reduce((n, s) => n + ((s.fields && s.fields.length) || 0), 0),
    [sections]
  );

  const startEdit = () => {
    const next = { title: report.title || '', document_type: report.document_type || '', summary: report.summary || '' };
    sections.forEach((section, si) => {
      (section.fields || []).forEach((field, fi) => {
        next[`sections.${si}.fields.${fi}.value`] = field.value || '';
      });
      if (section.table && section.table.rows) {
        section.table.rows.forEach((row, ri) => {
          row.forEach((cell, ci) => {
            next[`sections.${si}.table.rows.${ri}.${ci}`] = cell || '';
          });
        });
      }
    });
    setDraft(next);
    setEditing(true);
    setError('');
    setNotice('');
  };

  const setField = (path, value) => setDraft(d => ({ ...d, [path]: value }));

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      const edits = Object.entries(draft)
        .filter(([path, value]) => {
          const original = readOriginal(report, path);
          return String(original || '') !== String(value || '');
        })
        .map(([path, value]) => ({ path, value: String(value || '') }));
      if (!edits.length) {
        setEditing(false);
        setSaving(false);
        return;
      }
      const result = await saveReportEdits(caseId, document.document_id, edits);
      setEditing(false);
      setNotice(`${edits.length} correction${edits.length === 1 ? '' : 's'} saved — later answers and drafts will use it.`);
      if (onSaved) onSaved({ ...document, report: result.report, edits: result.edits });
    } catch (e) {
      setError(e.message || 'The report could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  const toggleSource = async () => {
    if (showSource) {
      setShowSource(false);
      return;
    }
    setShowSource(true);
    if (!sourceText) {
      try {
        const data = await getDocumentText(caseId, document.document_id);
        setSourceText(data.extracted_text || '');
      } catch (e) {
        setSourceText(`Could not load the extracted text: ${e.message}`);
      }
    }
  };

  return (
    <article className="w-full max-w-[85%] rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      {/* Header */}
      <header className="flex items-start gap-3.5 px-5 pt-4 pb-3.5 bg-gradient-to-b from-slate-50 to-white border-b border-slate-100">
        <div className="w-9 h-9 rounded-xl bg-green-600 text-white flex items-center justify-center flex-shrink-0">
          <Icon d={I.file} className="w-4 h-4" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-[1.5px] text-green-700">
            Document analysis · {report.document_type || 'Legal document'}
          </p>
          {editing ? (
            <input
              value={draft.title}
              onChange={e => setField('title', e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-[15px] font-semibold text-slate-900 outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20"
            />
          ) : (
            <h3 className="mt-0.5 text-[15px] font-semibold text-slate-900 leading-snug break-words">{report.title || 'Document analysis'}</h3>
          )}
          <p className="mt-0.5 text-[11px] text-slate-500 truncate">{document.filename}</p>
        </div>
        {report.has_corrections && (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5 flex-shrink-0">
            <Icon d={I.check} className="w-3 h-3" />
            Corrected
          </span>
        )}
      </header>

      {/* Body */}
      <div className="px-5 py-4">
        {(report.summary || editing) && (
          <div className="mb-4">
            <p className="text-[10px] font-semibold uppercase tracking-[1.5px] text-slate-400 mb-1.5">Summary</p>
            {editing ? (
              <textarea
                value={draft.summary}
                onChange={e => setField('summary', e.target.value)}
                rows={3}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-[13px] leading-relaxed text-slate-800 outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20 resize-y"
              />
            ) : (
              <p className="text-[13px] leading-relaxed text-slate-600">{report.summary}</p>
            )}
          </div>
        )}

        {sections.map((section, si) => (
          <section key={si} className="mt-4 first:mt-0">
            <div className="flex items-baseline justify-between gap-3 mb-2">
              <h4 className="text-[13px] font-semibold text-slate-900">{section.title}</h4>
              {section.summary && !editing && (
                <span className="text-[11px] text-slate-400 line-clamp-1">{section.summary}</span>
              )}
            </div>

            {(section.fields || []).length > 0 && (
              <div className="rounded-xl border border-slate-100 overflow-hidden">
                {(section.fields || []).map((field, fi) => {
                  const path = `sections.${si}.fields.${fi}.value`;
                  return (
                    <div key={fi} className="grid grid-cols-[32%_1fr] border-t border-slate-100 first:border-t-0">
                      <div className="bg-slate-50/80 px-3 py-2 text-[11px] font-medium text-slate-500">{field.label}</div>
                      <div className="px-3 py-2">
                        {editing ? (
                          <input
                            value={draft[path] ?? ''}
                            onChange={e => setField(path, e.target.value)}
                            className="w-full rounded-md border border-slate-200 px-2 py-1 text-[12.5px] text-slate-800 outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20"
                          />
                        ) : (
                          <>
                            <p className="text-[12.5px] leading-relaxed text-slate-700 whitespace-pre-wrap break-words">{field.value}</p>
                            {field.corrected && (
                              <p className="mt-1 text-[10px] text-amber-700">
                                corrected · was: <span className="line-through">{field.original_value}</span>
                              </p>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {section.table && section.table.columns && (
              <div className="mt-2 overflow-x-auto rounded-xl border border-slate-100">
                <table className="w-full text-[12px] min-w-[420px] border-collapse">
                  <thead>
                    <tr>
                      {section.table.columns.map((col, ci) => (
                        <th key={ci} className="bg-slate-50 text-left px-3 py-2 font-semibold text-slate-500 border-b border-slate-100">{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {section.table.rows.map((row, ri) => (
                      <tr key={ri}>
                        {row.map((cell, ci) => {
                          const path = `sections.${si}.table.rows.${ri}.${ci}`;
                          return (
                            <td key={ci} className="px-3 py-2 text-slate-700 border-t border-slate-100 align-top">
                              {editing ? (
                                <input
                                  value={draft[path] ?? ''}
                                  onChange={e => setField(path, e.target.value)}
                                  className="w-full rounded-md border border-slate-200 px-2 py-1 outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20"
                                />
                              ) : (
                                <span className="whitespace-pre-wrap break-words">{cell}</span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {(section.bullets || []).length > 0 && (
              <ul className="mt-2 space-y-1">
                {section.bullets.map((bullet, bi) => (
                  <li key={bi} className="flex gap-2 text-[12.5px] leading-relaxed text-slate-700">
                    <span className="mt-[7px] w-1 h-1 rounded-full bg-green-500 flex-shrink-0" />
                    <span className="whitespace-pre-wrap break-words">{bullet}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}

        {unclear.length > 0 && !editing && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-3">
            <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-800 mb-1.5">
              <Icon d={I.warn} className="w-3.5 h-3.5" />
              Unclear or missing information
            </p>
            <ul className="space-y-1">
              {unclear.map((item, i) => (
                <li key={i} className="text-[12px] leading-relaxed text-amber-900/80">{item}</li>
              ))}
            </ul>
          </div>
        )}

        {error && (
          <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[12.5px] text-rose-700">{error}</p>
        )}
        {notice && !editing && (
          <p className="mt-4 rounded-xl border border-green-200 bg-green-50 px-4 py-2.5 text-[12.5px] text-green-700">{notice}</p>
        )}

        {/* Extracted text */}
        <div className="mt-4 border-t border-slate-100 pt-3">
          <button onClick={toggleSource} className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 transition-colors hover:text-green-700">
            {showSource ? 'Hide extracted text' : 'View extracted text'}
          </button>
          {showSource && (
            <pre className="mt-2 max-h-64 overflow-auto rounded-xl bg-slate-50 border border-slate-100 p-3.5 text-[11px] leading-relaxed text-slate-600 whitespace-pre-wrap break-words font-mono">
              {sourceText || 'Loading…'}
            </pre>
          )}
        </div>

        {/* Footer actions */}
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3.5">
          {editing ? (
            <>
              <button
                onClick={save}
                disabled={saving}
                className="inline-flex items-center gap-2 rounded-xl bg-green-600 px-3.5 py-2 text-[13px] font-medium text-white shadow-sm transition-all duration-200 hover:bg-green-700 disabled:opacity-60"
              >
                {saving && <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />}
                {saving ? 'Saving…' : 'Save corrections'}
              </button>
              <button
                onClick={() => { setEditing(false); setError(''); }}
                disabled={saving}
                className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[13px] font-medium text-slate-600 transition-all duration-200 hover:bg-slate-50 disabled:opacity-60"
              >
                Cancel
              </button>
              <span className="text-[11px] text-slate-400">{fieldCount} extracted fields</span>
            </>
          ) : (
            <>
              <button
                onClick={startEdit}
                className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[13px] font-medium text-slate-700 transition-all duration-200 hover:border-green-300 hover:text-green-700 hover:bg-green-50"
              >
                <Icon d={I.edit} className="w-3.5 h-3.5" />
                Correct a value
              </button>
              <span className="ml-auto text-[11px] text-slate-400">
                Fields without a note are extractions from this document; corrections take priority in later answers.
              </span>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

function readOriginal(report, path) {
  const parts = path.split('.');
  let current = report;
  for (const part of parts) {
    if (current == null) return '';
    current = current[Array.isArray(current) ? Number(part) : part];
  }
  return current == null ? '' : current;
}
