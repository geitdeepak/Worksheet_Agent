import { useEffect, useState } from 'react';
import { api } from '../api';
import { Dialog, Layout, LoadState, useAction, useAuth, useClassList, useIsAdmin, useLoad, type User } from '../app';
import { Banner, Button, Card, DataTable, StatusBadge, Switch } from '../components/ds';
import { SettingsEditor, type WSettings } from './workspace/WorksheetSettingsTab';

interface AppSettings {
  institution_name: string; timezone: string; scheduler_time: string; lead_days: number; phase: number; worksheet_defaults: WSettings;
  reuse_worksheets: boolean; use_batch: boolean;
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

function PasswordCard() {
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

function UsersCard() {
  const { data, reload } = useLoad<(User & { active: boolean })[]>('/api/users');
  const { classes } = useClassList();
  const { user: me } = useAuth();
  const [edit, setEdit] = useState<(Partial<User> & { password?: string; active?: boolean }) | null>(null);
  const { busy, run } = useAction();

  async function save() {
    const body = { email: edit!.email, name: edit!.name, role: edit!.role ?? 'teacher', password: edit!.password || null, class_access: edit!.class_access ?? [], active: edit!.active ?? true };
    const r = await run('u', () => edit!.id ? api.patch(`/api/users/${edit!.id}`, body) : api.post('/api/users', body), 'User saved.');
    if (r) { setEdit(null); reload(); }
  }
  return (
    <Card title="People" flush actions={<Button size="sm" icon="plus" onClick={() => setEdit({ role: 'teacher', class_access: [], active: true })}>Add</Button>}>
      <DataTable onRowClick={(u) => setEdit({ ...u })}
        columns={[{ key: 'name', label: 'Name' }, { key: 'role', label: 'Role' },
          { key: 'access', label: 'Classes', render: (u) => u.role === 'admin' ? 'All' : (u.class_access.map((id) => classes.find((c) => c.id === id)?.name).filter(Boolean).join(', ') || 'None') },
          { key: 'active', label: 'Status', render: (u) => u.active ? <StatusBadge status="active" /> : <StatusBadge status="cancelled">Disabled</StatusBadge> }]}
        rows={data ?? []} />
      {edit ? (
        <Dialog title={edit.id ? edit.email! : 'Add person'} onClose={() => setEdit(null)}
          footer={<><Button variant="quiet" onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" onClick={save} disabled={busy === 'u'}>Save</Button></>}>
          <div className="grid-2">
            {!edit.id ? <label className="field"><span>Email</span><input className="input" type="email" value={edit.email ?? ''} onChange={(e) => setEdit({ ...edit, email: e.target.value })} /></label> : null}
            <label className="field"><span>Name</span><input className="input" value={edit.name ?? ''} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></label>
            <label className="field"><span>Role</span><select className="select" value={edit.role} disabled={edit.id === me?.id} onChange={(e) => setEdit({ ...edit, role: e.target.value as User['role'] })}>
              <option value="teacher">Teacher</option><option value="admin">Administrator</option></select></label>
            <label className="field"><span>{edit.id ? 'New password (optional)' : 'Password'}</span><input className="input" type="password" value={edit.password ?? ''} onChange={(e) => setEdit({ ...edit, password: e.target.value })} /></label>
          </div>
          {edit.role === 'teacher' ? (
            <div className="field"><span>Classes this teacher can see and review</span>
              <div className="row">{classes.map((c) => (
                <label key={c.id} className="row" style={{ gap: 6 }}><input type="checkbox" checked={edit.class_access?.includes(c.id) ?? false}
                  onChange={(e) => setEdit({ ...edit, class_access: e.target.checked ? [...(edit.class_access ?? []), c.id] : (edit.class_access ?? []).filter((x) => x !== c.id) })} />{c.name}</label>
              ))}</div></div>
          ) : <Banner>Administrators can see and change every class.</Banner>}
          {edit.id && edit.id !== me?.id ? <Switch on={edit.active ?? true} onChange={(v) => setEdit({ ...edit, active: v })} label="Active" description="Disabled people can’t sign in." /> : null}
        </Dialog>
      ) : null}
    </Card>
  );
}
