import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { login } from '../api/client';

/* ── Presentational helpers (UI only, no logic) ── */
const Field = ({ label, icon, ...props }) => (
  <label className="block mb-4">
    <span className="block mb-1.5 text-sm font-medium text-slate-700">{label}</span>
    <div className="relative">
      <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-sm opacity-60">{icon}</span>
      <input
        {...props}
        className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-10 pr-3.5 text-sm text-slate-800 placeholder:text-slate-400 shadow-sm outline-none transition-all duration-200 hover:border-slate-300 focus:border-green-500 focus:ring-4 focus:ring-green-100"
      />
    </div>
  </label>
);

const Spinner = () => (
  <span className="inline-block w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />
);

export default function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email || !password) {
      setError('Please fill in all fields.');
      return;
    }
    setError('');
    setLoading(true);

    try {
      await login({ email, password });
      setLoading(false);
      navigate('/chat');
    } catch (err) {
      setLoading(false);
      setError(err.message || 'Invalid email or password.');
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-[1fr_1.1fr] bg-white text-slate-800 antialiased">

      {/* ── Left panel (brand + bento) ── */}
      <aside className="hidden lg:flex flex-col justify-between bg-slate-50 border-r border-slate-200 p-12 xl:p-16 relative overflow-hidden">
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage: 'linear-gradient(#e2e8f0 1px, transparent 1px), linear-gradient(90deg, #e2e8f0 1px, transparent 1px)',
            backgroundSize: '48px 48px',
            maskImage: 'radial-gradient(ellipse 80% 60% at 30% 20%, black, transparent 75%)',
            WebkitMaskImage: 'radial-gradient(ellipse 80% 60% at 30% 20%, black, transparent 75%)',
            opacity: 0.7,
          }}
        />

        {/* Logo */}
        <button onClick={() => navigate('/')} className="relative flex items-center gap-2.5 w-fit group">
          <div className="w-9 h-9 rounded-xl bg-green-600 flex items-center justify-center text-base shadow-sm transition-transform duration-200 group-hover:scale-105">
            ⚖️
          </div>
          <span className="text-lg font-semibold tracking-tight text-slate-900">LexAI</span>
        </button>

        {/* Central copy */}
        <div className="relative">
          <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 shadow-sm mb-6">
            <span className="w-1.5 h-1.5 rounded-full bg-green-600 animate-pulse" />
            Secure Chambers Access
          </span>
          <h2 className="text-5xl font-semibold leading-[1.08] tracking-tight text-slate-900 mb-5">
            Welcome back,<br />
            <span className="text-green-600">Counsellor.</span>
          </h2>
          <p className="text-[15px] leading-relaxed text-slate-500 max-w-sm">
            Sign in to access your cases, documents, and AI-generated legal drafts for Pakistan's judicial system.
          </p>

          {/* Trust bento */}
          <div className="grid grid-cols-2 gap-3 mt-8 max-w-sm">
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <span className="text-lg">🔒</span>
              <p className="mt-2 text-sm font-medium text-slate-900">End-to-end encrypted</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <span className="text-lg">🇵🇰</span>
              <p className="mt-2 text-sm font-medium text-slate-900">Pakistani statutes</p>
            </div>
          </div>
        </div>

        {/* Testimonial */}
        <figure className="relative rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition-all duration-200 hover:shadow-md">
          <div className="flex items-center justify-between mb-4">
            <span className="text-xs font-medium text-green-600">Trusted by counsel</span>
            <span className="text-xs tracking-widest text-amber-400">★★★★★</span>
          </div>
          <blockquote className="text-sm leading-relaxed text-slate-600 mb-5">
            "LexAI reduced our case preparation from days to hours. The statute matching is remarkably accurate for Pakistani law."
          </blockquote>
          <figcaption className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full border border-slate-200 bg-slate-50 flex items-center justify-center text-lg">👨‍⚖️</div>
            <div>
              <p className="text-sm font-semibold text-slate-900">Adv. Fahad Mirza</p>
              <p className="text-xs text-slate-500">Lahore High Court</p>
            </div>
          </figcaption>
        </figure>
      </aside>

      {/* ── Right form ── */}
      <main className="flex items-center justify-center px-6 py-12 sm:px-12">
        <div className="w-full max-w-[400px]">

          {/* Mobile logo */}
          <button onClick={() => navigate('/')} className="flex items-center gap-2 mb-10 lg:hidden">
            <div className="w-8 h-8 rounded-lg bg-green-600 flex items-center justify-center text-sm">⚖️</div>
            <span className="text-lg font-semibold tracking-tight text-slate-900">LexAI</span>
          </button>

          <div className="mb-8">
            <h3 className="text-3xl font-semibold tracking-tight text-slate-900 mb-2">Sign in</h3>
            <p className="text-sm text-slate-500">
              Don't have an account?{' '}
              <Link to="/signup" className="font-medium text-green-600 hover:text-green-700 transition-colors">
                Create one →
              </Link>
            </p>
          </div>

          <form onSubmit={handleSubmit}>
            <Field
              label="Email Address"
              type="email"
              placeholder="you@example.com"
              icon="📧"
              value={email}
              onChange={e => setEmail(e.target.value)}
            />
            <Field
              label="Password"
              type="password"
              placeholder="••••••••"
              icon="🔒"
              value={password}
              onChange={e => setPassword(e.target.value)}
            />

            <div className="flex items-center justify-between mb-6">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" className="w-4 h-4 rounded border-slate-300 accent-green-600" />
                <span className="text-sm text-slate-600">Remember me</span>
              </label>
              <button type="button" className="text-sm font-medium text-green-600 hover:text-green-700 transition-colors">
                Forgot password?
              </button>
            </div>

            {error && (
              <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                ⚠️ {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-green-600 py-3 text-sm font-medium text-white shadow-md transition-all duration-200 hover:bg-green-700 hover:shadow-lg active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-70"
            >
              {loading ? <><Spinner /> Signing in…</> : 'Sign In →'}
            </button>
          </form>

          {/* Footer note */}
          <p className="mt-8 text-center text-xs text-slate-400">
            Protected by chambers-grade encryption · LexAI for Pakistani Counsel
          </p>
        </div>
      </main>
    </div>
  );
}