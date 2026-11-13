import React from 'react';
import { Outlet, useLocation } from 'react-router-dom';

export default function DashboardLayout() {
  const { pathname } = useLocation();
  const height = pathname === '/chat' ? 'h-screen' : 'h-[calc(100vh-65px)]';

  return (
    <div className={`flex ${height} overflow-hidden`}>
      <main className="flex-1 overflow-y-auto bg-slate-50">
        <Outlet />
      </main>
    </div>
  );
}
