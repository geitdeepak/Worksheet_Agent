import { useEffect, useState } from 'react';
import { api } from '../../api';
import { LoadState, useAction, useIsAdmin, useLoad } from '../../app';
import { Button, Card, Switch } from '../../components/ds';
import type { Workspace } from '../ClassWorkspace';

export interface WSettings { counts: Record<string, number>; difficulty: { easy: number; medium: number; hard: number }; answer_key: boolean; language: string }
interface Resp { global: WSettings; class_override: Partial<WSettings> | null; effective: WSettings; labels: Record<string, string>;
  subjects: { id: number; name: string; override: Partial<WSettings> | null; effective: WSettings; language_locked: boolean }[] }

export function SettingsEditor({ value, labels, onChange, disabled, languageLocked }: {
  value: WSettings; labels: Record<string, string>; onChange: (v: WSettings) => void; disabled?: boolean; languageLocked?: boolean;
}) {
  const total = Object.values(value.counts).reduce((a, b) => a + b, 0);
  const mix = value.difficulty.easy + value.difficulty.medium + value.difficulty.hard;
  return (
    <div className="stack">
      <label className="field" style={{ maxWidth: 320 }}><span>Worksheet language</span>
        <select className="select" disabled={disabled || languageLocked} value={languageLocked ? 'Hindi' : value.language}
          onChange={(e) => onChange({ ...value, language: e.target.value })}>
          <option value="English">English</option><option value="Hindi">हिंदी (Hindi)</option></select>
        <small>{languageLocked ? 'The Hindi subject is always prepared in Hindi.' : 'Hindi worksheets use Hindi text with standard maths notation (x², √2, π).'}</small>
      </label>
      <div>
        <div className="psa-label" style={{ marginBottom: 8 }}>Number of questions · {total} in total</div>
        <div className="stack-sm">
          {Object.keys(labels).map((k) => (
            <div key={k} className="row-between">
              <span>{labels[k]}</span>
              <input className="input num-input" type="number" min={0} max={30} disabled={disabled} value={value.counts[k] ?? 0} aria-label={labels[k]}
                onChange={(e) => onChange({ ...value, counts: { ...value.counts, [k]: Math.max(0, Math.min(30, Number(e.target.value) || 0)) } })} />
            </div>
          ))}
        </div>
      </div>
      <div>
        <div className="psa-label" style={{ marginBottom: 8 }}>Easy / medium / hard {mix !== 100 ? <span style={{ color: 'var(--danger)' }}>· adds up to {mix}%, must be 100%</span> : null}</div>
        <div className="row">
          {(['easy', 'medium', 'hard'] as const).map((l) => (
            <label key={l} className="row" style={{ gap: 6 }}>
              <span style={{ textTransform: 'capitalize' }}>{l}</span>
              <input className="input num-input" type="number" min={0} max={100} step={5} disabled={disabled} value={value.difficulty[l]}
                onChange={(e) => onChange({ ...value, difficulty: { ...value.difficulty, [l]: Math.max(0, Math.min(100, Number(e.target.value) || 0)) } })} />%
            </label>
          ))}
        </div>
      </div>
      <Switch on={value.answer_key} disabled={disabled} label="Include answers" description="Answers are printed on the last page, so you can remove them before printing." onChange={(v) => onChange({ ...value, answer_key: v })} />
    </div>
  );
}

export default function WorksheetSettingsTab({ ws, reload: reloadWs }: { ws: Workspace; reload: () => void }) {
  const admin = useIsAdmin();
  const { data, setData, error, loading } = useLoad<Resp>(`/api/classes/${ws.id}/worksheet-settings`, [ws.id]);
  const [draft, setDraft] = useState<WSettings | null>(null);
  const [subject, setSubject] = useState<number | 'class'>('class');
  const { busy, run } = useAction();

  const subj = data && subject !== 'class' ? data.subjects.find((s) => s.id === subject) : undefined;
  const current = data ? (subject === 'class' ? data.effective : subj?.effective) : null;
  const override = data ? (subject === 'class' ? data.class_override : subj?.override) : null;
  useEffect(() => { setDraft(current ? structuredClone(current) : null); }, [data, subject]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save(clear = false) {
    const url = subject === 'class' ? `/api/classes/${ws.id}/worksheet-settings` : `/api/subjects/${subject}/worksheet-settings`;
    const r = await run('save', () => api.put<Resp>(url, { settings: clear ? null : draft }), clear ? 'Back to the default settings.' : 'Saved.');
    if (r) { setData(r); reloadWs(); }
  }

  return <>
    <LoadState error={error} loading={loading && !data} />
    {data && draft ? (
      <Card title="Worksheet language and questions" actions={
        <select className="select" style={{ width: 230 }} value={String(subject)} aria-label="Apply to"
          onChange={(e) => setSubject(e.target.value === 'class' ? 'class' : Number(e.target.value))}>
          <option value="class">All subjects in {ws.name}</option>
          {data.subjects.map((s) => <option key={s.id} value={s.id}>Only {s.name}</option>)}
        </select>}>
        <div className="stack">
          <div className="help">{subject === 'class'
            ? 'These settings apply to every subject in this class. You can change one subject using the menu on the right.'
            : `These settings apply only to ${subj?.name}.`}{override ? ' (Changed from the default.)' : ''}</div>
          <SettingsEditor value={draft} labels={data.labels} onChange={setDraft} disabled={!admin} languageLocked={subj?.language_locked} />
          {subject === 'class' && data.subjects.some((s) => s.language_locked) ? (
            <div className="muted-sm">{data.subjects.filter((s) => s.language_locked).map((s) => s.name).join(', ')} will always be in Hindi.</div>
          ) : null}
          {admin ? <div className="row">
            <Button variant="primary" onClick={() => save()} disabled={busy === 'save'}>Save</Button>
            {override ? <Button variant="quiet" onClick={() => save(true)}>Use default settings</Button> : null}
          </div> : null}
        </div>
      </Card>
    ) : null}
  </>;
}
