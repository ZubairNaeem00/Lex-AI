import React, { useEffect, useState } from 'react';
import { Check, Loader2, Pencil, X } from 'lucide-react';
import { fetchMe, updateProfile } from '../../api/client';

const PROFILE_KEYS = ['occupation', 'organisation', 'bar_registration', 'jurisdiction', 'phone', 'address'];

const EMPTY_FORM = {
  full_name: '',
  occupation: '',
  organisation: '',
  bar_registration: '',
  jurisdiction: '',
  phone: '',
  address: '',
};

function toForm(account) {
  const profile = (account && account.profile) || {};
  return {
    full_name: (account && account.full_name) || '',
    occupation: profile.occupation || '',
    organisation: profile.organisation || '',
    bar_registration: profile.bar_registration || '',
    jurisdiction: profile.jurisdiction || '',
    phone: profile.phone || '',
    address: profile.address || '',
  };
}

function usernameFromEmail(email) {
  return email ? String(email).split('@')[0] : '';
}

function fmtDate(value, withTime = false) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const day = date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  if (!withTime) return day;
  return `${day}, ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

const STATUS_LABEL = {
  active: 'Active',
  pending: 'Pending verification',
  disabled: 'Disabled',
};

const InfoRow = ({ label, value }) => (
  <div className="flex items-start justify-between gap-4 border-b border-slate-100 py-2.5 last:border-0">
    <span className="text-[13px] text-slate-500">{label}</span>
    <span className="min-w-0 max-w-[62%] break-words text-right text-[13px] font-medium text-slate-900">
      {value || '—'}
    </span>
  </div>
);

const EditField = ({ label, value, onChange, type = 'text', placeholder, textarea }) => {
  const shared = {
    id: `profile-${label.replace(/\s+/g, '-').toLowerCase()}`,
    value,
    onChange: (e) => onChange(e.target.value),
    placeholder,
    className:
      'w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[13px] text-slate-800 ' +
      'placeholder:text-slate-400 shadow-sm outline-none transition-all duration-200 ' +
      'hover:border-slate-300 focus:border-green-500 focus:ring-4 focus:ring-green-100',
  };
  return (
    <label className="block">
      <span className="mb-1.5 block text-[12px] font-medium text-slate-600">{label}</span>
      {textarea ? <textarea {...shared} rows={2} /> : <input {...shared} type={type} />}
    </label>
  );
};

export default function ProfileModal({ open, onClose, onSaved }) {
  const [account, setAccount] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;
    setLoading(true);
    setEditing(false);
    setError('');
    setSaved(false);
    fetchMe()
      .then((me) => {
        if (cancelled) return;
        setAccount(me);
        setForm(toForm(me));
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message || 'Could not load your profile.');
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape' && !saving) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, saving, onClose]);

  if (!open) return null;

  const setField = (key) => (value) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setError('');
    setSaved(false);
  };

  const cancelEdit = () => {
    setForm(toForm(account));
    setEditing(false);
    setError('');
  };

  const handleSave = async () => {
    const fullName = form.full_name.trim();
    if (fullName.length < 2) {
      setError('Please enter your full name.');
      return;
    }
    if (/^\d/.test(fullName)) {
      setError('Full name must not start with a digit.');
      return;
    }
    const profile = {};
    PROFILE_KEYS.forEach((key) => {
      profile[key] = (form[key] || '').trim();
    });

    setError('');
    setSaving(true);
    try {
      const updated = await updateProfile({ fullName, profile });
      setAccount(updated);
      setForm(toForm(updated));
      setEditing(false);
      setSaved(true);
      if (onSaved) onSaved(updated);
    } catch (err) {
      setError(err.message || 'Could not save your profile.');
    } finally {
      setSaving(false);
    }
  };

  const profileOfAccount = (account && account.profile) || {};

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label="Profile">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <div className="relative flex max-h-[88vh] w-full max-w-lg flex-col rounded-2xl border border-slate-200 bg-white shadow-xl animate-fade-up">
        <header className="flex items-start gap-3 border-b border-slate-100 px-6 py-5 shrink-0">
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-green-600 text-sm font-bold text-white shrink-0">
            {(account && account.full_name ? account.full_name : 'L')
              .split(' ')
              .filter(Boolean)
              .slice(0, 2)
              .map((part) => part[0].toUpperCase())
              .join('') || 'L'}
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-[16px] font-semibold leading-snug text-slate-900">Profile</h3>
            <p className="mt-0.5 truncate text-[12px] text-slate-500">
              {loading ? 'Loading your account…' : (account && account.email) || ''}
            </p>
          </div>
          <button
            onClick={onClose}
            disabled={saving}
            aria-label="Close profile"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {loading && (
            <div className="flex items-center gap-2 py-8 text-[13px] text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading…
            </div>
          )}

          {!loading && account && !editing && (
            <>
              <p className="mb-2 text-[11px] font-medium uppercase tracking-[1.4px] text-slate-400">Account</p>
              <InfoRow label="Name" value={account.full_name} />
              <InfoRow label="Username" value={usernameFromEmail(account.email)} />
              <InfoRow label="Email" value={account.email} />
              <InfoRow label="Role" value={profileOfAccount.occupation} />

              <p className="mt-6 mb-2 text-[11px] font-medium uppercase tracking-[1.4px] text-slate-400">Practice details</p>
              <InfoRow label="Organisation" value={profileOfAccount.organisation} />
              <InfoRow label="Bar registration" value={profileOfAccount.bar_registration} />
              <InfoRow label="Jurisdiction" value={profileOfAccount.jurisdiction} />
              <InfoRow label="Phone" value={profileOfAccount.phone} />
              <InfoRow label="Address" value={profileOfAccount.address} />

              <p className="mt-6 mb-2 text-[11px] font-medium uppercase tracking-[1.4px] text-slate-400">Membership</p>
              <InfoRow label="Status" value={STATUS_LABEL[account.status] || account.status} />
              <InfoRow label="Email verified" value={account.email_verified ? 'Yes' : 'Not yet'} />
              <InfoRow label="Member since" value={fmtDate(account.created_at)} />
              <InfoRow label="Last sign-in" value={fmtDate(account.last_login_at, true)} />
            </>
          )}

          {!loading && account && editing && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <EditField label="Full name" value={form.full_name} onChange={setField('full_name')} placeholder="Adv. Ali Raza" />
              </div>
              <EditField label="Role" value={form.occupation} onChange={setField('occupation')} placeholder="Advocate" />
              <EditField label="Jurisdiction" value={form.jurisdiction} onChange={setField('jurisdiction')} placeholder="Lahore High Court" />
              <EditField label="Organisation" value={form.organisation} onChange={setField('organisation')} placeholder="Chamber name" />
              <EditField label="Bar registration" value={form.bar_registration} onChange={setField('bar_registration')} placeholder="PHSA-12345" />
              <EditField label="Phone" value={form.phone} onChange={setField('phone')} placeholder="+92 300 1234567" />
              <EditField label="Address" value={form.address} onChange={setField('address')} placeholder="Court Road, Lahore" />
              <div className="sm:col-span-2 rounded-xl border border-slate-100 bg-slate-50 px-3.5 py-2.5">
                <p className="text-[12px] text-slate-500">
                  Email and username are tied to your sign-in and cannot be changed here.
                </p>
              </div>
            </div>
          )}

          {error && (
            <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-[13px] text-rose-700">
              {error}
            </div>
          )}
          {saved && !editing && (
            <div className="mt-4 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-[13px] text-emerald-700">
              <Check className="w-4 h-4" /> Profile saved.
            </div>
          )}
        </div>

        <footer className="flex shrink-0 gap-2.5 border-t border-slate-100 px-6 py-4">
          {editing ? (
            <>
              <button
                onClick={cancelEdit}
                disabled={saving}
                className="flex-1 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[13px] font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex-1 rounded-xl bg-green-600 px-3.5 py-2 text-[13px] font-medium text-white shadow-sm transition-colors hover:bg-green-700 disabled:opacity-60"
              >
                {saving ? 'Saving…' : 'Save changes'}
              </button>
            </>
          ) : (
            <>
              <button
                onClick={onClose}
                className="flex-1 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[13px] font-medium text-slate-700 transition-colors hover:bg-slate-50"
              >
                Close
              </button>
              <button
                onClick={() => { setSaved(false); setEditing(true); }}
                disabled={loading}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-green-600 px-3.5 py-2 text-[13px] font-medium text-white shadow-sm transition-colors hover:bg-green-700 disabled:opacity-60"
              >
                <Pencil className="w-3.5 h-3.5" /> Edit profile
              </button>
            </>
          )}
        </footer>
      </div>
    </div>
  );
}
