import React, { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { resetPassword } from '../api/client';
import AuthCard, { AuthError, AuthField, AuthSpinner, submitClass } from '../components/auth/AuthCard';

/* Mirrors validate_password_strength in db/schemas.py. */
const PASSWORD_RULES = [
  { label: 'At least 8 characters', test: (v) => v.length >= 8 },
  { label: 'One letter', test: (v) => /[A-Za-z]/.test(v) },
  { label: 'One number', test: (v) => /\d/.test(v) },
  { label: 'One special character (! @ # $ %)', test: (v) => /[^A-Za-z0-9\s]/.test(v) },
];

const PasswordRules = ({ value }) => (
  <ul className="-mt-1 mb-4 grid grid-cols-1 gap-x-3 gap-y-1.5 sm:grid-cols-2">
    {PASSWORD_RULES.map((rule) => {
      const met = rule.test(value);
      return (
        <li key={rule.label} className={`flex items-center gap-1.5 text-[11px] transition-colors duration-200 ${met ? 'text-green-700' : 'text-slate-500'}`}>
          <span aria-hidden="true" className={met ? 'text-green-600' : 'text-slate-300'}>{met ? '✓' : '○'}</span>
          {rule.label}
        </li>
      );
    })}
  </ul>
);

export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = (params.get('token') || '').trim();

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const requestNewLink = (
    <Link to="/forgot-password" className="font-medium text-green-600 transition-colors hover:text-green-700">
      Request a new reset link →
    </Link>
  );

  if (!token) {
    return (
      <AuthCard
        title="Reset link incomplete"
        subtitle="This page needs the token from the reset email. Open the link in that email, or ask for a new one."
        footer={<Link to="/login" className="font-medium text-green-600 transition-colors hover:text-green-700">← Back to sign in</Link>}
      >
        {requestNewLink}
      </AuthCard>
    );
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (password.length > 128) return setError('Password must be at most 128 characters long.');
    const unmet = PASSWORD_RULES.find((rule) => !rule.test(password));
    if (unmet) return setError(`Password needs ${unmet.label.toLowerCase()}.`);
    if (password !== confirm) return setError('The two passwords do not match.');

    setError('');
    setLoading(true);
    try {
      const result = await resetPassword({ token, newPassword: password });
      setLoading(false);
      navigate('/login', {
        replace: true,
        state: { notice: result.detail || 'Password updated. Please sign in again.' },
      });
    } catch (err) {
      setLoading(false);
      setError(err.status === 429
        ? 'Too many attempts. Please wait a few minutes and try again.'
        : err.message || 'Could not reset the password. Please try again.');
    }
  };

  return (
    <AuthCard
      title="Choose a new password"
      subtitle="Your new password signs you out everywhere else, so every device will need to sign in again."
      footer={requestNewLink}
    >
      <form onSubmit={handleSubmit} noValidate>
        <AuthField
          label="New Password"
          type="password"
          placeholder="••••••••"
          icon="🔒"
          value={password}
          autoComplete="new-password"
          onChange={(e) => { setPassword(e.target.value); setError(''); }}
        />
        <PasswordRules value={password} />
        <AuthField
          label="Confirm New Password"
          type="password"
          placeholder="••••••••"
          icon="🔒"
          value={confirm}
          autoComplete="new-password"
          onChange={(e) => { setConfirm(e.target.value); setError(''); }}
        />
        {confirm && password !== confirm && (
          <p className="-mt-2 mb-4 text-[11px] text-red-600">The two passwords do not match yet.</p>
        )}

        {error && <AuthError>{error}</AuthError>}

        <button type="submit" disabled={loading} className={submitClass}>
          {loading ? <><AuthSpinner /> Updating password…</> : 'Update password →'}
        </button>
      </form>

      <p className="mt-5 text-xs leading-relaxed text-slate-400">
        Stored as an Argon2id hash — the server never keeps your password in plain text.
      </p>
    </AuthCard>
  );
}