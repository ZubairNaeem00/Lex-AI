import React from 'react';

const Icon = ({ d, className = 'w-4 h-4' }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {[].concat(d).map((p, i) => <path key={i} d={p} />)}
  </svg>
);

const I = {
  brain: ['M12 5a3 3 0 0 0-3 3', 'M9 8a3 3 0 0 0-1 5.8', 'M12 5a3 3 0 0 1 3 3', 'M15 8a3 3 0 0 1 1 5.8', 'M12 5v14', 'M8 14a3 3 0 0 0 4 3', 'M16 14a3 3 0 0 1-4 3'],
  warn: ['M12 9v4', 'M12 17h.01', 'M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'],
};

/* Read-only render of an analyze_document report for a precedent's text.
   Mirrors the AnalysisCard visual language without edit/source handlers, since
   a precedent analysis is not a persisted case document. */
export default function CaseAnalysisReport({ report }) {
  if (!report) return null;
  const sections = report.sections || [];
  const unclear = report.unclear_information || [];

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-start gap-3.5 border-b border-slate-100 bg-gradient-to-b from-slate-50 to-white px-5 pb-3.5 pt-4">
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-green-600 text-white">
          <Icon d={I.brain} className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-[1.5px] text-green-700">
            AI analysis · {report.document_type && report.document_type.toLowerCase() !== 'unknown' ? report.document_type : 'Case precedent'}
          </p>
          <h3 className="mt-0.5 break-words text-[15px] font-semibold leading-snug text-slate-900">
            {report.title || 'Case analysis'}
          </h3>
        </div>
      </header>

      <div className="px-5 py-4">
        {report.summary && (
          <div className="mb-4">
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[1.5px] text-slate-400">Summary</p>
            <p className="text-[13px] leading-relaxed text-slate-600">{report.summary}</p>
          </div>
        )}

        {sections.map((section, si) => (
          <section key={si} className="mt-4 first:mt-0">
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <h4 className="text-[13px] font-semibold text-slate-900">{section.title}</h4>
              {section.summary && <span className="line-clamp-1 text-[11px] text-slate-400">{section.summary}</span>}
            </div>

            {(section.fields || []).length > 0 && (
              <div className="overflow-hidden rounded-xl border border-slate-100">
                {section.fields.map((field, fi) => (
                  <div key={fi} className="grid grid-cols-[32%_1fr] border-t border-slate-100 first:border-t-0">
                    <div className="bg-slate-50/80 px-3 py-2 text-[11px] font-medium text-slate-500">{field.label}</div>
                    <div className="px-3 py-2">
                      <p className="whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-slate-700">{field.value}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {section.table && section.table.columns && (
              <div className="mt-2 overflow-x-auto rounded-xl border border-slate-100">
                <table className="w-full min-w-[420px] border-collapse text-[12px]">
                  <thead>
                    <tr>
                      {section.table.columns.map((col, ci) => (
                        <th key={ci} className="border-b border-slate-100 bg-slate-50 px-3 py-2 text-left font-semibold text-slate-500">{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(section.table.rows || []).map((row, ri) => (
                      <tr key={ri}>
                        {row.map((cell, ci) => (
                          <td key={ci} className="border-t border-slate-100 px-3 py-2 align-top text-slate-700">
                            <span className="whitespace-pre-wrap break-words">{cell}</span>
                          </td>
                        ))}
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
                    <span className="mt-[7px] h-1 w-1 flex-shrink-0 rounded-full bg-green-500" />
                    <span className="whitespace-pre-wrap break-words">{bullet}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}

        {unclear.length > 0 && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-3">
            <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-800">
              <Icon d={I.warn} className="h-3.5 w-3.5" />
              Unclear or missing information
            </p>
            <ul className="space-y-1">
              {unclear.map((item, i) => (
                <li key={i} className="text-[12px] leading-relaxed text-amber-900/80">{item}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}