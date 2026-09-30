import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { Layout, LoadState, useAction, useIsAdmin, useLoad } from '../app';
import { Button, Card, DataTable, StatusBadge, Tabs } from '../components/ds';

interface Ev { id: number; ts: string; actor: string; event: string; class: string | null; summary: string; level: string }
interface JobRow { id: number; type: string; business_key: string; class: string; subject: string; exam_date: string; trigger_date: string; status: string; attempts: number; error: string | null; source: string; worksheet_id: number | null; created_date: string; created: string }

const EVENTS = ['', 'upload', 'datesheet', 'syllabus', 'job', 'generation', 'validation', 'edit', 'approval', 'release', 'regeneration', 'email', 'whatsapp', 'delivery', 'retry', 'alert', 'automation', 'settings', 'login'];

export default function History() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') || 'audit';
  const [event, setEvent] = useState('');
  const [q, setQ] = useState('');
  const level = params.get('level') || '';
  const qs = new URLSearchParams({ limit: '300', ...(event ? { event } : {}), ...(level ? { level } : {}), ...(q ? { q } : {}) }).toString();
  const audit = useLoad<Ev[]>(tab === 'audit' ? `/api/audit?${qs}` : null, [qs, tab]);
  const jobs = useLoad<JobRow[]>(tab === 'jobs' ? '/api/jobs?limit=300' : null, [tab]);
  const nav = useNavigate();
  const admin = useIsAdmin();
  const { run } = useAction();

  async function retry(j: JobRow) {
    const r = await run('retry', () => api.post(`/api/jobs/${j.id}/retry`), 'Job queued again.');
    if (r) jobs.reload();
  }

  return (
    <Layout active="history" title="Activity log" crumb="Everything that happened: uploads, worksheets, approvals and deliveries">
      <Tabs active={tab} onChange={(t) => setParams({ tab: t })} items={[{ id: 'audit', label: 'Audit trail', icon: 'history' }, { id: 'jobs', label: 'Jobs', icon: 'bolt' }]} />
      {tab === 'audit' ? <>
        <div className="row">
          <select className="select" style={{ width: 180 }} value={event} onChange={(e) => setEvent(e.target.value)} aria-label="Event type">
            {EVENTS.map((e) => <option key={e} value={e}>{e ? e[0].toUpperCase() + e.slice(1) : 'All events'}</option>)}</select>
          <select className="select" style={{ width: 160 }} value={level} onChange={(e) => setParams({ tab, ...(e.target.value ? { level: e.target.value } : {}) })} aria-label="Level">
            <option value="">All levels</option><option value="error">Errors</option><option value="warning">Warnings</option></select>
          <input className="input" style={{ width: 260 }} placeholder="Search summaries" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <LoadState error={audit.error} loading={audit.loading && !audit.data} />
        <Card flush>
          <DataTable empty="No matching events."
            columns={[
              { key: 'ts', label: 'Time', mono: true, width: 150 },
              { key: 'event', label: 'Event', render: (r) => r.level === 'error' ? <StatusBadge status="failed">{r.event}</StatusBadge> : r.level === 'warning' ? <StatusBadge status="retrying">{r.event}</StatusBadge> : <span className="psa-mono">{r.event}</span> },
              { key: 'class', label: 'Class', render: (r) => r.class ?? '—' },
              { key: 'summary', label: 'What happened' },
              { key: 'actor', label: 'By', render: (r) => <span className="muted-sm">{r.actor}</span> },
            ]} rows={audit.data ?? []} />
        </Card>
      </> : <>
        <LoadState error={jobs.error} loading={jobs.loading && !jobs.data} />
        <Card flush>
          <DataTable empty="No jobs yet."
            onRowClick={(r) => r.worksheet_id && nav(r.type === 'SHARE_WORKSHEET' ? `/delivery/${r.worksheet_id}` : `/review/${r.worksheet_id}`)}
            columns={[
              { key: 'created_date', label: 'Created', render: (r) => <span className="psa-mono">{r.created_date} {r.created}</span> },
              { key: 'type', label: 'Job', mono: true },
              { key: 'class', label: 'Class' }, { key: 'subject', label: 'Subject' }, { key: 'exam_date', label: 'Exam' },
              { key: 'trigger_date', label: 'Trigger' }, { key: 'source', label: 'Source' },
              { key: 'attempts', label: 'Attempts', align: 'right' },
              { key: 'status', label: 'Status', render: (r) => <span title={r.error || r.business_key}><StatusBadge status={r.status} /></span> },
              ...(admin ? [{ key: 'act', label: '', render: (r: JobRow) => r.status === 'failed' ? <Button size="sm" variant="quiet" onClick={(e) => { e.stopPropagation(); retry(r); }}>Retry</Button> : null }] : []),
            ]} rows={jobs.data ?? []} />
        </Card>
      </>}
    </Layout>
  );
}
