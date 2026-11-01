import React from 'react';

/* ─────────────────────────────────────────────
   GoldButton (now the primary green button)
───────────────────────────────────────────── */
export const GoldButton = ({ children, onClick, className = '', size = 'md', type = 'button', disabled = false }) => {
  const sizes = {
    sm: 'px-4 py-2 text-sm',
    md: 'px-6 py-3 text-sm',
    lg: 'px-8 py-4 text-base',
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`
        inline-flex items-center justify-center gap-2 font-semibold rounded-lg
        bg-green-600 text-white transition-all duration-200 tracking-wide
        hover:bg-green-700 hover:-translate-y-0.5 hover:shadow-md hover:shadow-green-600/30
        active:translate-y-0 disabled:opacity-50 disabled:cursor-not-allowed
        ${sizes[size]} ${className}
      `}
    >
      {children}
    </button>
  );
};

/* ─────────────────────────────────────────────
   OutlineButton
───────────────────────────────────────────── */
export const OutlineButton = ({ children, onClick, className = '', size = 'md', type = 'button' }) => {
  const sizes = {
    sm: 'px-4 py-2 text-sm',
    md: 'px-6 py-3 text-sm',
    lg: 'px-8 py-4 text-base',
  };
  return (
    <button
      type={type}
      onClick={onClick}
      className={`
        inline-flex items-center justify-center gap-2 font-medium rounded-lg
        bg-white text-slate-600 border border-slate-200 transition-all duration-200
        hover:border-green-300 hover:text-green-700 hover:bg-green-50
        ${sizes[size]} ${className}
      `}
    >
      {children}
    </button>
  );
};

/* ─────────────────────────────────────────────
   Card
───────────────────────────────────────────── */
export const Card = ({ children, className = '', topAccent = false, glow = false }) => (
  <div className={`
    bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm
    ${glow ? 'shadow-md shadow-green-600/10' : ''}
    ${className}
  `}>
    {topAccent && (
      <div className="h-0.5 bg-green-600" />
    )}
    {children}
  </div>
);

/* ─────────────────────────────────────────────
   Badge
───────────────────────────────────────────── */
export const Badge = ({ children, color = 'gold', className = '' }) => {
  const colors = {
    gold:    'bg-green-50 border-green-200 text-green-700',
    green:   'bg-emerald-50 border-emerald-200 text-emerald-700',
    red:     'bg-rose-50 border-rose-200 text-rose-700',
    muted:   'bg-slate-100 border-slate-200 text-slate-500',
  };
  return (
    <span className={`
      inline-flex items-center gap-1.5 px-3 py-1 rounded-full border
      text-[11px] font-medium tracking-widest uppercase
      ${colors[color] || colors.gold} ${className}
    `}>
      {children}
    </span>
  );
};

/* ─────────────────────────────────────────────
   Input
───────────────────────────────────────────── */
export const Input = ({ label, type = 'text', placeholder, value, onChange, icon, className = '' }) => (
  <div className={`mb-5 ${className}`}>
    {label && (
      <label className="mb-2 block text-[11px] font-medium uppercase tracking-widest text-slate-500">
        {label}
      </label>
    )}
    <div className="relative">
      {icon && (
        <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-base">
          {icon}
        </span>
      )}
      <input
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        className={`
          w-full rounded-xl border border-slate-300 bg-white
          ${icon ? 'pl-10 pr-4' : 'px-4'} py-3
          text-sm text-slate-900 placeholder-slate-400
          transition-colors duration-200
          focus:outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20
        `}
      />
    </div>
  </div>
);

/* ─────────────────────────────────────────────
   Textarea
───────────────────────────────────────────── */
export const Textarea = ({ placeholder, value, onChange, onKeyDown, rows = 1, className = '' }) => (
  <textarea
    placeholder={placeholder}
    value={value}
    onChange={onChange}
    onKeyDown={onKeyDown}
    rows={rows}
    className={`
      w-full rounded-xl border border-slate-300 bg-white px-4 py-3
      text-sm text-slate-900 placeholder-slate-400 resize-none leading-relaxed
      transition-colors duration-200 focus:outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20
      ${className}
    `}
  />
);

/* ─────────────────────────────────────────────
   SectionLabel
───────────────────────────────────────────── */
export const SectionLabel = ({ children }) => (
  <p className="mb-2 text-[10px] font-medium uppercase tracking-[2.5px] text-green-600">
    {children}
  </p>
);

/* ─────────────────────────────────────────────
   GoldDivider
───────────────────────────────────────────── */
export const GoldDivider = () => (
  <div className="my-1 h-px bg-slate-200" />
);

/* ─────────────────────────────────────────────
   Spinner
───────────────────────────────────────────── */
export const Spinner = ({ size = 4 }) => (
  <div
    className={`w-${size} h-${size} border-2 border-white border-t-transparent rounded-full animate-spin`}
  />
);

/* ─────────────────────────────────────────────
   StatutePill
───────────────────────────────────────────── */
export const StatutePill = ({ children }) => (
  <span className="rounded-lg border border-green-200 bg-green-50 px-3 py-1 text-[11px] font-medium text-green-700">
    {children}
  </span>
);

/* ─────────────────────────────────────────────
   ProgressBar
───────────────────────────────────────────── */
export const ProgressBar = ({ value }) => (
  <div className="mt-2 h-[3px] overflow-hidden rounded-full bg-slate-200">
    <div
      className="h-full rounded-full bg-green-600 transition-all duration-500"
      style={{ width: `${value}%` }}
    />
  </div>
);

/* ─────────────────────────────────────────────
   SimilarityBar
───────────────────────────────────────────── */
export const SimilarityBar = ({ value }) => (
  <div className="mt-2 flex items-center gap-2">
    <span className="text-[10px] text-slate-500">Match</span>
    <div className="h-1 flex-1 overflow-hidden rounded-full bg-slate-200">
      <div className="h-full rounded-full bg-green-600" style={{ width: `${value}%` }} />
    </div>
    <span className="text-[11px] font-medium text-green-700">{value}%</span>
  </div>
);

/* ─────────────────────────────────────────────
   TypingDots
───────────────────────────────────────────── */
export const TypingDots = () => (
  <div className="flex gap-1.5 px-1 py-1">
    {[0, 1, 2].map(i => (
      <div
        key={i}
        className="h-2 w-2 animate-bounce rounded-full bg-green-600"
        style={{ animationDelay: `${i * 0.2}s` }}
      />
    ))}
  </div>
);