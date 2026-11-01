import React from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { getAuthUser } from '../api/client';

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
  const account = getAuthUser();
  const displayName = (account && account.full_name) || 'Guest';
  const occupation = (account && account.profile && account.profile.occupation) || 'Advocate';
  const initials = displayName.split(' ').filter(Boolean).slice(0, 2)
    .map((part) => part[0].toUpperCase()).join('') || 'L';

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
        <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-green-600 text-xs font-bold text-white">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium leading-none text-slate-900">{displayName}</p>
            <p className="mt-0.5 truncate text-[10px] text-slate-400">{occupation}</p>
          </div>
        </div>
      </div>
    </aside>
  );
}