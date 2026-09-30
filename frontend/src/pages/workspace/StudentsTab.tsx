import { useState } from 'react';
import { api } from '../../api';
import { Dialog, LoadState, useAction, useIsAdmin, useLoad } from '../../app';
import { Button, Card, DataTable, StatusBadge, Switch } from '../../components/ds';
import { ImportPreview, UploadSteps, type ImportResult } from '../../components/UploadSteps';
import type { Workspace } from '../ClassWorkspace';

interface Student { id: number; student_code: string; name: string; section: string; email: string; email_valid: boolean; whatsapp: string; has_whatsapp: boolean; active: boolean }
interface Resp { students: Student[]; summary: { total: number; by_section: Record<string, number>; invalid_email: number; missing_whatsapp: number } }

export default function StudentsTab({ ws, reload: reloadWs }: { ws: Workspace; reload: () => void }) {
  const admin = useIsAdmin();
  const { data, error, loading, reload } = useLoad<Resp>(`/api/classes/${ws.id}/students`, [ws.id]);
  const { busy, run } = useAction();
  const [file, setFile] = useState<File | null>(null);
  const [replace, setReplace] = useState(false);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [edit, setEdit] = useState<Student | 'new' | null>(null);
  const [filter, setFilter] = useState('');
  const url = `/api/classes/${ws.id}/students/upload`;

  async function check(f: File, rep = replace) {
    const r = await run('prev', () => api.upload<{ import: ImportResult }>(url, [f], 'file', { replace: String(rep), dry_run: 'true' }));
    if (r) { setFile(f); setPreview(r.import); }
  }
  async function confirm() {
    const r = await run('save', () => api.upload<{ import: ImportResult & { added: number } }>(url, [file!], 'file', { replace: String(replace) }),
      'Student list saved.');
    if (r) { setPreview(null); setFile(null); setShowUpload(false); reload(); reloadWs(); }
  }
  function cancel() { setPreview(null); setFile(null); }

  const students = data?.students ?? [];
  const rows = students.filter((s) => !filter || `${s.student_code} ${s.name} ${s.section}`.toLowerCase().includes(filter.toLowerCase()));
  const uploadOpen = admin && !preview && (students.length === 0 || showUpload);

  return <>
    <LoadState error={error} loading={loading && !data} />
    {uploadOpen ? (
      <Card title={students.length ? 'Upload students in bulk' : 'Step 4 · Upload your students'}
        actions={students.length ? <Button variant="quiet" size="sm" onClick={() => setShowUpload(false)}>Close</Button> : null}>
        <UploadSteps
          template={{ url: `/api/students/template.xlsx?class_id=${ws.id}`, fileName: `Students_${ws.name.replace(' ', '_')}.xlsx` }}
          fillHint="One row per student: ID, name, section, email and WhatsApp number. You can paste from your school register."
          uploadTitle="Upload the student list" uploadHint="Excel or CSV. Students already in the list are updated, new ones are added."
          accept=".xlsx,.csv" icon="users" onFiles={(f) => check(f[0])} busy={busy === 'prev'} />
      </Card>
    ) : null}

    {preview && file ? (
      <ImportPreview result={preview} fileName={file.name} onConfirm={confirm} onCancel={cancel} busy={busy === 'save'}>
        {students.length ? <Switch on={replace} label="Also deactivate students who are not in this file"
          description="Use this when the file is your complete, current list (for example, at the start of a new term)."
          onChange={(v) => { setReplace(v); check(file, v); }} /> : null}
      </ImportPreview>
    ) : null}

    {students.length ? (
      <Card title={`Students · ${data!.summary.total}`} flush actions={<div className="row">
        <input className="input" style={{ width: 180 }} placeholder="Search name or ID" value={filter} onChange={(e) => setFilter(e.target.value)} />
        {admin && !uploadOpen && !preview ? <Button size="sm" variant="primary" icon="upload" onClick={() => setShowUpload(true)}>Upload in bulk</Button> : null}
        {admin ? <Button size="sm" icon="plus" onClick={() => setEdit('new')}>Add one</Button> : null}</div>}>
        <div className="psa-card-body muted-sm" style={{ paddingBottom: 8 }}>
          {Object.entries(data!.summary.by_section).map(([k, v]) => `Section ${k}: ${v}`).join(' · ')}
          {data!.summary.invalid_email ? <span style={{ color: 'var(--danger)' }}> · {data!.summary.invalid_email} without a valid email (they won’t get worksheets)</span> : null}
          {data!.summary.missing_whatsapp ? ` · ${data!.summary.missing_whatsapp} without WhatsApp` : ''}
        </div>
        <DataTable empty="No students match your search." onRowClick={admin ? (s) => setEdit(s) : undefined}
          columns={[
            { key: 'student_code', label: 'Student ID', mono: true }, { key: 'name', label: 'Name' }, { key: 'section', label: 'Section' },
            { key: 'email', label: 'Email', mono: true, render: (s) => s.email_valid ? s.email : <span style={{ color: 'var(--danger)' }}>{s.email === '—' ? 'Missing' : `${s.email} · check`}</span> },
            { key: 'whatsapp', label: 'WhatsApp', mono: true },
            { key: 'active', label: 'Status', render: (s) => s.active ? <StatusBadge status="active" /> : <StatusBadge status="cancelled">Inactive</StatusBadge> },
          ]} rows={rows} />
      </Card>
    ) : null}
    {students.length ? <div className="muted-sm">Click a student to change their details. Contact details are partly hidden for privacy.</div> : null}
    {edit ? <EditStudent ws={ws} student={edit === 'new' ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload(); reloadWs(); }} /> : null}
  </>;
}

function EditStudent({ ws, student, onClose, onSaved }: { ws: Workspace; student: Student | null; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ student_code: student?.student_code ?? '', name: student?.name ?? '', section: student?.section ?? ws.sections.split(',')[0].trim(), email: '', whatsapp: '', active: student?.active ?? true });
  const { busy, run } = useAction();
  async function save() {
    const body: Record<string, unknown> = { name: f.name, section: f.section, active: f.active };
    if (f.email.trim() || !student) body.email = f.email;
    if (f.whatsapp.trim() || !student) body.whatsapp = f.whatsapp;
    const r = await run('save', () => student ? api.patch(`/api/students/${student.id}`, body)
      : api.post(`/api/classes/${ws.id}/students`, { ...body, student_code: f.student_code }), 'Student saved.');
    if (r) onSaved();
  }
  return (
    <Dialog title={student ? `${student.name}` : 'Add one student'} onClose={onClose}
      footer={<><Button variant="quiet" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={busy === 'save'} onClick={save}>Save</Button></>}>
      <div className="grid-2">
        {!student ? <label className="field"><span>Student ID</span><input className="input" value={f.student_code} onChange={(e) => setF({ ...f, student_code: e.target.value })} /></label> : null}
        <label className="field"><span>Name</span><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label className="field"><span>Section</span>
          <select className="select" value={f.section} onChange={(e) => setF({ ...f, section: e.target.value })}>
            {ws.sections.split(',').map((s) => <option key={s.trim()}>{s.trim()}</option>)}</select></label>
        <label className="field"><span>Email</span><input className="input" type="email" placeholder={student ? `${student.email} (leave blank to keep)` : ''} value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
        <label className="field"><span>WhatsApp</span><input className="input" placeholder={student ? `${student.whatsapp} (leave blank to keep)` : '98765 43210'} value={f.whatsapp} onChange={(e) => setF({ ...f, whatsapp: e.target.value })} /></label>
      </div>
      {student ? <Switch on={f.active} onChange={(v) => setF({ ...f, active: v })} label="Active" description="Inactive students receive nothing." /> : null}
    </Dialog>
  );
}
