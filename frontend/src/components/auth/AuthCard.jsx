import React from 'react';
import { Link } from 'react-router-dom';

/* Shared frame for the password-recovery pages, styled like the sign-in form. */
export default function AuthCard({ title, subtitle, children, footer }) {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-50 px-6 py-12 text-slate-800 antialiased">
      <div
        className="theme-grid pointer-events-none absolute inset-0"
        style={{
          backgroundImage: 'linear-gradient(#e2e8f0 1px, transparent 1px), linear-gradient(90deg, #e2e8f0 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse 70% 60% at 50% 0%, black, transparent 75%)',
          WebkitMaskImage: 'radial-gradient(ellipse 70% 60% at 50% 0%, black, transparent 75%)',
          opacity: 0.7,
        }}
      />

      <div className="relative w-full max-w-[420px]">
        <Link to="/" className="group mb-8 flex w-fit items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-green-600 text-base shadow-sm transition-transform duration-200 group-hover:scale-105">
            ⚖️
          </span>
          <span className="text-lg font-semibold tracking-tight text-slate-900">LexAI</span>
        </Link>

        <div className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm sm:p-8">
          <h1 className="mb-2 text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
          <p className="mb-6 text-sm leading-relaxed text-slate-500">{subtitle}</p>
          {children}
        </div>

        {footer && <div className="mt-6 text-center text-sm text-slate-500">{footer}</div>}
      </div>
    </div>
  );
}

export const AuthField = ({ label, icon, ...props }) => (
  <label className="mb-4 block">
    <span className="mb-1.5 block text-sm font-medium text-slate-700">{label}</span>
    <span className="relative block">
      <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-sm opacity-60">{icon}</span>
      <input
        {...props}
        className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-10 pr-3.5 text-sm text-slate-800 shadow-sm outline-none transition-all duration-200 placeholder:text-slate-400 hover:border-slate-300 focus:border-green-500 focus:ring-4 focus:ring-green-100"
      />
    </span>
  </label>
);

export const AuthSpinner = () => (
  <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
);

export const AuthError = ({ children }) => (
  <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
    ⚠️ {children}
  </div>
);

export const submitClass =
  'flex w-full items-center justify-center gap-2 rounded-xl bg-green-600 py-3 text-sm font-medium text-white shadow-md transition-all duration-200 hover:bg-green-700 hover:shadow-lg active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-70';