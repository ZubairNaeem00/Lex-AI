import React, { useEffect, useState } from 'react';
import { Check, Eye, EyeOff, KeyRound, Loader2, Moon, Palette, ShieldCheck, Sun, X } from 'lucide-react';
import { changePassword } from '../../api/client';
import { getTheme, setTheme, THEMES } from '../../theme';

const MIN_LENGTH = 8;

/* Add a future section here and render its pane below — the nav follows automatically. */
const SECTIONS = [
  { key: 'password', label: 'Change password', hint: 'Change your account password', icon: KeyRound },
  { key: 'themes', label: 'Themes', hint: 'Choose how LexAI looks', icon: Palette },
];

/* Mirrors the backend policy in db/schemas.py so a rejected form never reaches the API. */
function passwordProblem(value) {
  if (!value) return 'Enter a new password.';
  if (value.length < MIN_LENGTH) return `Password must be at least ${MIN_LENGTH} characters long.`;
  if (value.length > 128) return 'Password must be at most 128 characters long.';
  if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) return 'Password must contain at least one letter and one number.';
  if (!/[^A-Za-z0-9\s]/.test(value)) return 'Password must contain at least one special character, such as ! @ # $ % & *';
  if (value.length > 1 && /^(.)\1*$/.test(value)) return 'Password must not be a single repeated character.';
  return '';
}

const PasswordField = ({ label, value, onChange, onKeyDown, placeholder, autoComplete, error }) => {
  const [visible, setVisible] = useState(false);
  return (
    <label className="block">
      <span className="mb-1.5 block text-[12px] font-medium text-slate-600">{label}</span>
      <div className="relative">
        <input
          type={visible ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          autoComplete={autoComplete}
          maxLength={128}
          className={`w-full rounded-xl border bg-white py-2.5 pl-3.5 pr-11 text-[13px] text-slate-800 placeholder:text-slate-400
            shadow-sm outline-none transition-all duration-200 focus:ring-4
            ${error
              ? 'border-rose-300 focus:border-rose-500 focus:ring-rose-100'
              : 'border-slate-200 hover:border-slate-300 focus:border-green-500 focus:ring-green-100'}`}
        />
        <button
          type="button"
          onClick={() => setVisible((prev) => !prev)}
          aria-label={visible ? 'Hide password' : 'Show password'}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
        >
          {visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
      {error && <span className="mt-1.5 block text-[12px] text-rose-600">{error}</span>}
    </label>
  );
};

const PREVIEW = {
  light: { page: '#f8fafc', surface: '#ffffff', line: '#e2e8f0', ink: '#0f172a', muted: '#94a3b8', brand: '#1f6640' },
  dark: { page: '#0f1626', surface: '#131c2c', line: '#263145', ink: '#eef2f8', muted: '#7d8ca3', brand: '#3f9d6e' },
};

/* Each preview is painted with its own palette, so it stays truthful while the other one is active. */
const ThemePreview = ({ theme }) => {
  const c = PREVIEW[theme];
  return (
    <div className="flex h-[92px] overflow-hidden rounded-lg border" style={{ background: c.page, borderColor: c.line }}>
      <div className="w-[30%] shrink-0 border-r p-2" style={{ background: c.surface, borderColor: c.line }}>
        <div className="h-2 w-2 rounded" style={{ background: c.brand }} />
        <div className="mt-2 h-1 w-full rounded-full" style={{ background: c.brand, opacity: 0.55 }} />
        <div className="mt-1.5 h-1 w-4/5 rounded-full" style={{ background: c.muted, opacity: 0.5 }} />
        <div className="mt-1.5 h-1 w-3/5 rounded-full" style={{ background: c.muted, opacity: 0.5 }} />
      </div>
      <div className="min-w-0 flex-1 p-2">
        <div className="h-1.5 w-1/2 rounded-full" style={{ background: c.ink, opacity: 0.85 }} />
        <div className="mt-2 rounded-md border p-1.5" style={{ background: c.surface, borderColor: c.line }}>
          <div className="h-1 w-3/4 rounded-full" style={{ background: c.muted }} />
          <div className="mt-1 h-1 w-1/2 rounded-full" style={{ background: c.muted, opacity: 0.6 }} />
        </div>
        <div className="mt-2 flex items-center gap-1.5">
          <div className="h-3 w-9 rounded" style={{ background: c.brand }} />
          <div className="h-3 w-6 rounded border" style={{ borderColor: c.line }} />
        </div>
      </div>
    </div>
  );
};

function ThemesPane() {
  const [theme, setLocalTheme] = useState(getTheme);
  const choose = (key) => setLocalTheme(setTheme(key));

  return (
    <div>
      <h4 className="text-[14px] font-semibold text-slate-900">Appearance</h4>
      <p className="mt-1 text-[12px] leading-relaxed text-slate-500">
        The palette used across the dashboard, chat, reports and document editor.
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {THEMES.map((option) => {
          const selected = theme === option.key;
          const Icon = option.key === 'dark' ? Moon : Sun;
          return (
            <label key={option.key} className="block cursor-pointer">
              <input
                type="radio"
                name="lexai-theme"
                value={option.key}
                checked={selected}
                onChange={() => choose(option.key)}
                className="peer sr-only"
              />
              <div
                className={`rounded-xl border-2 p-2.5 transition-all duration-200 peer-focus-visible:ring-4 peer-focus-visible:ring-green-100
                  ${selected ? 'border-green-500 bg-green-50/60 shadow-sm' : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'}`}
              >
                <ThemePreview theme={option.key} />
                <div className="mt-2.5 flex items-center gap-2 px-0.5">
                  <Icon className={`w-3.5 h-3.5 shrink-0 ${selected ? 'text-green-600' : 'text-slate-400'}`} />
                  <span className={`text-[13px] font-medium ${selected ? 'text-green-700' : 'text-slate-700'}`}>{option.label}</span>
                  <span className="truncate text-[11px] text-slate-400">{option.note}</span>
                  {selected && <Check className="ml-auto w-4 h-4 shrink-0 text-green-600" />}
                </div>
              </div>
            </label>
          );
        })}
      </div>

      <p className="mt-4 text-[12px] leading-relaxed text-slate-500">
        Applies straight away and is remembered on this device. Drafts keep their white page, so what
        you edit still matches the printed document.
      </p>
    </div>
  );
}

export default function SettingsModal({ open, onClose, onPasswordChanged }) {
  const [section, setSection] = useState('password');
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});

  useEffect(() => {
    if (!open) return undefined;
    setSection('password');
    setCurrent('');
    setNext('');
    setConfirm('');
    setBusy(false);
    setError('');
    setFieldErrors({});
    const onKey = (e) => {
      if (e.key === 'Escape' && !busy) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  const submit = async (e) => {
    if (e) e.preventDefault();
    if (busy) return;

    const problems = {};
    if (!current) problems.current = 'Enter your current password.';
    const weak = passwordProblem(next);
    if (weak) problems.next = weak;
    if (next && !weak && next === current) problems.next = 'Choose a password you have not used here before.';
    if (!confirm) problems.confirm = 'Re-type the new password.';
    else if (confirm !== next) problems.confirm = 'The two passwords do not match.';

    setFieldErrors(problems);
    if (Object.keys(problems).length) {
      setError('');
      return;
    }

    setError('');
    setBusy(true);
    try {
      await changePassword({ currentPassword: current, newPassword: next });
      onPasswordChanged();
    } catch (err) {
      setBusy(false);
      setError(err.message || 'Could not change your password.');
    }
  };

  const active = SECTIONS.find((item) => item.key === section) || SECTIONS[0];
  const HeaderIcon = active.key === 'themes' ? Palette : ShieldCheck;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label="Settings">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={busy ? undefined : onClose} />
      <div className="relative flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl animate-fade-up">
        <header className="flex items-start gap-3 border-b border-slate-100 px-6 py-5 shrink-0">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-green-50 text-green-600 shrink-0">
            <HeaderIcon className="w-5 h-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-[16px] font-semibold leading-snug text-slate-900">Settings</h3>
            <p className="mt-0.5 text-[12px] text-slate-500">{active.hint}</p>
          </div>
          <button
            onClick={onClose}
            disabled={busy}
            aria-label="Close settings"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
          {section === 'themes' ? (
            <div className="scrollbar-light order-2 min-h-0 flex-1 overflow-y-auto px-6 py-5 sm:order-1">
              <ThemesPane />
            </div>
          ) : (
            <form className="scrollbar-light order-2 min-h-0 flex-1 overflow-y-auto px-6 py-5 sm:order-1" onSubmit={submit}>
            <div className="space-y-4">
              <PasswordField
                label="Current password"
                value={current}
                onChange={(value) => { setCurrent(value); setError(''); }}
                autoComplete="current-password"
                placeholder="••••••••"
                error={fieldErrors.current}
              />
              <PasswordField
                label="New password"
                value={next}
                onChange={(value) => { setNext(value); setError(''); }}
                autoComplete="new-password"
                placeholder="At least 8 characters"
                error={fieldErrors.next}
              />
              <PasswordField
                label="Confirm new password"
                value={confirm}
                onChange={(value) => { setConfirm(value); setError(''); }}
                onKeyDown={(e) => { if (e.key === 'Enter') submit(e); }}
                autoComplete="new-password"
                placeholder="Re-type the new password"
                error={fieldErrors.confirm}
              />
            </div>

            <p className="mt-4 text-[12px] leading-relaxed text-slate-500">
              Use at least {MIN_LENGTH} characters with one letter, one number and one special
              character. For your protection the password is stored as an Argon2id hash — the server
              never keeps it in plain text.
            </p>

            {error && (
              <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[13px] text-rose-700">
                {error}
              </div>
            )}

            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-[12px] leading-relaxed text-amber-800">
              Changing your password signs every device out of this account. You will return to the sign-in page.
            </div>

            <div className="mt-5 flex gap-2.5">
              <button
                type="button"
                onClick={onClose}
                disabled={busy}
                className="flex-1 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[13px] font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={busy}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-green-600 px-3.5 py-2 text-[13px] font-medium text-white shadow-sm transition-colors hover:bg-green-700 disabled:opacity-60"
              >
                {busy ? (<><Loader2 className="w-4 h-4 animate-spin" /> Updating…</>) : 'Update password'}
              </button>
            </div>
            </form>
          )}

          <nav
            aria-label="Settings sections"
            className="scrollbar-light order-1 flex shrink-0 gap-1 overflow-x-auto border-b border-slate-100 bg-slate-50/60 p-2 sm:order-2 sm:w-[184px] sm:flex-col sm:overflow-y-auto sm:border-b-0 sm:border-l sm:p-3"
          >
            {SECTIONS.map((item) => {
              const selected = item.key === section;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setSection(item.key)}
                  aria-current={selected ? 'true' : undefined}
                  className={`flex shrink-0 items-center gap-2.5 whitespace-nowrap rounded-lg border px-3 py-2 text-left text-[13px] font-medium transition-colors sm:w-full
                    ${selected
                      ? 'border-slate-200 bg-white text-green-700 shadow-sm'
                      : 'border-transparent text-slate-600 hover:bg-white hover:text-slate-900'}`}
                >
                  <item.icon className={`w-3.5 h-3.5 shrink-0 ${selected ? 'text-green-600' : 'text-slate-400'}`} />
                  {item.label}
                </button>
              );
            })}
          </nav>
        </div>
      </div>
    </div>
  );
}
