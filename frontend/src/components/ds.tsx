/* Practice Sheet Agent design system — typed port of components/bundle.js. Prop names follow index.d.ts. */
import { useState, type ButtonHTMLAttributes, type CSSProperties, type ReactNode } from 'react';
import { NavLink } from 'react-router-dom';

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ');

export type IconName = 'dashboard' | 'classes' | 'calendar' | 'book' | 'users' | 'sliders' | 'bolt' | 'review' | 'send'
  | 'history' | 'upload' | 'file' | 'sheet' | 'mail' | 'chat' | 'check' | 'alert' | 'info' | 'arrow' | 'refresh' | 'plus'
  | 'pause' | 'logout' | 'settings' | 'trash' | 'edit' | 'download' | 'moon' | 'sun' | 'scope' | 'menu' | 'close';
export type Status = 'draft' | 'active' | 'paused' | 'pending' | 'running' | 'validation-failed' | 'awaiting-approval'
  | 'released' | 'completed' | 'failed' | 'cancelled' | 'queued' | 'sending' | 'sent' | 'delivered' | 'retrying' | 'skipped'
  | 'superseded' | 'generating';
export type Tone = 'info' | 'success' | 'warning' | 'danger';

/* ---- Icon: stroke icons on a 24 grid ---- */
const PATHS: Record<IconName, string[]> = {
  dashboard: ['M4 4h7v7H4z', 'M13 4h7v4h-7z', 'M13 10h7v10h-7z', 'M4 13h7v7H4z'],
  classes: ['M3 8l9-4 9 4-9 4z', 'M7 10v5c0 1.5 2.2 3 5 3s5-1.5 5-3v-5'],
  calendar: ['M4 6h16v14H4z', 'M4 10h16', 'M8 3v4', 'M16 3v4'],
  book: ['M5 4h9a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z', 'M5 17a3 3 0 0 1 3-3h9'],
  users: ['M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z', 'M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6', 'M16 4.5a3.5 3.5 0 0 1 0 6.5', 'M18 14c1.8.8 3 2.9 3 6'],
  sliders: ['M4 7h10', 'M18 7h2', 'M4 17h4', 'M12 17h8', 'M16 5v4', 'M10 15v4'],
  bolt: ['M13 3L5 14h6l-1 7 8-11h-6z'],
  review: ['M5 4h10l4 4v12H5z', 'M9 13l2 2 4-4'],
  send: ['M4 12l16-8-6 16-3-7z', 'M11 13l9-9'],
  history: ['M4 12a8 8 0 1 0 2.3-5.7', 'M4 4v4h4', 'M12 8v4l3 2'],
  upload: ['M12 16V4', 'M7 9l5-5 5 5', 'M4 16v4h16v-4'],
  file: ['M6 3h8l4 4v14H6z', 'M14 3v4h4'],
  sheet: ['M5 3h14v18H5z', 'M5 9h14', 'M5 15h14', 'M11 3v18'],
  mail: ['M3 6h18v12H3z', 'M3 7l9 6 9-6'],
  chat: ['M4 5h16v11H9l-5 4z', 'M8 10h8'],
  check: ['M5 12l4 4 10-10'],
  alert: ['M12 4l9 16H3z', 'M12 10v4', 'M12 17v.5'],
  info: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 11v5', 'M12 8v.5'],
  arrow: ['M5 12h14', 'M13 6l6 6-6 6'],
  refresh: ['M20 11a8 8 0 0 0-14.9-3', 'M4 13a8 8 0 0 0 14.9 3', 'M4 4v4h4', 'M20 20v-4h-4'],
  plus: ['M12 5v14', 'M5 12h14'],
  pause: ['M8 5v14', 'M16 5v14'],
  logout: ['M15 4h4v16h-4', 'M10 8l-4 4 4 4', 'M6 12h10'],
  // Cog wheel (distinct from the sun icon): toothed outline + centre hole.
  settings: ['M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z',
    'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z'],
  trash: ['M4 7h16', 'M9 7V4h6v3', 'M6 7l1 13h10l1-13'],
  edit: ['M4 20h4L19 9l-4-4L4 16z', 'M13 7l4 4'],
  download: ['M12 4v12', 'M7 11l5 5 5-5', 'M4 20h16'],
  moon: ['M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z'],
  sun: ['M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M12 2v2', 'M12 20v2', 'M2 12h2', 'M20 12h2', 'M5 5l1.4 1.4', 'M17.6 17.6L19 19', 'M5 19l1.4-1.4', 'M17.6 6.4L19 5'],
  scope: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M12 12h.01'],
  menu: ['M4 7h16', 'M4 12h16', 'M4 17h16'],
  close: ['M6 6l12 12', 'M18 6L6 18'],
};

export function Icon({ name, size, label, className }: { name: IconName; size?: number; label?: string; className?: string }) {
  const d = PATHS[name] || PATHS.info;
  return (
    <svg className={cx('psa-icon', className)} viewBox="0 0 24 24" aria-hidden={label ? undefined : true}
      role={label ? 'img' : undefined} aria-label={label} style={size ? { width: size, height: size } : undefined}>
      {d.map((s, i) => <path key={i} d={s} />)}
    </svg>
  );
}

/* ---- Button ---- */
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'quiet' | 'danger'; size?: 'md' | 'sm'; icon?: IconName; children?: ReactNode;
};
export function Button({ variant = 'secondary', size = 'md', icon, className, children, type = 'button', ...rest }: ButtonProps) {
  return (
    <button type={type} {...rest} className={cx('psa-btn', 'psa-btn-' + variant, size === 'sm' && 'psa-btn-sm', className)}>
      {icon ? <Icon name={icon} /> : null}{children}
    </button>
  );
}

/* ---- StatusBadge: every state = word + shape + colour ---- */
type Glyph = 'ring' | 'dash' | 'half' | 'diamond' | 'pause' | 'triangle' | 'dot';
const STATUS: Record<string, [string, string, Glyph]> = {
  draft: ['neutral', 'Draft', 'ring'], pending: ['neutral', 'Pending', 'ring'], queued: ['neutral', 'Queued', 'ring'],
  skipped: ['neutral', 'Skipped', 'dash'], cancelled: ['neutral', 'Cancelled', 'dash'], superseded: ['neutral', 'Superseded', 'dash'],
  running: ['info', 'Running', 'half'], sending: ['info', 'Sending', 'half'], generating: ['info', 'Generating', 'half'],
  'awaiting-approval': ['warning', 'Awaiting approval', 'diamond'], paused: ['warning', 'Paused', 'pause'],
  retrying: ['warning', 'Retrying', 'diamond'], 'validation-failed': ['danger', 'Validation failed', 'triangle'],
  failed: ['danger', 'Failed', 'triangle'], released: ['success', 'Released', 'dot'], completed: ['success', 'Completed', 'dot'],
  sent: ['success', 'Sent', 'dot'], delivered: ['success', 'Delivered', 'dot'], active: ['success', 'Active', 'dot'],
};
function GlyphSvg({ kind }: { kind: Glyph }) {
  const p = { width: 10, height: 10, viewBox: '0 0 10 10', 'aria-hidden': true as const };
  switch (kind) {
    case 'dot': return <svg {...p}><circle cx={5} cy={5} r={4} fill="currentColor" /></svg>;
    case 'ring': return <svg {...p}><circle cx={5} cy={5} r={3.5} fill="none" stroke="currentColor" strokeWidth={1.5} /></svg>;
    case 'half': return <svg {...p}><circle cx={5} cy={5} r={3.5} fill="none" stroke="currentColor" strokeWidth={1.5} /><path d="M5 1.5a3.5 3.5 0 0 1 0 7z" fill="currentColor" /></svg>;
    case 'diamond': return <svg {...p}><path d="M5 0.5L9.5 5 5 9.5 0.5 5z" fill="currentColor" /></svg>;
    case 'triangle': return <svg {...p}><path d="M5 0.5L9.8 9.3H0.2z" fill="currentColor" /></svg>;
    case 'pause': return <svg {...p}><rect x={1.5} y={1} width={2.5} height={8} fill="currentColor" /><rect x={6} y={1} width={2.5} height={8} fill="currentColor" /></svg>;
    default: return <svg {...p}><rect x={1} y={4} width={8} height={2} fill="currentColor" /></svg>;
  }
}
export function StatusBadge({ status, children, tone }: { status: Status | string; children?: ReactNode; tone?: Tone | 'neutral' }) {
  const s = STATUS[status] || ['neutral', status || 'Unknown', 'ring'];
  return <span className={cx('psa-badge', 'psa-tone-' + (tone || s[0]))}><GlyphSvg kind={s[2]} />{children ?? s[1]}</span>;
}

/* ---- Card ---- */
export function Card({ title, actions, flush, children, className }: { title?: ReactNode; actions?: ReactNode; flush?: boolean; children?: ReactNode; className?: string }) {
  return (
    <section className={cx('psa-card', className)}>
      {title ? <header className="psa-card-head"><h3>{title}</h3>{actions || null}</header> : null}
      <div className={flush ? undefined : 'psa-card-body'}>{children}</div>
    </section>
  );
}

/* ---- Class colours: every class gets one hue from palette.css, chosen from its class number ---- */
export function classNumber(name: string): string {
  const m = /\d+/.exec(name || '');
  return m ? m[0] : (name || '?').trim().charAt(0).toUpperCase();
}
export function classHue(name: string): number {
  const n = parseInt(classNumber(name), 10);
  if (!Number.isNaN(n)) return ((n - 1) % 8 + 8) % 8 + 1; // Class 9 → 1, Class 10 → 2 …
  let h = 0;
  for (const ch of name || '') h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return (h % 8) + 1;
}
/** CSS variables that point this element (and its children) at the class's colour. */
export function classTone(nameOrHue: string | number): CSSProperties {
  const n = typeof nameOrHue === 'number' ? nameOrHue : classHue(nameOrHue);
  return { ['--c' as string]: `var(--class-${n})`, ['--c-soft' as string]: `var(--class-${n}-soft)`, ['--c2' as string]: `var(--class-${n}-2)` };
}
export function ClassBadge({ name, size = 28 }: { name: string; size?: number }) {
  return <span className="class-badge" style={{ ...classTone(name), width: size, height: size, fontSize: size * 0.44 }} aria-hidden="true">{classNumber(name)}</span>;
}
export function ClassChip({ name, suffix }: { name: string; suffix?: string }) {
  return <span className="class-chip" style={classTone(name)}><span className="class-chip-dot" />{name}{suffix ?? ''}</span>;
}

/* ---- KpiTile ---- */
export function KpiTile({ label, value, tone, note, onClick, icon, hue }: {
  label: string; value: ReactNode; tone?: 'success' | 'warning' | 'danger' | null; note?: string; onClick?: () => void; icon?: IconName; hue?: number;
}) {
  return (
    <button type="button" className={cx('psa-card psa-kpi', hue ? 'is-colored' : null)} onClick={onClick} style={hue ? classTone(hue) : undefined}>
      <span className="kpi-head">
        {icon ? <span className="kpi-icon"><Icon name={icon} /></span> : null}
        <span className="psa-label">{label}</span>
      </span>
      <span className={cx('psa-kpi-value', tone && 'is-' + tone)}>{value}</span>
      {note ? <span className="psa-kpi-note">{note}</span> : null}
    </button>
  );
}

/* ---- ClassCard ---- */
export function ClassCard(p: { name: string; year?: string; sections?: string; students: number; subjects: number; exams: number; automation?: 'draft' | 'active' | 'paused'; nextTrigger?: string | null; onOpen?: () => void }) {
  return (
    <article className="psa-card psa-class psa-clickable class-card" role="link" tabIndex={0} onClick={p.onOpen} style={classTone(p.name)}
      onKeyDown={(e) => { if (e.key === 'Enter') p.onOpen?.(); }}>
      <div className="class-card-head">
        <span className="class-card-num">{classNumber(p.name)}</span>
        <div className="grow">
          <h3 className="class-card-name">{p.name}</h3>
          <div className="class-card-sub">Academic year {p.year || '2026–27'}{p.sections ? ' · Sections ' + p.sections : ''}</div>
        </div>
        <span className="class-card-status"><StatusBadge status={p.automation || 'draft'} /></span>
      </div>
      <div className="class-card-body">
        <div className="class-card-stats">
          <div><b>{p.students}</b><span>Students</span></div>
          <div><b>{p.subjects}</b><span>Subjects</span></div>
          <div><b>{p.exams}</b><span>Exams</span></div>
        </div>
        <div className="class-card-next"><Icon name="calendar" />{p.nextTrigger ? <>Next worksheet <b>{p.nextTrigger}</b></> : 'No upcoming worksheet'}</div>
      </div>
    </article>
  );
}

/* ---- Pipeline: the fixed job flow ---- */
const FLOWS = { review: ['Generate', 'Validate', 'Review', 'Approve', 'Release', 'Share'], auto: ['Generate', 'Validate', 'Auto release', 'Share'] };
export function Pipeline({ mode = 'review', steps, current, failed }: { mode?: 'review' | 'auto'; steps?: string[]; current?: number; failed?: boolean }) {
  const list = steps || FLOWS[mode];
  const cur = current == null ? -1 : current;
  return (
    <div className="psa-pipe" role="list" aria-label="Worksheet workflow">
      {list.map((s, i) => {
        const state = i < cur ? 'done' : i === cur ? (failed ? 'failed' : 'current') : 'todo';
        return (
          <span key={s} style={{ display: 'contents' }}>
            <span role="listitem" className={cx('psa-pipe-step', 'is-' + state)} aria-current={state === 'current' ? 'step' : undefined}>
              {state === 'done' ? <Icon name="check" /> : state === 'failed' ? <Icon name="alert" /> : null}{s}
            </span>
            {i < list.length - 1 ? <span className="psa-pipe-arrow"><Icon name="arrow" /></span> : null}
          </span>
        );
      })}
    </div>
  );
}

/* ---- UploadDropzone (with real file input + drag and drop) ---- */
export function UploadDropzone(p: {
  title: string; hint?: ReactNode; state?: 'empty' | 'parsed' | 'error' | 'pending'; fileName?: string | null; icon?: IconName;
  action?: ReactNode; accept?: string; multiple?: boolean; onFiles?: (files: File[]) => void; busy?: boolean; disabled?: boolean;
}) {
  const state = p.state || 'empty';
  const [over, setOver] = useState(false);
  const inputId = 'up-' + p.title.replace(/\W+/g, '-').toLowerCase();
  const pick = (list: FileList | null) => { if (list && list.length && p.onFiles) p.onFiles(Array.from(list)); };
  return (
    <div className={cx('psa-drop', 'is-' + (state === 'pending' ? 'empty' : state), over && 'is-over')}
      onDragOver={(e) => { if (p.onFiles && !p.disabled) { e.preventDefault(); setOver(true); } }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (!p.disabled) pick(e.dataTransfer.files); }}>
      <div className="psa-drop-icon"><Icon name={state === 'empty' ? 'upload' : state === 'error' ? 'alert' : (p.icon || 'sheet')} size={20} /></div>
      <div className="psa-drop-text">
        <div className="psa-drop-title">{state === 'empty' ? p.title : (p.fileName || p.title)}</div>
        <div className="psa-drop-hint">{p.hint}</div>
      </div>
      {p.action}
      {p.onFiles ? (
        <>
          <input id={inputId} type="file" hidden accept={p.accept} multiple={p.multiple}
            onChange={(e) => { pick(e.target.files); e.target.value = ''; }} />
          <label htmlFor={inputId} className={cx('psa-btn', state === 'empty' ? 'psa-btn-secondary' : 'psa-btn-quiet', 'psa-btn-sm', (p.busy || p.disabled) && 'is-disabled')}
            aria-disabled={p.busy || p.disabled}>
            {state === 'empty' ? <><Icon name="upload" />{p.busy ? 'Uploading…' : 'Choose file'}</> : (p.busy ? 'Uploading…' : 'Replace')}
          </label>
        </>
      ) : null}
    </div>
  );
}

/* ---- ChannelStatus: one row per delivery channel, tracked independently ---- */
export function ChannelStatus({ channel, status, detail, phase }: { channel: 'email' | 'whatsapp'; status: Status | 'off' | string; detail?: ReactNode; phase?: string }) {
  const off = status === 'off';
  return (
    <div className={cx('psa-chan', off && 'is-off')}>
      <div className="psa-chan-icon"><Icon name={channel === 'whatsapp' ? 'chat' : 'mail'} /></div>
      <div className="psa-chan-main">
        <div className="psa-chan-name">{channel === 'whatsapp' ? 'WhatsApp' : 'Email'}</div>
        <div className="psa-chan-detail">{detail}</div>
      </div>
      {off ? <span className="psa-badge psa-tone-neutral">{phase || 'Phase 2'}</span> : <StatusBadge status={status} />}
    </div>
  );
}

/* ---- DataTable ---- */
export interface Column<R> { key: string; label: string; mono?: boolean; align?: 'right'; width?: number | string; minWidth?: number; render?: (row: R) => ReactNode }
export function DataTable<R extends Record<string, any>>({ columns, rows, empty, onRowClick }: { columns: Column<R>[]; rows: (R & { id?: string | number; _selected?: boolean })[]; empty?: ReactNode; onRowClick?: (row: R) => void }) {
  return (
    <div className="psa-table-wrap">
      <table className="psa-table">
        <thead><tr>{columns.map((c) => <th key={c.key} className={c.align === 'right' ? 'is-right' : undefined} style={c.width || c.minWidth ? { width: c.width, minWidth: c.minWidth } : undefined}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.length === 0 && empty ? <tr><td colSpan={columns.length} className="psa-empty">{empty}</td></tr> : null}
          {rows.map((r, i) => (
            <tr key={r.id ?? i} className={cx(r._selected && 'is-selected', onRowClick && 'psa-clickable')} onClick={onRowClick ? () => onRowClick(r) : undefined}>
              {columns.map((c) => <td key={c.key} className={cx(c.mono && 'psa-mono', c.align === 'right' && 'is-right')}>{c.render ? c.render(r) : r[c.key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---- Switch ---- */
export function Switch({ on, label, description, onChange, disabled }: { on?: boolean; label: string; description?: ReactNode; onChange?: (next: boolean) => void; disabled?: boolean }) {
  const [local, setLocal] = useState(!!on);
  const value = onChange ? !!on : local;
  const toggle = () => { if (disabled) return; if (onChange) onChange(!value); else setLocal(!value); };
  return (
    <div className={cx('psa-switch', value && 'is-on', disabled && 'is-disabled')} role="switch" aria-checked={value} aria-disabled={disabled} tabIndex={0}
      onClick={toggle} onKeyDown={(e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle(); } }}>
      <span className="psa-switch-track" />
      <span><div className="psa-switch-label">{label}</div>{description ? <div className="psa-switch-desc">{description}</div> : null}</span>
    </div>
  );
}

/* ---- Tabs (controlled when onChange + active are given) ---- */
export function Tabs({ items, active, onChange }: { items: { id: string; label: string; icon?: IconName; count?: number }[]; active?: string; onChange?: (id: string) => void }) {
  const [local, setLocal] = useState(active || items[0]?.id);
  const current = onChange && active ? active : local;
  return (
    <div className="psa-tabs" role="tablist">
      {items.map((t) => (
        <button key={t.id} role="tab" aria-selected={t.id === current} className={cx('psa-tab', t.id === current && 'is-active')}
          onClick={() => { setLocal(t.id); onChange?.(t.id); }}>
          {t.icon ? <Icon name={t.icon} /> : null}{t.label}{t.count != null ? <span className="psa-tab-count">{t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

/* ---- Banner ---- */
const BANNER_ICON: Record<Tone, IconName> = { info: 'info', success: 'check', warning: 'alert', danger: 'alert' };
export function Banner({ tone = 'info', title, action, children }: { tone?: Tone; title?: ReactNode; action?: ReactNode; children?: ReactNode }) {
  return (
    <div className={cx('psa-banner', tone !== 'info' && 'psa-tone-' + tone)} role={tone === 'danger' ? 'alert' : 'status'}
      style={tone !== 'info' ? { background: `var(--${tone}-soft)` } : undefined}>
      <Icon name={BANNER_ICON[tone]} />
      <div style={{ flex: 1 }}>
        {title ? <div className="psa-banner-title">{title}</div> : null}
        {children ? <div className="psa-banner-body">{children}</div> : null}
      </div>
      {action || null}
    </div>
  );
}

/* ---- AppShell: sidebar + top bar for every admin screen ---- */
const NAV: { id: string; label: string; icon: IconName; to: string }[] = [
  { id: 'dashboard', label: 'Home', icon: 'dashboard', to: '/' },
  { id: 'classes', label: 'Classes', icon: 'classes', to: '/classes' },
  { id: 'review', label: 'Check worksheets', icon: 'review', to: '/review' },
  { id: 'delivery', label: 'Delivery status', icon: 'send', to: '/delivery' },
  { id: 'history', label: 'Activity log', icon: 'history', to: '/history' },
];
export function AppShell(p: {
  active?: string; title: ReactNode; crumb?: ReactNode; actions?: ReactNode; classes?: { id: number; name: string }[];
  activeClass?: number; children?: ReactNode; footer?: ReactNode;
}) {
  // On phones the sidebar collapses to a top bar; the menu button opens the links below it.
  const [menuOpen, setMenuOpen] = useState(false);
  const close = () => setMenuOpen(false);
  return (
    <div className="psa-shell psa">
      <aside className={cx('psa-side', menuOpen && 'is-open')}>
        <div className="psa-side-bar">
          <div className="psa-brand"><span className="psa-brand-mark">PS</span><span>Practice Sheet<br /> Agent</span></div>
          <button type="button" className="psa-menu-btn" onClick={() => setMenuOpen(!menuOpen)} aria-expanded={menuOpen}
            aria-controls="psa-nav-links" aria-label={menuOpen ? 'Close menu' : 'Open menu'}>
            <Icon name={menuOpen ? 'close' : 'menu'} size={20} />
          </button>
        </div>
        <nav id="psa-nav-links" className="psa-nav-links">
          {NAV.map((n) => (
            <NavLink key={n.id} to={n.to} onClick={close} className={cx('psa-nav', p.active === n.id && 'is-active')}><Icon name={n.icon} />{n.label}</NavLink>
          ))}
          {p.classes && p.classes.length ? <div className="psa-label psa-nav-section">Class workspaces</div> : null}
          {(p.classes || []).map((c) => (
            <NavLink key={c.id} to={`/classes/${c.id}`} onClick={close} style={classTone(c.name)}
              className={cx('psa-nav', 'class-nav', p.activeClass === c.id && 'is-active')}><ClassBadge name={c.name} size={22} />{c.name}</NavLink>
          ))}
        </nav>
        <div style={{ flex: 1 }} />
        {p.footer}
      </aside>
      <div className="psa-main">
        <header className="psa-top">
          <div>{p.crumb ? <div className="psa-crumb">{p.crumb}</div> : null}<h1>{p.title}</h1></div>
          <div className="psa-top-actions">{p.actions}</div>
        </header>
        <main className="psa-content">{p.children}</main>
      </div>
    </div>
  );
}
