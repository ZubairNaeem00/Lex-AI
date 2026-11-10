import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { checkEmail, signup } from '../api/client';

const ROLES = [
  { label: 'Advocate / Lawyer', desc: 'Practice in courts of law' },
  { label: 'Legal Researcher', desc: 'Research & case analysis' },
  { label: 'Law Student', desc: 'Learning the ropes' },
  { label: 'Judiciary Official', desc: 'Bench & court staff' },
  { label: 'Law Firm', desc: 'Firm-wide workspace' },
];

/* Mirrors validate_password_strength in db/schemas.py, so step 1 never passes a
   password the server would reject at the end of step 3. */
const PASSWORD_RULES = [
  { label: 'At least 8 characters', test: (v) => v.length >= 8 },
  { label: 'One letter', test: (v) => /[A-Za-z]/.test(v) },
  { label: 'One number', test: (v) => /\d/.test(v) },
  { label: 'One special character (! @ # $ %)', test: (v) => /[^A-Za-z0-9\s]/.test(v) },
];

/* ── Presentational helpers (UI only, matches ChatPage / ReportsPage) ── */
const Icon = ({ d, className = 'w-4 h-4' }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {[].concat(d).map((p, i) => <path key={i} d={p} />)}
  </svg>
);

const I = {
  back: ['M19 12H5', 'M12 19l-7-7 7-7'],
  user: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6'],
  mail: ['M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z', 'M22 6l-10 7L2 6'],
  lock: ['M5 11h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z', 'M7 11V7a5 5 0 0 1 10 0v4'],
  check: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M8 12l3 3 5-6'],
  circle: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z'],
  scale: ['M12 3v18', 'M5 21h14', 'M12 6h-5l-3 6a3.5 3.5 0 0 0 6 0l-3-6', 'M17 6h5l-3 6a3.5 3.5 0 0 0 6 0l-3-6', 'M7 6h10'],
  shield: ['M12 22s8-3.5 8-10V5l-8-3-8 3v7c0 6.5 8 10 8 10z', 'M9 12l2 2 4-4'],
};

const BentoCard = ({ children, className = '', style }) => (
  <div style={style} className={`rounded-2xl border border-slate-200 bg-white shadow-sm transition-all duration-200 hover:shadow-md ${className}`}>
    {children}
  </div>
);

const Field = ({ label, type = 'text', placeholder, icon, value, onChange }) => (
  <label className="block mb-4">
    <span className="mb-1.5 block text-xs font-medium text-slate-500">{label}</span>
    <span className="relative block">
      <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400">
        <Icon d={icon} className="w-4 h-4" />
      </span>
      <input
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        className="w-full rounded-xl border border-slate-200 bg-slate-50/50 py-2.5 pl-10 pr-4 text-sm text-slate-900 placeholder:text-slate-400 shadow-sm outline-none transition-all duration-200 focus:border-green-400 focus:bg-white focus:ring-4 focus:ring-green-100"
      />
    </span>
  </label>
);

const PasswordRules = ({ value }) => (
  <ul className="-mt-1 mb-4 grid grid-cols-1 gap-x-3 gap-y-1.5 sm:grid-cols-2">
    {PASSWORD_RULES.map(rule => {
      const met = rule.test(value);
      return (
        <li key={rule.label} className={`flex items-center gap-1.5 text-[11px] transition-colors duration-200 ${met ? 'text-green-700' : 'text-slate-500'}`}>
          <Icon d={met ? I.check : I.circle} className={`w-3.5 h-3.5 shrink-0 ${met ? 'text-green-600' : 'text-slate-300'}`} />
          {rule.label}
        </li>
      );
    })}
  </ul>
);

const StepDots = ({ step }) => (
  <div className="flex gap-2 mb-8">
    {[1, 2, 3].map(s => (
      <div
        key={s}
        className={`h-1 flex-1 rounded-full transition-all duration-500 ${
          s <= step ? 'bg-green-600' : 'bg-slate-200'
        }`}
      />
    ))}
  </div>
);

export default function SignupPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState({ name: '', email: '', password: '', role: '' });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const set = (field) => (e) => {
    setForm(f => ({ ...f, [field]: e.target.value }));
    setError('');
  };

  const submitAccount = async () => {
    setError('');
    setSaving(true);
    try {
      await signup({
        fullName: form.name.trim(),
        email: form.email.trim(),
        password: form.password,
        role: form.role,
      });
      setSaving(false);
      navigate('/chat');
    } catch (err) {
      setSaving(false);
      /* Someone claimed the address while the visitor finished the last steps. */
      if (err.status === 409) setStep(1);
      setError(err.message || 'Could not create the account. Please try again.');
    }
  };

  const goPastDetails = async () => {
    if (saving) return;
    if (form.name.trim().length < 2) return setError('Please enter your full name.');
    const email = form.email.trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return setError('Please enter a valid email address.');
    if (form.password.length > 128) return setError('Password must be at most 128 characters long.');
    const unmet = PASSWORD_RULES.find(rule => !rule.test(form.password));
    if (unmet) return setError(`Password needs ${unmet.label.toLowerCase()}.`);

    setError('');
    setSaving(true);
    try {
      const { available } = await checkEmail(email);
      setSaving(false);
      if (!available) {
        return setError('An account with this email already exists. Sign in below, or use a different address.');
      }
      setStep(2);
    } catch {
      /* The probe is advisory — if it cannot run, register still refuses duplicates. */
      setSaving(false);
      setStep(2);
    }
  };

  const goPastRole = () => {
    if (!form.role) return setError('Please choose the role that fits you best.');
    setError('');
    setStep(3);
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6 md:p-8 relative overflow-hidden bg-slate-50 text-slate-800 antialiased">
      {/* Ambient — same feel as the app, in green */}
      <div className="pointer-events-none absolute inset-0"
           style={{ background: 'radial-gradient(ellipse at 60% 40%, rgba(22,163,74,.06), transparent 70%)' }} />
      <div className="pointer-events-none absolute inset-0"
           style={{
             backgroundImage:
               'linear-gradient(rgba(15,23,42,.035) 1px, transparent 1px), linear-gradient(90deg, rgba(15,23,42,.035) 1px, transparent 1px)',
             backgroundSize: '44px 44px',
             maskImage: 'radial-gradient(ellipse at center, black 20%, transparent 75%)',
             WebkitMaskImage: 'radial-gradient(ellipse at center, black 20%, transparent 75%)',
           }} />
      <div className="pointer-events-none absolute -top-32 left-1/2 -translate-x-1/2 w-[560px] h-[280px] rounded-full bg-green-500/10 blur-[120px]" />

      <div className="w-full max-w-md relative">

        {/* Back to home */}
        <button onClick={() => navigate('/')} className="flex items-center gap-2.5 mb-8 group">
          <div className="w-7 h-7 rounded-lg bg-green-600 text-white flex items-center justify-center text-xs font-bold transition-all duration-200 group-hover:shadow-md group-hover:scale-105">L</div>
          <span className="text-[15px] font-semibold tracking-tight text-slate-900">LexAI</span>
          <span className="text-[10px] font-medium text-green-600 bg-green-50 border border-green-100 rounded-md px-1.5 py-0.5">Beta</span>
        </button>

        <BentoCard className="relative">
          <div className="p-8">
            <StepDots step={step} />

            {error && (
              <div className="mb-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}

            <div className="mb-7">
              <p className="text-[11px] text-green-600 tracking-widest uppercase font-medium mb-2">
                Step {step} of 3
              </p>
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900 mb-1.5">
                {step === 1 && 'Create your account'}
                {step === 2 && 'Your role'}
                {step === 3 && 'Almost there'}
              </h2>
              <p className="text-slate-500 text-sm">
                {step === 1 && 'Join legal professionals across Pakistan using LexAI.'}
                {step === 2 && 'Help us personalize your experience.'}
                {step === 3 && 'Your details are stored in the LegalLens database.'}
              </p>
            </div>

            {/* Step 1 — Account details */}
            {step === 1 && (
              <div>
                <Field label="Full Name"     placeholder="Your full name"    icon={I.user}  value={form.name}     onChange={set('name')} />
                <Field label="Email Address" type="email" placeholder="your@email.com" icon={I.mail} value={form.email} onChange={set('email')} />
                <Field label="Password"      type="password" placeholder="Strong password" icon={I.lock} value={form.password} onChange={set('password')} />
                <PasswordRules value={form.password} />
                <button
                  onClick={goPastDetails}
                  disabled={saving}
                  className="w-full mt-2 rounded-xl bg-green-600 text-white text-sm font-medium py-2.5 shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-70"
                >
                  {saving ? 'Checking your details…' : 'Continue →'}
                </button>
              </div>
            )}

            {/* Step 2 — Role selection */}
            {step === 2 && (
              <div>
                <div className="flex flex-col gap-2.5 mb-6">
                  {ROLES.map(r => (
                    <button
                      key={r.label}
                      onClick={() => setForm(f => ({ ...f, role: r.label }))}
                      className={`
                        text-left px-4 py-3 rounded-xl border text-sm transition-all duration-200 hover:-translate-y-px
                        ${form.role === r.label
                          ? 'bg-green-50 border-green-400 shadow-sm'
                          : 'bg-white border-slate-200 hover:border-slate-300 hover:shadow-sm'}
                      `}
                    >
                      <span className={`flex items-center justify-between gap-2 font-medium ${form.role === r.label ? 'text-green-700' : 'text-slate-800'}`}>
                        {r.label}
                        {form.role === r.label && <Icon d={I.check} className="w-4 h-4 text-green-600" />}
                      </span>
                      <span className={`mt-0.5 block text-xs ${form.role === r.label ? 'text-green-600/80' : 'text-slate-500'}`}>{r.desc}</span>
                    </button>
                  ))}
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={() => { setError(''); setStep(1); }}
                    className="flex-1 inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition-all duration-200 hover:border-slate-300 hover:shadow-md"
                  >
                    <Icon d={I.back} className="w-4 h-4" />Back
                  </button>
                  <button
                    onClick={goPastRole}
                    className="flex-[2] rounded-xl bg-green-600 text-white text-sm font-medium py-2.5 shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98]"
                  >
                    Continue →
                  </button>
                </div>
              </div>
            )}

            {/* Step 3 — Success */}
            {step === 3 && (
              <div className="text-center py-4">
                <div className="relative inline-block mb-5">
                  <div className="absolute inset-0 rounded-full bg-green-500/20 blur-xl" />
                  <div className="relative w-14 h-14 mx-auto rounded-2xl bg-green-50 border border-green-100 text-green-600 flex items-center justify-center">
                    <Icon d={I.scale} className="w-7 h-7" />
                  </div>
                </div>
                <p className="text-slate-500 text-sm leading-relaxed mb-8">
                  Welcome, <strong className="text-slate-900">{form.name || 'Counsellor'}</strong>!<br />
                  We'll create your account and open your first case.
                </p>
                <button
                  onClick={submitAccount}
                  disabled={saving}
                  className="w-full rounded-xl bg-green-600 text-white text-sm font-medium py-2.5 shadow-sm transition-all duration-200 hover:bg-green-700 hover:shadow-md active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-70"
                >
                  {saving ? 'Creating your account…' : 'Go to Chat →'}
                </button>
              </div>
            )}
          </div>
        </BentoCard>

        <p className="text-center text-slate-500 text-sm mt-5">
          Already have an account?{' '}
          <Link to="/login" className="text-green-600 hover:text-green-700 font-medium underline underline-offset-4 decoration-green-200 hover:decoration-green-400 transition-colors">Sign in</Link>
        </p>

        <p className="text-center text-slate-400 text-[11px] mt-4 tracking-wide inline-flex items-center justify-center gap-1.5 w-full">
          <Icon d={I.shield} className="w-3.5 h-3.5" />
          Protected by industry-standard encryption · Pakistani legal data residency
        </p>
      </div>
    </div>
  );
}