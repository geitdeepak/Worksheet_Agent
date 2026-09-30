import { useEffect, useState } from 'react';
import { api, openFile } from '../../api';
import { useAction, useIsAdmin } from '../../app';
import { Banner, Button, Card, DataTable } from '../../components/ds';
import { UploadSteps } from '../../components/UploadSteps';
import type { SyllabusEntry, Workspace } from '../ClassWorkspace';

type SY = Workspace['syllabus'];

export default function SyllabusTab({ ws, onChange, reload }: { ws: Workspace; onChange: (w: Workspace) => void; reload: () => void }) {
  const admin = useIsAdmin();
  const { busy, run } = useAction();
  const sy = ws.syllabus;
  const base = `/api/classes/${ws.id}/syllabus`;
  const [draft, setDraft] = useState<SyllabusEntry[]>(sy.pending?.entries ?? []);
  const [dirty, setDirty] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  useEffect(() => { setDraft(sy.pending?.entries ?? []); setDirty(false); }, [sy.pending]);

  const set = (s: SY | undefined) => { if (s) { onChange({ ...ws, syllabus: s }); reload(); } };
  const examSubjects = Array.from(new Set(ws.datesheet.exams.map((e) => e.subject)));
  const missingInDraft = examSubjects.filter((s) => !draft.some((d) => d.subject.toLowerCase() === s.toLowerCase() && d.text.trim()));

  async function upload(files: File[]) { set(await run('up', () => api.upload<SY>(base, files))); setReplacing(false); }
  async function saveDraft() {
    const r = await run('save', () => api.put<SY>(`${base}/pending`, { entries: draft.map(({ subject, text }) => ({ subject, text })) }));
    if (r) { set(r); setDirty(false); }
    return r;
  }
  async function confirm() {
    if (dirty && !(await saveDraft())) return;
    set(await run('ok', () => api.post<SY>(`${base}/confirm`), 'Syllabus saved. Worksheets will only use these chapters.'));
  }
  async function discard() { set(await run('x', () => api.post<SY>(`${base}/discard`))); }
  const setText = (i: number, text: string) => { setDraft(draft.map((d, j) => j === i ? { ...d, text } : d)); setDirty(true); };

  const p = sy.pending;
  const showUpload = admin && !p && (!sy.entries.length || replacing);

  return <>
    {showUpload ? (
      <Card title={sy.entries.length ? 'Upload a new syllabus' : 'Step 2 · Upload the exam syllabus'}
        actions={replacing ? <Button variant="quiet" size="sm" onClick={() => setReplacing(false)}>Cancel</Button> : null}>
        <UploadSteps
          template={{ url: `${base}/template.xlsx`, fileName: `Syllabus_${ws.name.replace(' ', '_')}.xlsx` }}
          fillHint={examSubjects.length ? `Write the chapters for each subject (${examSubjects.join(', ')}). The subjects are already listed.` : 'Write the chapters for each subject, e.g. “Chapter 1, 2 and 5”.'}
          uploadTitle="Upload the syllabus" uploadHint="The Excel template, or your school’s own syllabus notice as PDF or Word."
          accept=".pdf,.docx,.xlsx,.csv,.txt" icon="scope" onFiles={upload} busy={busy === 'up'} />
        <div className="help" style={{ marginTop: 16 }}><b>Why this matters:</b> every school sets its own syllabus for each exam.
          Worksheets only use the chapters you list here. Any question outside them is stopped before it reaches students.</div>
      </Card>
    ) : null}

    {p ? (
      <Card title="Check the syllabus for each subject">
        <div className="stack">
          <div>This is what we read from <span className="psa-mono">{p.file}</span>. You can correct the text below before saving.
            Write chapters like “Chapter 1, 2” and anything left out on its own line, like “Chapter 6 is not included”.</div>
          {missingInDraft.length ? <Banner tone="warning" title="Some subjects have no syllabus yet">
            {missingInDraft.join(', ')}. Add them below.</Banner> : null}
          {draft.map((d, i) => (
            <label key={d.subject + i} className="field">
              <span>{d.subject}{d.chapters.length ? ` · chapters ${d.chapters.join(', ')}` : ''}{d.excluded_chapters?.length ? ` · not ${d.excluded_chapters.join(', ')}` : ''}</span>
              <textarea className="textarea" rows={Math.min(8, Math.max(3, d.text.split('\n').length + 1))} value={d.text} readOnly={!admin}
                onChange={(e) => setText(i, e.target.value)} placeholder="Chapter 1 Number Systems, Chapter 2 Polynomials" />
            </label>
          ))}
          {admin && missingInDraft.length ? <div className="row">
            {missingInDraft.map((s) => <Button key={s} size="sm" icon="plus" onClick={() => { setDraft([...draft, { subject: s, text: '', chapters: [], topics: [] }]); setDirty(true); }}>Add {s}</Button>)}
          </div> : null}
          <div><Button variant="quiet" size="sm" onClick={() => setShowRaw(!showRaw)}>{showRaw ? 'Hide' : 'Show'} the original text from the file</Button>
            {showRaw ? <div className="passage" style={{ maxHeight: 260, overflow: 'auto', marginTop: 8 }}>{p.raw || 'No text could be read.'}</div> : null}</div>
          <div className="row">
            <Button variant="primary" icon="check" onClick={confirm} disabled={!draft.length || busy === 'ok'}>Save syllabus</Button>
            <Button variant="quiet" onClick={discard}>Cancel</Button>
          </div>
        </div>
      </Card>
    ) : null}

    {!p && sy.entries.length ? (
      <Card title="Exam syllabus" flush actions={<div className="row">
        {sy.file ? <Button variant="quiet" size="sm" icon="download" onClick={() => openFile(`${base}/file`, sy.file!)}>Uploaded file</Button> : null}
        {admin && !replacing ? <Button size="sm" icon="upload" onClick={() => setReplacing(true)}>Upload new syllabus</Button> : null}</div>}>
        <DataTable columns={[
          { key: 'subject', label: 'Subject', width: 150 },
          { key: 'chapters', label: 'Chapters used', render: (r) => r.chapters.length ? r.chapters.join(', ') : 'By topic', width: 120 },
          { key: 'text', label: 'Syllabus', render: (r) => <span className="muted-sm" style={{ whiteSpace: 'pre-wrap' }}>{r.text.length > 240 ? r.text.slice(0, 240) + '…' : r.text}</span> },
        ]} rows={sy.entries.map((e) => ({ ...e, id: e.subject }))} />
      </Card>
    ) : null}
    {sy.confirmed && sy.missing.length && !p ? <Banner tone="danger" title="Some exams have no syllabus">
      {sy.missing.join(', ')} {sy.missing.length > 1 ? 'are' : 'is'} on the date sheet but not in the syllabus. Upload a new syllabus that includes {sy.missing.length > 1 ? 'them' : 'it'}.</Banner> : null}
  </>;
}
