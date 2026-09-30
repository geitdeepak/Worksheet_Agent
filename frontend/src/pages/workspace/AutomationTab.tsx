import { useNavigate } from 'react-router-dom';
import { LoadState, useLoad } from '../../app';
import { Card, DataTable, Pipeline, StatusBadge } from '../../components/ds';
import type { Workspace } from '../ClassWorkspace';

interface JobRow { id: number; type: string; subject: string; sections: string; exam_date: string; trigger_date: string; status: string; attempts: number; error: string | null; source: string; worksheet_id: number | null; created_date: string; created: string }

export default function AutomationTab({ ws }: { ws: Workspace; patch: (b: Partial<Workspace>) => void; reload: () => void }) {
  const nav = useNavigate();
  const { data, error, loading } = useLoad<JobRow[]>(`/api/jobs?class_id=${ws.id}&limit=50`, [ws.id]);
  const tz = ws.timezone === 'Asia/Kolkata' ? 'IST' : ws.timezone;
  return <>
    <Card title="How automation runs for this class">
      <div className="stack">
        <div>Every day at <b>{ws.scheduler_time} {tz}</b> the scheduler reads the confirmed date sheet and finds exams exactly
          <b> {ws.lead_days} days</b> away. For each, it creates one worksheet job, keyed by exam, class, section, subject, date and version, so a retry or restart can never create it twice.</div>
        <div>The Worksheet Creation Agent uses only the chapter PDFs that match the confirmed exam syllabus, generates the questions, and validates them. {ws.release_mode === 'auto'
          ? 'Worksheets that pass validation are released straight away.' : 'Worksheets wait for a teacher or administrator to approve them.'} The Worksheet Sharing Agent then sends them to every active student in the exam’s sections.</div>
        <Pipeline mode={ws.release_mode} />
      </div>
    </Card>
    <LoadState error={error} loading={loading && !data} />
    <Card title="Jobs for this class" flush>
      <DataTable empty="No jobs yet." onRowClick={(r) => r.worksheet_id && nav(r.type === 'SHARE_WORKSHEET' ? `/delivery/${r.worksheet_id}` : `/review/${r.worksheet_id}`)}
        columns={[
          { key: 'created_date', label: 'Created', render: (r) => <span className="psa-mono">{r.created_date} {r.created}</span> },
          { key: 'type', label: 'Job', mono: true },
          { key: 'subject', label: 'Subject' },
          { key: 'exam_date', label: 'Exam' },
          { key: 'source', label: 'Source' },
          { key: 'attempts', label: 'Attempts', align: 'right' },
          { key: 'status', label: 'Status', render: (r) => <span title={r.error || undefined}><StatusBadge status={r.status} /></span> },
        ]} rows={data ?? []} />
    </Card>
  </>;
}
