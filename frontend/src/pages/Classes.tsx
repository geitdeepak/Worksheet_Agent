import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { Dialog, Layout, LoadState, useAction, useClassList, useIsAdmin, useLoad } from '../app';
import { Banner, Button, ClassCard, Icon } from '../components/ds';
import { ImportPreview, UploadSteps, type ImportResult } from '../components/UploadSteps';

export interface ClassCardData {
  id: number; name: string; grade: string; academic_year: string; sections: string; students: number; subjects: number;
  exams: number; automation: 'draft' | 'active' | 'paused'; next_trigger: string | null;
}

export default function Classes() {
  const { data, error, loading, reload } = useLoad<ClassCardData[]>('/api/classes');
  const { refresh } = useClassList();
  const nav = useNavigate();
  const admin = useIsAdmin();
  const [open, setOpen] = useState(false);
  const [bulk, setBulk] = useState(false);
  const [form, setForm] = useState({ name: '', academic_year: '2026–27', sections: 'A' });
  const { busy, run } = useAction();

  async function create() {
    const c = await run('create', () => api.post<ClassCardData>('/api/classes', form), `${form.name} created. Follow the 4 steps to set it up.`);
    if (c) { setOpen(false); refresh(); reload(); nav(`/classes/${c.id}`); }
  }

  return (
    <Layout active="classes" title="Classes" crumb="Set up each class once. After that, worksheets are made and sent automatically."
      actions={admin ? <>
        {data?.length ? <Button icon="users" onClick={() => setBulk(true)}>Upload students for all classes</Button> : null}
        <Button variant="primary" icon="plus" onClick={() => setOpen(true)}>Add a class</Button></> : null}>
      <LoadState error={error} loading={loading && !data} />
      {data && data.length === 0 ? (
        <Banner title="Start by adding your first class" action={admin ? <Button variant="primary" size="sm" onClick={() => setOpen(true)}>Add a class</Button> : null}>
          Then follow four simple steps: exam dates, exam syllabus, study material and students.
        </Banner>
      ) : null}
      <div className="grid-cards">
        {data?.map((c) => (
          <ClassCard key={c.id} name={c.name} year={c.academic_year} sections={c.sections} students={c.students}
            subjects={c.subjects} exams={c.exams} automation={c.automation} nextTrigger={c.next_trigger}
            onOpen={() => nav(`/classes/${c.id}`)} />
        ))}
        {admin && data?.length ? (
          <button type="button" className="class-card-add" onClick={() => setOpen(true)}>
            <span style={{ display: 'grid', justifyItems: 'center', gap: 8 }}><Icon name="plus" size={28} />Add a class</span>
          </button>
        ) : null}
      </div>
      {open ? (
        <Dialog title="Add a class" onClose={() => setOpen(false)}
          footer={<><Button variant="quiet" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" onClick={create} disabled={!form.name.trim() || busy === 'create'}>Add class</Button></>}>
          <label className="field"><span>Class name</span>
            <input className="input" placeholder="Class 9" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus />
            <small>For example “Class 9”. The number is used to match rows in your Excel files.</small>
          </label>
          <div className="grid-2">
            <label className="field"><span>Sections</span>
              <input className="input" placeholder="A, B" value={form.sections} onChange={(e) => setForm({ ...form, sections: e.target.value })} />
              <small>Separate with commas.</small></label>
            <label className="field"><span>Academic year</span>
              <input className="input" value={form.academic_year} onChange={(e) => setForm({ ...form, academic_year: e.target.value })} /></label>
          </div>
        </Dialog>
      ) : null}
      {bulk ? <SchoolBulkUpload onClose={() => setBulk(false)} onDone={() => { setBulk(false); reload(); refresh(); }} /> : null}
    </Layout>
  );
}

function SchoolBulkUpload({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const { busy, run } = useAction();
  async function check(f: File) {
    const r = await run('prev', () => api.upload<{ import: ImportResult }>('/api/students/upload', [f], 'file', { dry_run: 'true' }));
    if (r) { setFile(f); setPreview(r.import); }
  }
  async function confirm() {
    const r = await run('save', () => api.upload('/api/students/upload', [file!], 'file'), 'Students saved to their classes.');
    if (r) onDone();
  }
  return (
    <Dialog title="Upload students for all classes" onClose={onClose} wide>
      {!preview ? <>
        <div>Upload one Excel file with every student in the school. Each student is added to the right class using the <b>Class</b> column.</div>
        <UploadSteps template={{ url: '/api/students/template.xlsx', fileName: 'Students_all_classes.xlsx' }}
          fillHint="One row per student, with their class, section, email and WhatsApp number."
          uploadTitle="Upload the school student list" uploadHint="Excel or CSV. Existing students are updated; new ones are added."
          accept=".xlsx,.csv" icon="users" onFiles={(f) => check(f[0])} busy={busy === 'prev'} />
      </> : (
        <ImportPreview result={preview} fileName={file!.name} showClass onConfirm={confirm} onCancel={() => { setPreview(null); setFile(null); }} busy={busy === 'save'} />
      )}
    </Dialog>
  );
}
