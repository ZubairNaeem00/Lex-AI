import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { forgotPassword } from '../api/client';
import AuthCard, { AuthError, AuthField, AuthSpinner, submitClass } from '../components/auth/AuthCard';

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export default function ForgotPasswordPage() {
  const location = useLocation();
  const [email, setEmail] = useState((location.state && location.state.email) || '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const address = email.trim();
    if (!EMAIL_PATTERN.test(address)) return setError('Please enter a valid email address.');

    setError('');
    setLoading(true);
    try {
      const result = await forgotPassword(address);
      setLoading(false);
      setSent(result);
    } catch (err) {
      setLoading(false);
      setError(err.status === 429
        ? 'Too many reset requests. Please wait a few minutes and try again.'
        : err.message || 'Could not send the reset link. Please try again.');
    }
  };

  if (sent) {
    return (
      <AuthCard
        title="Check your inbox"
        subtitle={sent.detail || 'If that email is registered, a reset link has been sent.'}
        footer={<Link to="/login" className="font-medium text-green-600 transition-colors hover:text-green-700">← Back to sign in</Link>}
      >
        <div className="mb-5 rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-sm leading-relaxed text-green-800">
          ✓ If <span className="font-medium">{email.trim()}</span> has an account, the link is on its way.
          It works once and expires automatically, so use it soon. Check spam if it has not arrived.
        </div>

        {/* Resend's test sender only delivers to the account owner, so the local
            demo also returns the link (EXPOSE_AUTH_LINKS). Never shown in production. */}
        {sent.reset_link && (
          <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            <p className="mb-2 font-medium">Local demo link</p>
            <a href={sent.reset_link} className="break-all font-medium text-green-700 underline hover:text-green-800">
              Open the reset page →
            </a>
          </div>
        )}

        <button
          type="button"
          onClick={() => { setSent(null); setError(''); }}
          className="text-sm font-medium text-slate-600 transition-colors hover:text-slate-900"
        >
          Use a different email
        </button>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Forgot password?"
      subtitle="Enter the email you registered with and we will send you a link to choose a new password."
      footer={<>Remembered it?{' '}<Link to="/login" className="font-medium text-green-600 transition-colors hover:text-green-700">Sign in →</Link></>}
    >
      <form onSubmit={handleSubmit} noValidate>
        <AuthField
          label="Email Address"
          type="email"
          placeholder="you@example.com"
          icon="📧"
          value={email}
          autoComplete="email"
          onChange={(e) => { setEmail(e.target.value); setError(''); }}
        />

        {error && <AuthError>{error}</AuthError>}

        <button type="submit" disabled={loading} className={submitClass}>
          {loading ? <><AuthSpinner /> Sending link…</> : 'Send reset link →'}
        </button>
      </form>

      <p className="mt-5 text-xs leading-relaxed text-slate-400">
        For your security we never confirm whether an address has an account.
      </p>
    </AuthCard>
  );
}