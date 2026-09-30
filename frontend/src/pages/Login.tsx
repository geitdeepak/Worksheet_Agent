import { useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { api, setToken } from '../api';
import { useAuth, type User } from '../app';
import { Banner, Button, classTone } from '../components/ds';

export default function Login() {
  const { user, setUser } = useAuth();
  const nav = useNavigate();
  const loc = useLocation() as { state?: { from?: string } };
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={loc.state?.from || '/'} replace />;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ token: string; user: User }>('/api/auth/login', { email, password });
      setToken(r.token);
      setUser(r.user);
      nav(loc.state?.from || '/', { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally { setBusy(false); }
  }

  return (
    <div className="login">
      <div className="login-hero">
        <div style={{ fontWeight: 700, fontSize: 15 }}>Practice Sheet Agent</div>
        <div>
          <h2>Practice sheets that arrive two days before every exam.</h2>
          <p>Configure each class once. The platform finds upcoming exams, builds worksheets from your own syllabus and
            study material, and delivers them to the right students.</p>
          <div className="login-dots" aria-hidden="true">
            {['6', '7', '8', '9', '10', '11', '12'].map((n) => <span key={n} style={classTone(`Class ${n}`)}>{n}</span>)}
          </div>
        </div>
        <div style={{ fontSize: 13, opacity: 0.75 }}>Phase 1 · Email delivery · Phase 2 · Email and WhatsApp</div>
      </div>
      <div className="login-form-wrap">
        <form className="psa-card login-form" onSubmit={submit}>
          <div>
            <div style={{ fontSize: 24, lineHeight: '32px', fontWeight: 700, color: 'var(--navy)' }}>Sign in</div>
            <div className="muted-sm">Administrators and teachers</div>
          </div>
          {error ? <Banner tone="danger">{error}</Banner> : null}
          <label className="field"><span>Email</span>
            <input className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="field"><span>Password</span>
            <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <Button variant="primary" type="submit" disabled={busy} style={{ justifyContent: 'center' }}>{busy ? 'Signing in…' : 'Sign in'}</Button>
          <div className="muted-sm" style={{ textAlign: 'center' }}>Forgot your password? Ask an administrator to reset it.</div>
        </form>
      </div>
    </div>
  );
}
