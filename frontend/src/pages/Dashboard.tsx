import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { Layout, LoadState, useAction, useAuth, useClassList, useIsAdmin, useLoad } from '../app';
import { Button, Card, ClassBadge, ClassChip, DataTable, KpiTile, StatusBadge, classTone } from '../components/ds';

interface Dash {
  todo: { tone: 'danger' | 'warning' | 'info'; title: string; detail: string; action: string; to: string }[];
  today: string; weekday: string; scheduler_time: string; timezone: string; phase: number;
  last_run: { at: string; date: string; created: number } | null;
  kpis: Record<string, number | null> & { generated_subjects: string[] };
  awaiting: { id: number; title: string; subject: string; class: string; exam_date: string; status: string; version: number }[];
  jobs: { id: number; time: string; type: string; class: string; subject: string; exam: string; status: string; worksheet_id: number | null; error: string | null }[];
  upcoming: { id: number; class: string; class_id: number; subject: string; exam_date: string; trigger: string; automation: string }[];
  exceptions: { id: number; summary: string; time: string }[];
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}

export default function Dashboard() {
  const { data, error, loading, reload } = useLoad<Dash>('/api/dashboard');
  const nav = useNavigate();
  const admin = useIsAdmin();
  const { user } = useAuth();
  const { classes } = useClassList();
  const { busy, run } = useAction();
  const k = data?.kpis;

  async function runNow() {
    const r = await run('run', () => api.post<{ created: number; target_exam_date: string }>('/api/scheduler/run'));
    if (r) { await reload(); setTimeout(reload, 4000); }
  }

  const tz = data?.timezone === 'Asia/Kolkata' ? 'IST' : data?.timezone;
  const crumb = data ? `${data.weekday}, ${data.today} · ` + (data.last_run?.date ? `scheduler ran ${data.last_run.at.slice(11, 16)} ${tz}` : `scheduler runs daily at ${data.scheduler_time} ${tz}`) : '';
  const waiting = data?.awaiting.filter((w) => w.status === 'awaiting-approval') ?? [];

  return (
    <Layout active="dashboard" title="Home" crumb={crumb}
      actions={admin ? <Button icon="refresh" onClick={runNow} disabled={busy === 'run'}>{busy === 'run' ? 'Checking…' : 'Check for exams now'}</Button> : null}>
      <LoadState error={error} loading={loading && !data} />
      {data && k ? <>
        <div className="welcome">
          <div>
            <h2>{greeting()}, {user?.name?.split(' ')[0] ?? 'there'}</h2>
            <p>{data.todo.length ? `${data.todo.length} thing${data.todo.length > 1 ? 's need' : ' needs'} your attention today.` : 'Everything is on track. Worksheets are being made and sent automatically.'}</p>
          </div>
          {classes.length ? (
            <div className="welcome-classes">
              {classes.map((c) => <Link key={c.id} to={`/classes/${c.id}`}><ClassBadge name={c.name} size={24} />{c.name}</Link>)}
            </div>
          ) : null}
        </div>

        <Card title="Needs your attention" flush>
          {data.todo.length ? (
            <ul className="todo">
              {data.todo.map((t, i) => (
                <li key={i}>
                  <span className={`dot is-${t.tone}`} aria-hidden="true" />
                  <div className="grow"><div className="t">{t.title}</div>{t.detail ? <div className="s">{t.detail}</div> : null}</div>
                  <Button size="sm" variant={i === 0 ? 'primary' : 'secondary'} onClick={() => nav(t.to)}>{t.action}</Button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="all-good">✓ All good. Nothing needs you today.</div>
          )}
        </Card>

        <div className="psa-grid-kpi">
          <KpiTile hue={1} icon="classes" label="Active classes" value={k.active_classes} note={`of ${k.configured_classes} set up`} onClick={() => nav('/classes')} />
          <KpiTile hue={8} icon="calendar" label="Upcoming exams" value={k.upcoming_exams} note="in the next 14 days" />
          <KpiTile hue={7} icon="review" label="Waiting for you" value={k.awaiting_approval} note={waiting[0] ? `${waiting[0].subject} · ${waiting[0].class}` : 'nothing to check'} onClick={() => nav('/review')} />
          <KpiTile hue={6} icon="send" label="Sent today" value={(k.email_sent ?? 0) + (data.phase >= 2 ? (k.whatsapp_sent ?? 0) : 0)} note={data.phase >= 2 ? 'email and WhatsApp' : 'by email'} onClick={() => nav('/delivery')} />
          <KpiTile hue={4} icon="alert" label="Not delivered" value={k.email_failed ?? 0} tone={k.email_failed ? 'danger' : null} note={k.email_failed ? 'usually a wrong email' : 'none'} onClick={() => nav('/delivery')} />
        </div>

        <div className="psa-two">
          <Card title="Today’s activity" flush actions={<Button variant="quiet" size="sm" onClick={() => nav('/history?tab=jobs')}>See all</Button>}>
            <DataTable
              empty="Nothing yet today. Worksheets are made automatically two days before each exam."
              onRowClick={(r) => r.worksheet_id && nav(r.type === 'SHARE_WORKSHEET' ? `/delivery/${r.worksheet_id}` : `/review/${r.worksheet_id}`)}
              columns={[
                { key: 'time', label: 'Time', mono: true },
                { key: 'type', label: 'What', render: (r) => r.type === 'SHARE_WORKSHEET' ? 'Send worksheet' : 'Make worksheet' },
                { key: 'class', label: 'Class', render: (r) => <ClassChip name={r.class} /> },
                { key: 'subject', label: 'Subject' },
                { key: 'exam', label: 'Exam' },
                { key: 'status', label: 'Status', render: (r) => <span title={r.error || undefined}><StatusBadge status={r.status} /></span> },
              ]}
              rows={data.jobs} />
          </Card>
          <div className="stack-lg">
            <Card title="Upcoming exams">
              <div className="stack-sm">
                {data.upcoming.length === 0 ? <div className="muted-sm">No exams in the next 14 days.</div> : null}
                {data.upcoming.map((e) => {
                  const [day, month] = e.exam_date.split(' ');
                  return (
                    <div key={e.id} className="exam-row" style={classTone(e.class)} onClick={() => nav(`/classes/${e.class_id}`)}>
                      <div className="exam-date"><b>{day}</b><span>{month}</span></div>
                      <div className="grow">
                        <div style={{ fontWeight: 600 }}>{e.subject}</div>
                        <div className="muted-sm">{e.automation === 'active' ? `Worksheet goes out ${e.trigger}` : 'Class not started yet'}</div>
                      </div>
                      <ClassChip name={e.class} />
                    </div>
                  );
                })}
              </div>
            </Card>
            {data.exceptions.length ? (
              <Card title="Problems today" actions={<Button variant="quiet" size="sm" onClick={() => nav('/history?level=error')}>Details</Button>}>
                <div className="stack-sm">
                  {data.exceptions.slice(0, 5).map((x) => <div key={x.id} className="muted-sm"><span className="psa-mono">{x.time}</span> · {x.summary}</div>)}
                </div>
              </Card>
            ) : null}
          </div>
        </div>
      </> : null}
    </Layout>
  );
}
