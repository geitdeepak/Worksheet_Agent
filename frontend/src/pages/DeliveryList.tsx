import { useNavigate } from 'react-router-dom';
import { Layout, LoadState, useLoad } from '../app';
import { Card, ClassChip, DataTable, StatusBadge } from '../components/ds';
import type { WsSummary } from './ReviewList';

type Row = WsSummary & { summary: Record<string, Record<string, number>> };

function channelCell(s: Record<string, number> | undefined) {
  if (!s) return <span className="psa-muted">—</span>;
  const ok = (s.sent ?? 0) + (s.delivered ?? 0);
  const total = Object.values(s).reduce((a, b) => a + b, 0);
  const bad = s.failed ?? 0;
  const pending = (s.retrying ?? 0) + (s.queued ?? 0) + (s.sending ?? 0);
  return <div className="row" style={{ gap: 6 }}>
    <span className="num">{ok}/{total}</span>
    {bad ? <StatusBadge status="failed">{bad} failed</StatusBadge> : null}
    {pending ? <StatusBadge status="retrying">{pending} pending</StatusBadge> : null}
    {s.skipped ? <StatusBadge status="skipped">{s.skipped} skipped</StatusBadge> : null}
  </div>;
}

export default function DeliveryList() {
  const { data, error, loading } = useLoad<Row[]>('/api/deliveries');
  const nav = useNavigate();
  return (
    <Layout active="delivery" title="Delivery status" crumb="Which students received each worksheet">
      <LoadState error={error} loading={loading && !data} />
      <Card flush>
        <DataTable onRowClick={(r) => nav(`/delivery/${r.id}`)} empty="Nothing has been released yet."
          columns={[
            { key: 'subject', label: 'Subject' },
            { key: 'class', label: 'Class', render: (r) => <ClassChip name={r.class} suffix={r.sections ? ` · ${r.sections}` : ''} /> },
            { key: 'exam_date', label: 'Exam' },
            { key: 'version', label: 'Version', render: (r) => `v${r.version}` },
            { key: 'email', label: 'Email', render: (r) => channelCell(r.summary.email) },
            { key: 'whatsapp', label: 'WhatsApp', render: (r) => channelCell(r.summary.whatsapp) },
          ]} rows={data ?? []} />
      </Card>
    </Layout>
  );
}
