import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api, openFile } from '../api';
import { Layout, LoadState, useAction, useLoad } from '../app';
import { Banner, Button, Card, ChannelStatus, DataTable, StatusBadge } from '../components/ds';

interface Row { id: number; student_code: string; name: string; section: string; email: string; whatsapp: string;
  email_status: string | null; whatsapp_status: string | null; email_error?: string; whatsapp_error?: string }
interface Resp {
  id: number; title: string; subject: string; class: string; class_id: number; sections: string; exam_date: string; version: number;
  summary: Record<string, Record<string, number>>; rows: Row[]; released_at: string | null; share_job: { status: string; error: string | null } | null;
  phase: number; channels: string[]; channel_whatsapp: boolean;
}

function channelSummary(s: Record<string, number> | undefined): { status: string; detail: string } {
  if (!s) return { status: 'queued', detail: 'Not started' };
  const total = Object.values(s).reduce((a, b) => a + b, 0);
  const parts = Object.entries(s).sort().map(([k, v]) => `${v} ${k}`);
  const status = (s.retrying || s.queued || s.sending) ? 'sending' : s.failed && s.failed === total ? 'failed' : (s.sent || s.delivered) ? (s.delivered ? 'delivered' : 'sent') : 'skipped';
  return { status, detail: `${parts.join(' · ')} of ${total}` };
}

export default function DeliveryMonitor() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: d, error, loading, reload } = useLoad<Resp>(`/api/worksheets/${id}/deliveries`, [id]);
  const { busy, run } = useAction();
  const [filter, setFilter] = useState<'all' | 'problems'>('all');

  // While anything is still in flight, refresh every few seconds.
  const inFlight = d ? Object.values(d.summary).some((s) => s.queued || s.sending || s.retrying) || d.share_job?.status === 'pending' || d.share_job?.status === 'running' : false;
  useEffect(() => { if (!inFlight) return; const t = setInterval(reload, 4000); return () => clearInterval(t); }, [inFlight, reload]);

  if (!d) return <Layout active="delivery" title="Delivery status"><LoadState error={error} loading={loading} /></Layout>;
  const email = channelSummary(d.summary.email);
  const wa = channelSummary(d.summary.whatsapp);
  const failedRows = d.rows.filter((r) => r.email_status === 'failed' || r.whatsapp_status === 'failed');
  const rows = filter === 'problems' ? d.rows.filter((r) => ['failed', 'retrying', 'skipped'].includes(r.email_status ?? '') || ['failed', 'retrying'].includes(r.whatsapp_status ?? '')) : d.rows;
  const tz = 'IST';

  async function retry() {
    const r = await run('retry', () => api.post<{ retried: number }>(`/api/worksheets/${d!.id}/retry-failed`));
    if (r) { reload(); }
  }

  return (
    <Layout active="delivery" title="Delivery status"
      crumb={`${d.subject} · ${d.class}${d.sections ? '-' + d.sections : ''} · Exam ${d.exam_date} · v${d.version}${d.released_at ? ` · released ${d.released_at} ${tz}` : ''}`}
      actions={<>
        <Button variant="quiet" onClick={() => nav(`/review/${d.id}`)}>Worksheet</Button>
        <Button icon="refresh" onClick={retry} disabled={busy === 'retry'} title="Re-sends failed deliveries using the students’ current contact details">Retry failed</Button>
      </>}>
      <div className="grid-2">
        <ChannelStatus channel="email" status={d.channels.includes('email') || d.summary.email ? email.status : 'off'} detail={email.detail} phase="Off" />
        <ChannelStatus channel="whatsapp" status={d.summary.whatsapp ? wa.status : 'off'}
          detail={d.summary.whatsapp ? wa.detail : d.phase >= 2 ? (d.channel_whatsapp ? 'Enabled — use Retry failed to send this worksheet' : 'Turned off for this class') : 'Turns on in Phase 2 · tracked separately from email'} phase={d.phase >= 2 ? 'Off' : 'Phase 2'} />
      </div>
      <Card title="Per-student status" flush actions={<div className="row">
        <select className="select" style={{ width: 160 }} value={filter} onChange={(e) => setFilter(e.target.value as 'all' | 'problems')}>
          <option value="all">All students</option><option value="problems">Problems only</option></select>
        <Button variant="quiet" size="sm" icon="download" onClick={() => openFile(`/api/worksheets/${d.id}/deliveries.csv`, `deliveries_${d.subject}_${d.exam_date}.csv`)}>Export CSV</Button></div>}>
        <DataTable empty="No deliveries yet."
          columns={[
            { key: 'student_code', label: 'Student ID', mono: true }, { key: 'name', label: 'Name' }, { key: 'section', label: 'Section' },
            { key: 'email', label: 'Email', mono: true },
            { key: 'email_status', label: 'Email status', render: (r) => r.email_status ? <span title={r.email_error}><StatusBadge status={r.email_status} /></span> : <span className="psa-muted">—</span> },
            { key: 'whatsapp', label: 'WhatsApp', mono: true },
            { key: 'whatsapp_status', label: 'WhatsApp status', render: (r) => r.whatsapp_status ? <span title={r.whatsapp_error}><StatusBadge status={r.whatsapp_status} /></span>
              : <StatusBadge status="skipped">{d.phase >= 2 ? 'Off' : 'Phase 2'}</StatusBadge> },
          ]} rows={rows} />
      </Card>
      {failedRows.slice(0, 3).map((r) => (
        <Banner key={r.id} tone="danger" title={`${r.student_code} · ${r.name}`}
          action={<Button size="sm" onClick={() => nav(`/classes/${d.class_id}/students`)}>Fix contact</Button>}>
          {[r.email_status === 'failed' ? `Email: ${r.email_error}` : '', r.whatsapp_status === 'failed' ? `WhatsApp: ${r.whatsapp_error}` : ''].filter(Boolean).join(' ')} Other recipients were not affected. Fix it in {d.class} › Students and retry.
        </Banner>
      ))}
      {failedRows.length > 3 ? <div className="muted-sm">{failedRows.length - 3} more failures. Filter by “Problems only” to see them.</div> : null}
    </Layout>
  );
}
