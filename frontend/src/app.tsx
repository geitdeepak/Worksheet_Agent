import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, setToken, setUnauthorizedHandler } from './api';
import { AppShell, Banner, Button, Icon } from './components/ds';

export interface User { id: number; email: string; name: string; role: 'admin' | 'teacher'; class_access: number[] }
export interface ClassRef { id: number; name: string }

/* ------------------------------------------------------------------ auth */
const AuthCtx = createContext<{ user: User | null; setUser: (u: User | null) => void; logout: () => void }>(null!);
export const useAuth = () => useContext(AuthCtx);
export const useIsAdmin = () => useAuth().user?.role === 'admin';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const logout = useCallback(() => { setToken(null); setUser(null); }, []);
  useEffect(() => {
    setUnauthorizedHandler(logout);
    api.get<User>('/api/auth/me').then(setUser).catch(() => setUser(null)).finally(() => setReady(true));
  }, [logout]);
  if (!ready) return null;
  return <AuthCtx.Provider value={{ user, setUser, logout }}>{children}</AuthCtx.Provider>;
}

/* ---------------------------------------------------------------- toasts */
type Toast = { id: number; tone: 'success' | 'danger' | 'info' | 'warning'; text: string };
const ToastCtx = createContext<(tone: Toast['tone'], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((tone: Toast['tone'], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, tone, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'danger' ? 9000 : 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className="toast"><Banner tone={t.tone}>{t.text}</Banner></div>)}
      </div>
    </ToastCtx.Provider>
  );
}

/* --------------------------------------------------------------- loading */
export function useLoad<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try { setData(await api.get<T>(path)); setError(null); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }, [path]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, [reload, ...deps]);
  return { data, setData, error, loading, reload };
}

/** Run an action with a busy flag and toast on failure. Returns the result or undefined. */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>, success?: string): Promise<T | undefined> => {
    setBusy(key);
    try {
      const r = await fn();
      if (success) toast('success', success);
      return r;
    } catch (e) {
      toast('danger', (e as Error).message);
      return undefined;
    } finally { setBusy(null); }
  }, [toast]);
  return { busy, run };
}

/* ---------------------------------------------------------------- dialog */
export function Dialog({ title, onClose, children, footer, wide }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={'dialog' + (wide ? ' wide' : '')} role="dialog" aria-modal="true" aria-label={title}>
        <div className="dialog-head"><h2>{title}</h2><Button variant="quiet" size="sm" onClick={onClose} aria-label="Close">Close</Button></div>
        <div className="dialog-body">{children}</div>
        {footer ? <div className="dialog-foot">{footer}</div> : null}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- theme */
function useTheme() {
  const [theme, setTheme] = useState(() => document.documentElement.getAttribute('data-theme') || 'light');
  const toggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('psa-theme', next); } catch { /* ignore */ }
    setTheme(next);
  };
  return { theme, toggle };
}

/* ---------------------------------------------------------------- layout */
const ClassesCtx = createContext<{ classes: ClassRef[]; refresh: () => void }>({ classes: [], refresh: () => {} });
export const useClassList = () => useContext(ClassesCtx);

export function ClassesProvider({ children }: { children: ReactNode }) {
  const [classes, setClasses] = useState<ClassRef[]>([]);
  const refresh = useCallback(() => { api.get<ClassRef[]>('/api/classes').then(setClasses).catch(() => {}); }, []);
  useEffect(() => { refresh(); }, [refresh]);
  return <ClassesCtx.Provider value={{ classes, refresh }}>{children}</ClassesCtx.Provider>;
}

function initials(name?: string) {
  const parts = (name || '?').trim().split(/\s+/);
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase() || '?';
}

/** Profile button in the top bar: shows who is signed in, with Settings and Sign out. */
function UserMenu() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [open]);
  const role = user?.role === 'admin' ? 'Administrator' : 'Teacher';
  return (
    <div className="user-menu" ref={ref}>
      <button type="button" className="user-button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}
        title={`${user?.name} · ${role}`}>
        <span className="user-avatar">{initials(user?.name)}</span>
        <span className="user-name">{user?.name?.split(' ')[0]}</span>
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
      </button>
      {open ? (
        <div className="user-dropdown" role="menu">
          <div className="user-dropdown-head">
            <span className="user-avatar lg">{initials(user?.name)}</span>
            <div><b>{user?.name}</b><div className="muted-sm">{user?.email}</div><div className="muted-sm">{role}</div></div>
          </div>
          {user?.role === 'admin' ? (
            <button type="button" role="menuitem" onClick={() => { setOpen(false); nav('/settings'); }}><Icon name="settings" />Settings</button>
          ) : null}
          <button type="button" role="menuitem" className="is-danger" onClick={() => { logout(); nav('/login'); }}><Icon name="logout" />Sign out</button>
        </div>
      ) : null}
    </div>
  );
}

export function Layout(props: { active: string; title: ReactNode; crumb?: ReactNode; actions?: ReactNode; activeClass?: number; children: ReactNode }) {
  const { user } = useAuth();
  const { classes } = useClassList();
  const { theme, toggle } = useTheme();
  const nav = useNavigate();
  return (
    <AppShell {...props} classes={classes}
      actions={<>
        {props.actions}
        <span className="top-divider" aria-hidden="true" />
        <button type="button" className="theme-toggle" onClick={toggle}
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={18} />
        </button>
        {user?.role === 'admin' ? (
          <button type="button" className="theme-toggle" onClick={() => nav('/settings')} aria-label="Settings" title="Settings">
            <Icon name="settings" size={18} />
          </button>
        ) : null}
        <UserMenu />
      </>} />
  );
}

export function LoadState({ error, loading }: { error: string | null; loading: boolean }) {
  if (error) return <Banner tone="danger" title="This page could not be loaded">{error}</Banner>;
  if (loading) return <div className="muted-sm row"><Icon name="refresh" /> Loading…</div>;
  return null;
}
