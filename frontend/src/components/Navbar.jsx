import React, { useState, useEffect } from 'react';
import { NavLink, useNavigate, useLocation } from 'react-router-dom';
import { clearSession, clearStoredCaseId, isAuthenticated, logoutRequest, resetCasePromise } from '../api/client';

const NAV_LINKS = [
  { to: '/',          label: 'Home' },
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/upload',    label: 'Documents' },
  { to: '/chat',      label: 'AI Chat' },
  { to: '/reports',   label: 'Reports' },
];

export default function Navbar() {
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isAuthed, setIsAuthed] = useState(false);

  // Re-read the session every time the page URL changes
  useEffect(() => {
    setIsAuthed(isAuthenticated());
  }, [location]);

  // Revoke the server session too, then drop every trace of this visitor
  const handleLogout = () => {
    logoutRequest().finally(() => {
      clearSession();
      clearStoredCaseId();
      resetCasePromise();
      setIsAuthed(false);
      navigate('/');
    });
  };

  const isAuthPage = ['/login', '/signup', '/forgot-password', '/reset-password'].includes(location.pathname);
  if (isAuthPage) return null;

  return (
    <nav className="sticky top-0 z-50 bg-white/90 backdrop-blur-xl border-b border-slate-200">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Logo */}
        <button onClick={() => navigate('/')} className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-green-600 text-lg text-white shadow-sm shadow-green-600/30">
            ⚖️
          </div>
          <div className="text-left">
            <div className="text-lg font-semibold leading-none text-slate-900">LexAI</div>
            <div className="mt-0.5 text-[9px] uppercase tracking-[1.6px] text-slate-400">
              Pakistan Legal Intelligence
            </div>
          </div>
        </button>

        {/* Desktop links */}
        <div className="hidden items-center gap-1 md:flex">
          {NAV_LINKS.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) => `
                rounded-lg border px-4 py-2 text-sm font-medium transition-all duration-200
                ${isActive
                  ? 'border-green-100 bg-green-50 text-green-700'
                  : 'border-transparent text-slate-500 hover:bg-slate-50 hover:text-slate-900'}
              `}
            >
              {label}
            </NavLink>
          ))}
        </div>

        {/* Right actions (Desktop) */}
        <div className="hidden items-center gap-3 md:flex">
          {isAuthed ? (
            <button
              onClick={handleLogout}
              className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-900"
            >
              Sign Out
            </button>
          ) : (
            <>
              <button
                onClick={() => navigate('/login')}
                className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-900"
              >
                Sign In
              </button>
              <button
                onClick={() => navigate('/signup')}
                className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white shadow-sm shadow-green-600/30 transition-colors hover:bg-green-700"
              >
                Get Started
              </button>
            </>
          )}
        </div>

        {/* Mobile hamburger */}
        <button
          onClick={() => setMobileOpen(o => !o)}
          className="p-2 text-slate-500 transition-colors hover:text-green-600 md:hidden"
        >
          {mobileOpen ? '✕' : '☰'}
        </button>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="animate-fade-in absolute inset-x-0 top-full flex flex-col gap-2 border-b border-slate-200 bg-white p-4 shadow-lg md:hidden">
          {NAV_LINKS.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) => `
                rounded-xl px-4 py-3 text-sm font-medium
                ${isActive ? 'bg-green-50 text-green-700' : 'text-slate-500'}
              `}
            >
              {label}
            </NavLink>
          ))}
          <div className="flex gap-3 border-t border-slate-200 pt-3">
            {isAuthed ? (
              <button
                onClick={() => { setMobileOpen(false); handleLogout(); }}
                className="flex-1 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-600"
              >
                Sign Out
              </button>
            ) : (
              <>
                <button
                  onClick={() => { setMobileOpen(false); navigate('/login'); }}
                  className="flex-1 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-600"
                >
                  Sign In
                </button>
                <button
                  onClick={() => { setMobileOpen(false); navigate('/signup'); }}
                  className="flex-1 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-medium text-white"
                >
                  Get Started
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </nav>
  );
}