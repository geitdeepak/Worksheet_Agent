import { useEffect, useState } from 'react';
import { api } from '../api';
import { Dialog, Layout, LoadState, useAction, useAuth, useClassList, useIsAdmin, useLoad, type User } from '../app';
import { Banner, Button, Card, DataTable, StatusBadge, Switch } from '../components/ds';
import { SettingsEditor, type WSettings } from './workspace/WorksheetSettingsTab';

interface AppSettings {
  institution_name: string; timezone: string; scheduler_time: string; lead_days: number; phase: number; worksheet_defaults: WSettings;
  reuse_worksheets: boolean; use_batch: boolean; parent_daily_limit: number;
  providers: { llm: string; llm_model: string | null; llm_effort: string; llm_context_chars: number; email: string; whatsapp: string };
}
const LABELS: Record<string, string> = { mcq: 'Multiple choice', very_short: 'Very short answer', short: 'Short answer', application: 'Application based', long: 'Long answer', hots: 'Higher order thinking (HOTS)' };

export default function Settings() {
  const admin = useIsAdmin();
  const { data, setData, error, loading } = useLoad<AppSettings>('/api/settings');
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const { busy, run } = useAction();
  useEffect(() => { if (data) setDraft(structuredClone(data)); }, [data]);

  async function save() {
    const { providers: _p, ...body } = draft!;
    void _p;
    const r = await run('save', () => api.put<AppSettings>('/api/settings', body), 'Settings saved.');
    if (r) setData(r);
  }

  return (
    <Layout active="" title="Settings" crumb="Institution, scheduler, phase and people">
      <LoadState error={error} loading={loading && !data} />
      {draft ? (
        <div className="psa-two">
          <div className="stack-lg">
            <Card title="Institution and scheduler">
              <div className="stack">
                <div className="form-grid">
                  <label className="field"><span>Institution name</span><input className="input" disabled={!admin} value={draft.institution_name} onChange={(e) => setDraft({ ...draft, institution_name: e.target.value })} /></label>
                  <label className="field"><span>Timezone</span><input className="input" disabled={!admin} value={draft.timezone} onChange={(e) => setDraft({ ...draft, timezone: e.target.value })} /><small>IANA name, e.g. Asia/Kolkata</small></label>
                  <label className="field"><span>Daily check at</span><input className="input" type="time" disabled={!admin} value={draft.scheduler_time} onChange={(e) => setDraft({ ...draft, scheduler_time: e.target.value })} /></label>
                  <label className="field"><span>Days before exam</span><input className="input" type="number" min={1} max={14} disabled={!admin} value={draft.lead_days} onChange={(e) => setDraft({ ...draft, lead_days: Number(e.target.value) })} /></label>
                </div>
                <Switch on={draft.phase >= 2} disabled={!admin} label="Phase 2 · WhatsApp delivery"
                  description="Lets classes turn on WhatsApp alongside email. Configure the WhatsApp Business Platform on the server first."
                  onChange={(v) => setDraft({ ...draft, phase: v ? 2 : 1 })} />
              </div>
            </Card>
            <Card title="Saving AI costs">
              <div className="stack">
                <Switch on={draft.reuse_worksheets} disabled={!admin} label="Reuse worksheets across sections and classes"
                  description="If another section or class already has a worksheet this term for the same subject, syllabus and settings, it is reused instead of made again. Every section’s students still receive it."
                  onChange={(v) => setDraft({ ...draft, reuse_worksheets: v })} />
                <Switch on={draft.use_batch} disabled={!admin} label="Use the cheaper batch service for scheduled worksheets"
                  description="Half the AI price. Scheduled worksheets take minutes to a few hours instead of seconds, which is fine because they are made two days ahead. “Make it now” is always immediate."
                  onChange={(v) => setDraft({ ...draft, use_batch: v })} />
                <label className="field" style={{ maxWidth: 320 }}><span>Parent practice sheets per child per day</span>
                  <input className="input" type="number" min={1} max={20} disabled={!admin} value={draft.parent_daily_limit}
                    onChange={(e) => setDraft({ ...draft, parent_daily_limit: Number(e.target.value) })} />
                  <small>Each sheet a parent makes is one AI request. Failed attempts don’t count.</small></label>
                {draft.providers.llm !== 'offline' ? (
                  <div className="help">Model: <b>{draft.providers.llm_model}</b> at <b>{draft.providers.llm_effort}</b> effort, using up to
                    {' '}<b>{Math.round(draft.providers.llm_context_chars / 1000)}k characters</b> of the most relevant in-syllabus pages per worksheet.
                    These are set in the server’s <span className="psa-mono">.env</span> ({draft.providers.llm === 'gemini' ? 'GEMINI_MODEL' : 'LLM_MODEL'}, LLM_EFFORT, LLM_CONTEXT_CHARS).</div>
                ) : null}
              </div>
            </Card>
            <Card title="Default worksheet settings">
              <div className="stack">
                <div className="muted-sm">Used by every class and subject unless they override it.</div>
                <SettingsEditor value={draft.worksheet_defaults} labels={LABELS} disabled={!admin} onChange={(w) => setDraft({ ...draft, worksheet_defaults: w })} />
              </div>
            </Card>
            {admin ? <div><Button variant="primary" onClick={save} disabled={busy === 'save'}>Save settings</Button></div> : null}
          </div>
          <div className="stack-lg">
            <Card title="Services">
              <div className="stack-sm" style={{ gap: 10 }}>
                <div className="row-between"><span>Question generation</span>{draft.providers.llm !== 'offline'
                  ? <StatusBadge status="active">{draft.providers.llm === 'gemini' ? 'Gemini · ' : 'Claude · '}{draft.providers.llm_model}</StatusBadge>
                  : <StatusBadge status="paused">Offline</StatusBadge>}</div>
                <div className="row-between"><span>Email</span>{draft.providers.email === 'smtp' ? <StatusBadge status="active">SMTP</StatusBadge> : <StatusBadge status="paused">Outbox (not sent)</StatusBadge>}</div>
                <div className="row-between"><span>WhatsApp</span>{draft.providers.whatsapp === 'cloud_api' ? <StatusBadge status="active">Business Platform</StatusBadge> : <StatusBadge status="paused">Outbox (not sent)</StatusBadge>}</div>
                <div className="muted-sm">Providers and credentials are set in the server’s environment (backend/.env), never in the UI.</div>
              </div>
            </Card>
            <PasswordCard />
            {admin ? <UsersCard /> : null}
          </div>
        </div>
      ) : null}
    </Layout>
  );
}

export function PasswordCard() {
  const [f, setF] = useState({ current: '', new: '' });
  const { busy, run } = useAction();
  return (
    <Card title="Your password">
      <div className="stack">
        <label className="field"><span>Current password</span><input className="input" type="password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} /></label>
        <label className="field"><span>New password</span><input className="input" type="password" value={f.new} onChange={(e) => setF({ ...f, new: e.target.value })} /><small>At least 8 characters.</small></label>
        <div><Button disabled={busy === 'pw' || f.new.length < 8} onClick={async () => { if (await run('pw', () => api.post('/api/auth/password', f), 'Password changed.')) setF({ current: '', new: '' }); }}>Change password</Button></div>
      </div>
    </Card>
  );
}

interface ChildRef { id: number; name: string; class: string | null; section: string }
type Person = User & { active: boolean; children: ChildRef[] };
const ROLE_LABEL: Record<User['role'], string> = { admin: 'Administrator', teacher: 'Teacher', parent: 'Parent' };

function UsersCard() {
  const { data, reload } = useLoad<Person[]>('/api/users');
  const { classes } = useClassList();
  const { user: me } = useAuth();
  const [edit, setEdit] = useState<(Partial<Person> & { password?: string }) | null>(null);
  const { busy, run } = useAction();

  async function save() {
    const body = { email: edit!.email, name: edit!.name, role: edit!.role ?? 'teacher', password: edit!.password || null, class_access: edit!.class_access ?? [], student_ids: edit!.student_ids ?? [], active: edit!.active ?? true };
    const r = await run('u', () => edit!.id ? api.patch(`/api/users/${edit!.id}`, body) : api.post('/api/users', body), 'User saved.');
    if (r) { setEdit(null); reload(); }
  }
  return (
    <Card title="People" flush actions={<Button size="sm" icon="plus" onClick={() => setEdit({ role: 'teacher', class_access: [], student_ids: [], children: [], active: true })}>Add</Button>}>
      <DataTable onRowClick={(u) => setEdit({ ...u })}
        columns={[{ key: 'name', label: 'Name' }, { key: 'role', label: 'Role', render: (u) => ROLE_LABEL[u.role] ?? u.role },
          { key: 'access', label: 'Access', minWidth: 170, render: (u) => u.role === 'admin' ? 'All classes'
            : u.role === 'parent' ? (u.children.map((k) => `${k.name} (${k.class}-${k.section})`).join(', ') || 'No child linked')
            : (u.class_access.map((id) => classes.find((c) => c.id === id)?.name).filter(Boolean).join(', ') || 'None') },
          { key: 'active', label: 'Status', render: (u) => u.active ? <StatusBadge status="active" /> : <StatusBadge status="cancelled">Disabled</StatusBadge> }]}
        rows={data ?? []} />
      {edit ? (
        <Dialog title={edit.id ? edit.email! : 'Add person'} onClose={() => setEdit(null)}
          footer={<><Button variant="quiet" onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" onClick={save} disabled={busy === 'u'}>Save</Button></>}>
          <div className="grid-2">
            {!edit.id ? <label className="field"><span>Email</span><input className="input" type="email" value={edit.email ?? ''} onChange={(e) => setEdit({ ...edit, email: e.target.value })} /></label> : null}
            <label className="field"><span>Name</span><input className="input" value={edit.name ?? ''} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></label>
            <label className="field"><span>Role</span><select className="select" value={edit.role} disabled={edit.id === me?.id} onChange={(e) => setEdit({ ...edit, role: e.target.value as User['role'] })}>
              <option value="teacher">Teacher</option><option value="parent">Parent</option><option value="admin">Administrator</option></select></label>
            <label className="field"><span>{edit.id ? 'New password (optional)' : 'Password'}</span><input className="input" type="password" value={edit.password ?? ''} onChange={(e) => setEdit({ ...edit, password: e.target.value })} /></label>
          </div>
          {edit.role === 'teacher' ? (
            <div className="field"><span>Classes this teacher can see and review</span>
              <div className="row">{classes.map((c) => (
                <label key={c.id} className="row" style={{ gap: 6 }}><input type="checkbox" checked={edit.class_access?.includes(c.id) ?? false}
                  onChange={(e) => setEdit({ ...edit, class_access: e.target.checked ? [...(edit.class_access ?? []), c.id] : (edit.class_access ?? []).filter((x) => x !== c.id) })} />{c.name}</label>
              ))}</div></div>
          ) : edit.role === 'parent' ? (
            <ChildPicker value={edit.student_ids ?? []} known={edit.children ?? []}
              onChange={(student_ids, children) => setEdit({ ...edit, student_ids, children })} />
          ) : <Banner>Administrators can see and change every class.</Banner>}
          {edit.id && edit.id !== me?.id ? <Switch on={edit.active ?? true} onChange={(v) => setEdit({ ...edit, active: v })} label="Active" description="Disabled people can’t sign in." /> : null}
        </Dialog>
      ) : null}
    </Card>
  );
}

/** Link a parent to their children: pick a class, then tick the children. */
function ChildPicker({ value, known, onChange }: { value: number[]; known: ChildRef[]; onChange: (ids: number[], kids: ChildRef[]) => void }) {
  const { classes } = useClassList();
  const [classId, setClassId] = useState<number | null>(classes[0]?.id ?? null);
  const { data } = useLoad<{ students: { id: number; student_code: string; name: string; section: string; active: boolean }[] }>(
    classId ? `/api/classes/${classId}/students` : null);
  const className = classes.find((c) => c.id === classId)?.name ?? null;
  const linked = known.filter((k) => value.includes(k.id));

  function toggle(s: { id: number; name: string; section: string }, on: boolean) {
    if (on) onChange([...value, s.id], [...linked, { id: s.id, name: s.name, class: className, section: s.section }]);
    else onChange(value.filter((x) => x !== s.id), linked.filter((k) => k.id !== s.id));
  }
  return (
    <div className="stack-sm">
      <div className="field"><span>Children this parent can make practice sheets for</span>
        {linked.length ? (
          <div className="chapter-picks">{linked.map((k) => (
            <button key={k.id} type="button" className="chapter-pick is-on" onClick={() => toggle(k, false)} title="Remove">
              {k.name} · {k.class}-{k.section} ✕</button>
          ))}</div>
        ) : <div className="muted-sm">No child linked yet. Choose a class and tick the child below.</div>}
      </div>
      <label className="field"><span>Find a child in</span>
        <select className="select" value={classId ?? ''} onChange={(e) => setClassId(Number(e.target.value))}>
          {classes.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>
      <div className="child-list">
        {(data?.students ?? []).filter((s) => s.active).map((s) => (
          <label key={s.id} className="row" style={{ gap: 8 }}>
            <input type="checkbox" checked={value.includes(s.id)} onChange={(e) => toggle(s, e.target.checked)} />
            {s.name} <span className="muted-sm">· {s.student_code} · Section {s.section}</span>
          </label>
        ))}
        {data && !data.students.length ? <div className="muted-sm">No students in this class yet.</div> : null}
      </div>
    </div>
  );
}
