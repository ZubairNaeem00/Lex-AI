import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronUp, LogOut, Settings, UserRound } from 'lucide-react';
import { clearSession, clearStoredCaseId, getAuthUser, resetCasePromise } from '../../api/client';
import ProfileModal from './ProfileModal';
import SettingsModal from './SettingsModal';

const ITEMS = [
  { key: 'profile', label: 'Profile', icon: UserRound },
  { key: 'settings', label: 'Settings', icon: Settings },
];

function initialsOf(name) {
  return (name || '').split(' ').filter(Boolean).slice(0, 2)
    .map((part) => part[0].toUpperCase()).join('') || 'L';
}

/* The sidebar account strip: hovering (or tapping) it opens Profile / Settings / Log out. */
export default function AccountSection({ onLogout }) {
  const navigate = useNavigate();
  const [account, setAccount] = useState(getAuthUser);
  const [menuOpen, setMenuOpen] = useState(false);
  const [panel, setPanel] = useState(null);
  const closeTimer = useRef(null);
  const wrapRef = useRef(null);

  useEffect(() => () => clearTimeout(closeTimer.current), []);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    const onDocClick = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setMenuOpen(false);
    };
    window.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDocClick);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDocClick);
    };
  }, [menuOpen]);

  const openMenu = () => {
    clearTimeout(closeTimer.current);
    setMenuOpen(true);
  };

  /* A short grace period so the pointer can cross the gap between strip and panel. */
  const closeMenuSoon = () => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setMenuOpen(false), 160);
  };

  const showPanel = (key) => {
    setMenuOpen(false);
    setPanel(key);
  };

  const handleSaved = (user) => setAccount(user);

  const handlePasswordChanged = () => {
    // The backend revokes every session when the hash changes, so sign in again.
    clearSession();
    clearStoredCaseId();
    resetCasePromise();
    setPanel(null);
    navigate('/login', { state: { notice: 'Password updated. Please sign in again.' } });
  };

  const displayName = (account && account.full_name) || 'Guest';
  const email = (account && account.email) || '';
  const occupation = (account && account.profile && account.profile.occupation) || 'Advocate';

  return (
    <div
      ref={wrapRef}
      className="relative"
      onMouseEnter={openMenu}
      onMouseLeave={closeMenuSoon}
    >
      {menuOpen && (
        <div className="absolute bottom-full left-0 z-40 mb-2 w-full overflow-hidden rounded-xl border border-slate-200 bg-white p-1 shadow-lg animate-fade-up">
          <div className="border-b border-slate-100 px-3 py-2">
            <p className="truncate text-[13px] font-medium leading-tight text-slate-900">{displayName}</p>
            <p className="truncate text-[11px] text-slate-500">{email || occupation}</p>
          </div>
          {ITEMS.map((item) => (
            <button
              key={item.key}
              onClick={() => showPanel(item.key)}
              className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] text-slate-700 transition-colors hover:bg-slate-100"
            >
              <item.icon className="w-3.5 h-3.5 shrink-0 text-slate-400" />
              {item.label}
            </button>
          ))}
          <button
            onClick={() => { setMenuOpen(false); onLogout(); }}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] text-rose-600 transition-colors hover:bg-rose-50"
          >
            <LogOut className="w-3.5 h-3.5 shrink-0" />
            Log out
          </button>
        </div>
      )}

      <button
        onClick={openMenu}
        aria-expanded={menuOpen}
        aria-haspopup="menu"
        title="Account"
        className={`flex w-full items-center gap-3 rounded-xl px-1.5 py-1 text-left transition-colors hover:bg-slate-100
          ${menuOpen ? 'bg-slate-100' : ''}`}
      >
        <div className="w-8 h-8 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center text-[11px] font-semibold text-slate-500 shrink-0">
          {initialsOf(displayName)}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-slate-900 truncate leading-none">{displayName}</p>
          <p className="text-[11px] text-slate-500 mt-0.5">{occupation}</p>
        </div>
        <ChevronUp className={`w-3.5 h-3.5 text-slate-400 shrink-0 transition-transform duration-150 ${menuOpen ? 'rotate-180' : ''}`} />
      </button>

      <ProfileModal open={panel === 'profile'} onClose={() => setPanel(null)} onSaved={handleSaved} />
      <SettingsModal open={panel === 'settings'} onClose={() => setPanel(null)} onPasswordChanged={handlePasswordChanged} />
    </div>
  );
}
