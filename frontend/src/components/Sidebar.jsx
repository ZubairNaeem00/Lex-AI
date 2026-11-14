import React, { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { LogOut } from 'lucide-react';
import { clearSession, clearStoredCaseId, logoutRequest, resetCasePromise } from '../api/client';
import AccountSection from './account/AccountSection';
import ConfirmDialog from './chat/ConfirmDialog';

const ITEMS = [
  {
    group: 'Workspace',
    links: [
      { to: '/dashboard', label: 'Overview',   icon: '🏠', exact: true },
      { to: '/upload',    label: 'Documents',  icon: '📁', badge: '4', badgeColor: 'gold' },
      { to: '/chat',      label: 'AI Chat',    icon: '💬', badge: '1', badgeColor: 'gold' },
      { to: '/reports',   label: 'Reports',    icon: '📋', badge: '3' },
    ],
  },
  {
    group: 'Legal Database',
    links: [
      { to: '/dashboard/ppc',       label: 'PPC Statutes',  icon: '📜' },
      { to: '/dashboard/crpc',      label: 'CrPC Sections', icon: '⚖️' },
      { to: '/dashboard/precedents',label: 'Precedents',    icon: '🏛️', badge: '2.4k' },
    ],
  },
  {
    group: 'Cases',
    links: [
      { to: '/dashboard/active', label: 'Active Cases', icon: '🔴', badge: '2', badgeColor: 'gold' },
      { to: '/dashboard/closed', label: 'Closed Cases', icon: '✅', badge: '11' },
    ],
  },
];

export default function Sidebar() {
  const navigate = useNavigate();
  const [signOutOpen, setSignOutOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  const handleSignOut = async () => {
    setSigningOut(true);
    await logoutRequest();
    clearSession();
    clearStoredCaseId();
    resetCasePromise();
    setSigningOut(false);
    setSignOutOpen(false);
    navigate('/login', { state: { notice: 'You are signed out. Sign in to continue.' } });
  };

  return (
    <aside className="w-[220px] flex-shrink-0 border-r border-slate-200 bg-slate-50 flex flex-col overflow-y-auto">
      {/* Logo strip */}
      <button
        onClick={() => navigate('/')}
        className="flex items-center gap-3 border-b border-slate-200 px-5 py-4 transition-colors hover:bg-white"
      >
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-green-600 text-sm text-white shadow-sm shadow-green-600/30">
          ⚖️
        </div>
        <span className="text-lg font-semibold text-slate-900">LexAI</span>
      </button>

      {/* Nav items */}
      <nav className="flex-1 p-3">
        {ITEMS.map(section => (
          <div key={section.group} className="mb-1">
            <p className="px-3 pb-2 pt-3 text-[10px] font-medium uppercase tracking-[1.6px] text-slate-400">
              {section.group}
            </p>
            {section.links.map(item => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.exact}
                className={({ isActive }) => `
                  mb-0.5 flex items-center gap-2.5 rounded-lg px-3 py-2.5
                  text-sm font-medium transition-all duration-200
                  ${isActive
                    ? 'bg-green-50 text-green-700'
                    : 'text-slate-500 hover:bg-white hover:text-slate-900'}
                `}
              >
                <span className="w-5 text-center text-base">{item.icon}</span>
                <span className="flex-1 leading-none">{item.label}</span>
                {item.badge && (
                  <span className={`
                    rounded-full px-2 py-0.5 text-[10px] font-medium
                    ${item.badgeColor === 'gold'
                      ? 'bg-green-100 text-green-700'
                      : 'bg-slate-200 text-slate-500'}
                  `}>
                    {item.badge}
                  </span>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* User strip */}
      <div className="border-t border-slate-200 p-3">
        <AccountSection onLogout={() => setSignOutOpen(true)} />
      </div>

      {signOutOpen && (
        <ConfirmDialog
          title="Sign out of LexAI?"
          message="Conversations you have started stay in your account."
          confirmLabel="Sign out"
          cancelLabel="Stay signed in"
          danger
          busy={signingOut}
          icon={<LogOut className="w-4 h-4" />}
          onConfirm={handleSignOut}
          onCancel={() => !signingOut && setSignOutOpen(false)}
        />
      )}
    </aside>
  );
}