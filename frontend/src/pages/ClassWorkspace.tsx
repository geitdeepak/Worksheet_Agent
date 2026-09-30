import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../api';
import { Layout, LoadState, useAction, useClassList, useIsAdmin, useLoad } from '../app';
import { Banner, Button, Card, StatusBadge, Switch, Tabs, classNumber, classTone } from '../components/ds';
import DateSheetTab from './workspace/DateSheetTab';
import SyllabusTab from './workspace/SyllabusTab';
import SubjectsTab from './workspace/SubjectsTab';
import StudentsTab from './workspace/StudentsTab';
import SettingsTab from './workspace/SettingsTab';

export interface ExamRow {
  id: number; exam_code: string; subject: string; sections: string; exam_date: string; exam_date_iso: string; time: string;
  trigger: string; past: boolean; status: string; worksheet_id: number | null; job_error: string | null; syllabus: string | null;
  in_progress: boolean; reused: boolean;
}
export interface PendingRow { exam_code: string; subject_name: string; sections: string; exam_date: string; exam_date_label: string; exam_time: string | null; trigger: string; past: boolean; late: boolean }
export interface SyllabusEntry { subject: string; text: string; chapters: number[]; topics: string[]; excluded_chapters?: number[] }
export interface Workspace {
  id: number; name: string; grade: string; academic_year: string; sections: string; students: number; subjects: number;
  automation: 'draft' | 'active' | 'paused'; next_trigger: string | null; release_mode: 'review' | 'auto';
  channel_email: boolean; channel_whatsapp: boolean; phase: number; scheduler_time: string; timezone: string; lead_days: number;
  datesheet: { file: string | null; uploaded_at: string | null; confirmed: boolean; issues: { row: number; message: string }[]; exams: ExamRow[];
    pending: { file: string; rows: PendingRow[]; issues: { row: number; message: string }[] } | null };
  syllabus: { file: string | null; uploaded_at: string | null; confirmed: boolean; entries: SyllabusEntry[]; missing: string[];
    pending: { file: string; entries: SyllabusEntry[]; issues: { subject: string; message: string }[]; raw: string } | null };
  readiness: { id: string; label: string; ready: boolean; detail: string }[];
  problems: string[]; subject_count: number; student_count: number;
}

/* The four setup steps, in order. Readiness ids come from the backend. */
const STEPS = [
  { tab: 'dates', readiness: 'datesheet', title: 'Exam dates', help: 'Upload the date sheet' },
  { tab: 'syllabus', readiness: 'syllabus', title: 'Exam syllabus', help: 'Which chapters each exam covers' },
  { tab: 'material', readiness: 'subjects', title: 'Study material', help: 'Chapter PDFs for each subject' },
  { tab: 'students', readiness: 'students', title: 'Students', help: 'Who receives the worksheets' },
];
const ALIASES: Record<string, string> = { datesheet: 'dates', subjects: 'material', worksheet: 'settings', delivery: 'settings', automation: 'settings' };

export default function ClassWorkspace() {
  const { id, tab: rawTab } = useParams();
  const classId = Number(id);
  const nav = useNavigate();
  const admin = useIsAdmin();
  const { refresh } = useClassList();
  const { data: ws, setData, error, loading, reload } = useLoad<Workspace>(`/api/classes/${classId}`, [classId]);
  const { busy, run } = useAction();

  const ready = (rid: string) => ws?.readiness.find((r) => r.id === rid)?.ready ?? false;
  const firstTodo = STEPS.find((s) => !ready(s.readiness))?.tab ?? 'dates';
  const tabParam = rawTab ? (ALIASES[rawTab] ?? rawTab) : null;
  const active = tabParam && [...STEPS.map((s) => s.tab), 'settings'].includes(tabParam) ? tabParam : firstTodo;
  const done = STEPS.filter((s) => ready(s.readiness)).length;
  const allReady = ws ? ws.problems.length === 0 : false;

  async function automation(action: 'activate' | 'pause') {
    const r = await run('auto', () => api.post<Workspace>(`/api/classes/${classId}/automation`, { action }),
      action === 'activate' ? `${ws?.name} is live. Worksheets will go out ${ws?.lead_days} days before each exam.` : 'Paused. No new worksheets will be made for this class.');
    if (r) { setData(r); refresh(); }
  }
  async function patch(body: Partial<Workspace>) {
    const r = await run('patch', () => api.patch<Workspace>(`/api/classes/${classId}`, body), 'Saved.');
    if (r) setData(r);
  }

  const tz = ws?.timezone === 'Asia/Kolkata' ? 'IST' : ws?.timezone;
  const headerActions = ws && admin ? (ws.automation === 'active'
    ? <><StatusBadge status="active">Sending automatically</StatusBadge><Button icon="pause" onClick={() => automation('pause')} disabled={busy === 'auto'}>Pause</Button></>
    : allReady ? <Button variant="primary" icon="bolt" onClick={() => automation('activate')} disabled={busy === 'auto'}>Start sending worksheets</Button>
      : <StatusBadge status={ws.automation === 'paused' ? 'paused' : 'draft'}>{ws.automation === 'paused' ? 'Paused' : `Setup ${done} of 4`}</StatusBadge>) : null;

  return (
    <Layout active="classes" activeClass={classId} title={ws?.name ?? 'Class'} crumb={ws ? `Classes › Academic year ${ws.academic_year} · Sections ${ws.sections}` : 'Classes'} actions={headerActions}>
      <LoadState error={error} loading={loading && !ws} />
      {ws ? <div className="class-scope stack-lg" style={classTone(ws.name)}>
        <div className="class-hero">
          <span className="class-hero-num">{classNumber(ws.name)}</span>
          <div>
            <h2>{ws.name}</h2>
            <div className="class-hero-sub">Sections {ws.sections} · Academic year {ws.academic_year}</div>
            {ws.automation === 'active'
              ? <div className="class-hero-sub" style={{ marginTop: 6 }}>● Sending worksheets automatically{ws.next_trigger ? ` · next ${ws.next_trigger}` : ''}</div>
              : <div className="row" style={{ marginTop: 8, gap: 10 }}><div className="progress"><span style={{ width: `${done * 25}%` }} /></div>
                <span className="class-hero-sub">Setup {done} of 4</span></div>}
          </div>
          <div className="class-hero-stats">
            <div><b>{ws.student_count}</b><span>Students</span></div>
            <div><b>{ws.subject_count}</b><span>Subjects</span></div>
            <div><b>{ws.datesheet.exams.filter((e) => !e.past).length}</b><span>Exams</span></div>
          </div>
        </div>
        <Tabs active={active} onChange={(t) => nav(`/classes/${classId}/${t}`)} items={[
          ...STEPS.map((s, i) => ({ id: s.tab, label: `${i + 1}. ${s.title}`, icon: ready(s.readiness) ? 'check' as const : undefined,
            count: s.tab === 'students' ? ws.student_count : undefined })),
          { id: 'settings', label: 'Settings', icon: 'sliders' as const },
        ]} />
        <div className="psa-two">
          <div className="stack-lg">
            {active === 'dates' ? <DateSheetTab ws={ws} onChange={(w) => { setData(w); refresh(); }} reload={reload} /> : null}
            {active === 'syllabus' ? <SyllabusTab ws={ws} onChange={(w) => setData(w)} reload={reload} /> : null}
            {active === 'material' ? <SubjectsTab ws={ws} reload={reload} /> : null}
            {active === 'students' ? <StudentsTab ws={ws} reload={reload} /> : null}
            {active === 'settings' ? <SettingsTab ws={ws} patch={patch} busy={busy === 'patch'} reload={reload} /> : null}
            {active !== 'settings' ? <NextStep ws={ws} active={active} ready={ready} onGo={(t) => nav(`/classes/${classId}/${t}`)} /> : null}
          </div>
          <div className="stack-lg">
            {ws.automation === 'active' ? (
              <Card title="Sending automatically">
                <div className="stack">
                  <div>Every day at <b>{ws.scheduler_time} {tz}</b>, worksheets are made for exams <b>{ws.lead_days} days</b> away and sent to students.</div>
                  {ws.next_trigger ? <div className="help">Next worksheet: <b>{ws.next_trigger}</b></div> : <div className="help">No upcoming exams on the date sheet.</div>}
                  <Switch on={ws.release_mode === 'review'} disabled={!admin} label="Let me check each worksheet before it is sent"
                    description={ws.release_mode === 'review' ? 'You approve every worksheet in “Check worksheets”.' : 'Worksheets that pass all checks are sent without waiting for you.'}
                    onChange={(on) => patch({ release_mode: on ? 'review' : 'auto' })} />
                </div>
              </Card>
            ) : null}
            <Card title="Setup checklist">
              <div className="stack">
                <div className="row-between"><span className="muted-sm">{done} of 4 steps done</span><span className="muted-sm">{Math.round(done * 25)}%</span></div>
                <div className="progress"><span style={{ width: `${done * 25}%` }} /></div>
                <ol className="checklist">
                  {STEPS.map((s, i) => {
                    const r = ws.readiness.find((x) => x.id === s.readiness);
                    return (
                      <li key={s.tab} className={(r?.ready ? 'is-done' : '') + (active === s.tab ? ' is-current' : '')}>
                        <button onClick={() => nav(`/classes/${classId}/${s.tab}`)}>
                          <span className="check-dot">{r?.ready ? '✓' : i + 1}</span>
                          <span className="grow"><div className="t">{s.title}</div><div className="s">{r?.ready ? r.detail : s.help}</div></span>
                        </button>
                      </li>
                    );
                  })}
                </ol>
                {ws.automation !== 'active' && admin ? (allReady
                  ? <Button variant="primary" icon="bolt" className="big-cta" onClick={() => automation('activate')} disabled={busy === 'auto'}>Start sending worksheets</Button>
                  : <div className="help">When all four steps are done, you can start sending worksheets automatically.
                    {ws.problems.length && done === 4 ? <> Still needed: {ws.problems.join(' ')}</> : null}</div>) : null}
              </div>
            </Card>
          </div>
        </div>
      </div> : null}
    </Layout>
  );
}

function NextStep({ ws, active, ready, onGo }: { ws: Workspace; active: string; ready: (r: string) => boolean; onGo: (t: string) => void }) {
  const idx = STEPS.findIndex((s) => s.tab === active);
  const cur = STEPS[idx];
  if (!cur || !ready(cur.readiness)) return null;
  const next = STEPS.slice(idx + 1).find((s) => !ready(s.readiness)) ?? STEPS.find((s) => !ready(s.readiness));
  if (!next) return ws.automation === 'active' ? null
    : <Banner tone="success" title="All steps are done">Click “Start sending worksheets” at the top right when you’re ready.</Banner>;
  return <Banner tone="success" title={`${cur.title} done`} action={<Button variant="primary" size="sm" onClick={() => onGo(next.tab)}>Next: {next.title}</Button>}>
    Continue with step {STEPS.indexOf(next) + 1}.</Banner>;
}
