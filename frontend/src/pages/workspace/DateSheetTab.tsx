import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api';
import { Dialog, useAction, useIsAdmin } from '../../app';
import { Button, Card, DataTable, StatusBadge } from '../../components/ds';
import { UploadSteps } from '../../components/UploadSteps';
import type { ExamRow, Workspace } from '../ClassWorkspace';

type DS = Workspace['datesheet'];

export default function DateSheetTab({ ws, onChange, reload }: { ws: Workspace; onChange: (w: Workspace) => void; reload: () => void }) {
  const admin = useIsAdmin();
  const nav = useNavigate();
  const { busy, run } = useAction();
  const [edit, setEdit] = useState<ExamRow | null>(null);
  const [replacing, setReplacing] = useState(false);
  const ds = ws.datesheet;
  const base = `/api/classes/${ws.id}`;
  const afterDs = (d: DS | undefined) => { if (d) onChange({ ...ws, datesheet: d }); reload(); };

  async function upload(files: File[]) { afterDs(await run('ds-up', () => api.upload<DS>(`${base}/datesheet`, files))); setReplacing(false); }
  async function confirm() { afterDs(await run('ds-ok', () => api.post<DS>(`${base}/datesheet/confirm`), 'Exam dates saved.')); }
  async function discard() { afterDs(await run('ds-x', () => api.post<DS>(`${base}/datesheet/discard`))); }
  async function generate(e: ExamRow) {
    const r = await run('gen-' + e.id, () => api.post(`/api/exams/${e.id}/generate`),
      `Making the ${e.subject} worksheet now. It will appear in “Check worksheets” in a minute.`);
    if (r) setTimeout(reload, 3000);
  }
  async function remove(e: ExamRow) {
    if (!window.confirm(`Remove the ${e.subject} exam on ${e.exam_date}? No worksheet will be sent for it.`)) return;
    afterDs(await run('rm', () => api.del<DS>(`/api/exams/${e.id}`), `${e.subject} removed.`));
  }

  const p = ds.pending;
  const showUpload = admin && !p && (!ds.exams.length || replacing);

  return <>
    {showUpload ? (
      <Card title={ds.exams.length ? 'Upload a new date sheet' : 'Step 1 · Upload the exam dates'}
        actions={replacing ? <Button variant="quiet" size="sm" onClick={() => setReplacing(false)}>Cancel</Button> : null}>
        <UploadSteps
          template={{ url: `${base}/datesheet/template.xlsx`, fileName: `DateSheet_${ws.name.replace(' ', '_')}.xlsx` }}
          fillHint={ws.subject_count ? 'One row per exam: subject and exam date. Your subjects are already listed.' : 'One row per exam: subject and exam date.'}
          uploadTitle="Upload your date sheet" uploadHint="Excel or CSV. You can also upload the school’s own date sheet if it has Subject and Date columns."
          accept=".xlsx,.xlsm,.csv" icon="calendar" onFiles={upload} busy={busy === 'ds-up'}
          extra={ds.exams.length ? <div className="help">Exams that are missing from the new file will be removed, and changed dates get new worksheet dates.</div> : null} />
      </Card>
    ) : null}

    {p ? (
      <Card title="Is this right?">
        <div className="stack">
          <div>We found <b>{p.rows.length} exam{p.rows.length === 1 ? '' : 's'}</b> in <span className="psa-mono">{p.file}</span>. Please check the dates.
            Each worksheet is sent on the date in the last column.</div>
          {p.issues.length ? <div className="issue-box is-warning"><b>{p.issues.length} row{p.issues.length > 1 ? 's were' : ' was'} skipped:</b>
            <ul>{p.issues.map((i) => <li key={i.row}>{i.message}</li>)}</ul></div> : null}
          <DataTable columns={[
            { key: 'subject_name', label: 'Subject' },
            { key: 'sections', label: 'Section', render: (r) => r.sections || 'All' },
            { key: 'exam_date_label', label: 'Exam date', render: (r) => <>{r.exam_date_label}{r.exam_time ? <div className="muted-sm">{r.exam_time}</div> : null}</> },
            { key: 'trigger', label: 'Worksheet sent on', render: (r) => r.past ? <span className="psa-muted">Exam already over</span>
              : r.late ? <span>{r.trigger} <span className="muted-sm">(too soon, send it by hand)</span></span> : <b>{r.trigger}</b> },
          ]} rows={p.rows.map((r) => ({ ...r, id: r.exam_code }))} />
          <div className="row">
            <Button variant="primary" icon="check" onClick={confirm} disabled={!p.rows.length || busy === 'ds-ok'}>Yes, save these dates</Button>
            <Button variant="quiet" onClick={discard}>No, cancel</Button>
          </div>
        </div>
      </Card>
    ) : null}

    {ds.exams.length ? (
      <Card title="Exam dates" flush actions={admin && !p && !replacing ? <Button size="sm" icon="upload" onClick={() => setReplacing(true)}>Upload new date sheet</Button> : null}>
        <DataTable
          columns={[
            { key: 'subject', label: 'Subject' },
            { key: 'sections', label: 'Section' },
            { key: 'exam_date', label: 'Exam date', render: (r) => <>{r.exam_date}{r.time !== '—' ? <div className="muted-sm">{r.time}</div> : null}</> },
            { key: 'trigger', label: 'Worksheet sent on', render: (r) => r.past ? <span className="psa-muted">Exam over</span> : r.trigger },
            { key: 'status', label: 'Worksheet', render: (r) => <div className="stack-sm" style={{ gap: 4, alignItems: 'flex-start' }}>
              {r.worksheet_id ? <span title={r.job_error || undefined}><StatusBadge status={r.status} /></span>
                : r.status === 'failed' ? <span title={r.job_error || undefined}><StatusBadge status="failed">Could not make it</StatusBadge></span>
                  : r.in_progress ? <StatusBadge status="running">Being prepared…</StatusBadge>
                    : r.past ? null : <span className="muted-sm">Not made yet</span>}
              {r.reused ? <span className="muted-sm">Reused, no AI cost</span> : null}
              <div className="row" style={{ gap: 0, marginLeft: -12 }}>
                {r.worksheet_id ? <Button variant="quiet" size="sm" onClick={() => nav(`/review/${r.worksheet_id}`)}>Open</Button>
                  : admin && !r.past && !r.in_progress ? <Button variant="quiet" size="sm" disabled={busy === 'gen-' + r.id} onClick={() => generate(r)} title="Don’t wait for the date: make this worksheet now">Make it now</Button> : null}
                {admin ? <Button variant="quiet" size="sm" icon="edit" aria-label="Change" title="Change this exam" onClick={() => setEdit(r)} /> : null}
                {admin ? <Button variant="quiet" size="sm" icon="trash" aria-label="Remove" title="Remove this exam" onClick={() => remove(r)} /> : null}
              </div>
            </div> },
          ]}
          rows={ds.exams} />
      </Card>
    ) : null}
    {ds.exams.length && !p ? <div className="help">Worksheets are sent <b>{ws.lead_days} days before</b> each exam. Use <b>Make it now</b> if you don’t want to wait.</div> : null}

    {edit ? <EditExam exam={edit} ws={ws} onClose={() => setEdit(null)} onSaved={(d) => { setEdit(null); afterDs(d); }} /> : null}
  </>;
}

function EditExam({ exam, ws, onClose, onSaved }: { exam: ExamRow; ws: Workspace; onClose: () => void; onSaved: (d: DS) => void }) {
  const [f, setF] = useState({ subject_name: exam.subject, sections: exam.sections === 'All' ? '' : exam.sections, exam_date: exam.exam_date_iso, exam_time: exam.time === '—' ? '' : exam.time });
  const { busy, run } = useAction();
  async function save() {
    const d = await run('save', () => api.patch<DS>(`/api/exams/${exam.id}`, f), 'Exam changed. Its worksheet date was updated.');
    if (d) onSaved(d);
  }
  return (
    <Dialog title={`Change ${exam.subject} exam`} onClose={onClose}
      footer={<><Button variant="quiet" onClick={onClose}>Cancel</Button><Button variant="primary" onClick={save} disabled={busy === 'save'}>Save</Button></>}>
      <div className="grid-2">
        <label className="field"><span>Exam date</span><input className="input" type="date" value={f.exam_date} onChange={(e) => setF({ ...f, exam_date: e.target.value })} /></label>
        <label className="field"><span>Time</span><input className="input" placeholder="09:00" value={f.exam_time} onChange={(e) => setF({ ...f, exam_time: e.target.value })} /></label>
        <label className="field"><span>Subject</span><input className="input" value={f.subject_name} onChange={(e) => setF({ ...f, subject_name: e.target.value })} /></label>
        <label className="field"><span>Sections</span><input className="input" placeholder={`All (${ws.sections})`} value={f.sections} onChange={(e) => setF({ ...f, sections: e.target.value })} /></label>
      </div>
      <div className="help">If a worksheet was already made for the old date and not yet sent, it is cancelled and a new one is made for the new date.</div>
    </Dialog>
  );
}
