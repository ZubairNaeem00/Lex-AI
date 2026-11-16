import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/* Turn the machine [SOURCE-i] citation labels into nothing. The retrieved
   sources are still listed under the answer, so the inline markers only add
   noise to the prose and table cells. */
/* Turn the machine [SOURCE-i]/[PRECEDENT-i] citation labels into nothing. The
   retrieved sources are still listed under the answer, so the inline markers
   only add noise to the prose and table cells. Labels are always uppercase and
   carry a number, so requiring both keeps prose words like "source",
   "resources" and "precedents" intact. */
function stripSourceMarkers(text) {
  return String(text || '')
    .replace(/\[\s*\*{0,2}(?:SOURCE|PRECEDENT)[ \t\u2011\u2013-]+\d+[^\]]*\]/g, '')
    .replace(/\[?\s*\*{0,2}(?:SOURCE|PRECEDENT)[ \t\u2011\u2013-]+\d+\*{0,2}\s*\]?/g, '')
    .replace(/\[\s*(?:[,;]\s*)*\]/g, '')
    .replace(/\*\*\s*\*\*/g, '')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/[ \t]+([.,;:!?)])/g, '$1')
    .replace(/\n{3,}/g, '\n\n');
}

const HEADINGS = {
  h1: 'mt-4 mb-2 text-[16px] font-bold text-green-700 first:mt-0',
  h2: 'mt-4 mb-2 text-[15px] font-semibold text-green-700 first:mt-0',
  h3: 'mt-3.5 mb-1.5 text-[14px] font-semibold text-green-700 first:mt-0',
  h4: 'mt-3 mb-1.5 text-[13px] font-semibold text-green-700 first:mt-0',
  h5: 'mt-3 mb-1.5 text-[12.5px] font-semibold text-green-700 first:mt-0',
  h6: 'mt-3 mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-green-700 first:mt-0',
};

const components = {
  h1: ({ children }) => <h1 className={HEADINGS.h1}>{children}</h1>,
  h2: ({ children }) => <h2 className={HEADINGS.h2}>{children}</h2>,
  h3: ({ children }) => <h3 className={HEADINGS.h3}>{children}</h3>,
  h4: ({ children }) => <h4 className={HEADINGS.h4}>{children}</h4>,
  h5: ({ children }) => <h5 className={HEADINGS.h5}>{children}</h5>,
  h6: ({ children }) => <h6 className={HEADINGS.h6}>{children}</h6>,
  p: ({ children }) => <p className="my-2 text-[14px] leading-relaxed first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5 marker:text-green-600">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5 marker:text-green-600">{children}</ol>,
  li: ({ children }) => <li className="text-[13.5px] leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-green-700 underline underline-offset-2 hover:text-green-800">{children}</a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-green-300 pl-3 text-slate-600 italic">{children}</blockquote>
  ),
  hr: () => <hr className="my-3 border-slate-200" />,
  code: ({ className, children, ...props }) => {
    const isBlock = /language-/.test(className || '') || String(children).includes('\n');
    if (isBlock) return <code className={className} {...props}>{children}</code>;
    return <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[12.5px] text-slate-700">{children}</code>;
  },
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded-lg bg-slate-100 p-3 text-[12.5px] leading-relaxed">{children}</pre>
  ),
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full border-collapse text-[12.5px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead>{children}</thead>,
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => <tr className="border-t border-slate-100">{children}</tr>,
  th: ({ children }) => (
    <th className="border-r border-slate-100 bg-slate-50 px-3 py-2 text-left font-semibold text-slate-600 last:border-r-0">{children}</th>
  ),
  td: ({ children }) => (
    <td className="border-r border-slate-100 px-3 py-2 align-top text-slate-700 last:border-r-0">{children}</td>
  ),
};

export default function MarkdownAnswer({ text }) {
  return (
    <div className="text-slate-700">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {stripSourceMarkers(text)}
      </ReactMarkdown>
    </div>
  );
}

