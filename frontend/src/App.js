import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import { isAuthenticated } from './api/client';
import Navbar          from './components/Navbar';
import DashboardLayout from './components/DashboardLayout';

import LandingPage  from './pages/LandingPage';
import LoginPage    from './pages/LoginPage';
import SignupPage   from './pages/SignupPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import ResetPasswordPage  from './pages/ResetPasswordPage';
import DashboardPage from './pages/DashboardPage';
import UploadPage   from './pages/UploadPage';
import ChatPage     from './pages/ChatPage';
import ReportsPage  from './pages/ReportsPage';

/* Only the homepage and the sign-in/recovery pages are public: every app page
   needs a signed-in account. */
function RequireAuth({ children }) {
  return isAuthenticated() ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      {/* Global navbar (hides itself on /login and /signup) */}
      <Navbar />

      <Routes>
        {/* ── Public routes ── */}
        <Route path="/"       element={<LandingPage />} />
        <Route path="/login"  element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password"  element={<ResetPasswordPage />} />

        {/* ── App routes (signed in, with sidebar) ── */}
        <Route element={<RequireAuth><DashboardLayout /></RequireAuth>}>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/upload"    element={<UploadPage />} />
          <Route path="/chat"      element={<ChatPage />} />
          <Route path="/reports"   element={<ReportsPage />} />
        </Route>

        {/* ── Catch-all ── */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
