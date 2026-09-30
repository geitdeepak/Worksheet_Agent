import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout, LoadState, useLoad } from '../app';
import { Card, ClassChip, DataTable, StatusBadge, Tabs } from '../components/ds';

export interface WsSummary { id: number; title: string; subject: string; class: string; class_id: number; sections: string; exam_code: string; exam_date: string; exam_day: string; version: number; status: string; generator: string; created: string; questions: number; validation: string; release_mode: string }

const FILTERS: Record<string, string> = { review: 'awaiting-approval,validation-failed', released: 'released', all: '' };

export default function ReviewList() {
  const [tab, setTab] = useState('review');
  const { data, error, loading } = useLoad<WsSummary[]>(`/api/worksheets${FILTERS[tab] ? `?status=${FILTERS[tab]}` : ''}`, [tab]);
  const nav = useNavigate();
  return (
    <Layout active="review" title="Check worksheets" crumb="Read each worksheet, fix anything you don’t like, then approve it to send it to students">
      <Tabs active={tab} onChange={setTab} items={[{ id: 'review', label: 'Waiting for you', icon: 'review' }, { id: 'released', label: 'Sent to students', icon: 'send' }, { id: 'all', label: 'All', icon: 'history' }]} />
      <LoadState error={error} loading={loading && !data} />
      <Card flush>
        <DataTable onRowClick={(r) => nav(`/review/${r.id}`)}
          empty={tab === 'review' ? 'Nothing is waiting for you. New worksheets appear here two days before each exam.' : 'No worksheets yet.'}
          columns={[
            { key: 'subject', label: 'Subject' },
            { key: 'class', label: 'Class', render: (r) => <ClassChip name={r.class} suffix={r.sections ? ` · ${r.sections}` : ''} /> },
            { key: 'exam_date', label: 'Exam' },
            { key: 'exam_code', label: 'Exam ID', mono: true },
            { key: 'version', label: 'Version', render: (r) => `v${r.version}` },
            { key: 'questions', label: 'Questions', align: 'right' },
            { key: 'validation', label: 'Validation' },
            { key: 'status', label: 'Status', render: (r) => <StatusBadge status={r.status} /> },
          ]} rows={data ?? []} />
      </Card>
    </Layout>
  );
}
