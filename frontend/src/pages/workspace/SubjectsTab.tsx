import { useState } from 'react';
import { api, openFile } from '../../api';
import { Dialog, LoadState, useAction, useIsAdmin, useLoad } from '../../app';
import { Banner, Button, Card, DataTable, StatusBadge, UploadDropzone } from '../../components/ds';
import type { Workspace } from '../ClassWorkspace';

interface Doc { id: number; filename: string; kind: 'syllabus' | 'chapter'; chapter: string | null; version: number; active: boolean; pages: number; chars: number; extraction: string; uploaded_at: string }
interface Subject { id: number; name: string; documents: Doc[]; active_files: number; has_syllabus: boolean; readable: boolean }

export default function SubjectsTab({ ws, reload: reloadWs }: { ws: Workspace; reload: () => void }) {
  const admin = useIsAdmin();
  const { data, setData, error, loading, reload } = useLoad<{ subjects: Subject[]; missing_from_datesheet: string[] }>(`/api/classes/${ws.id}/subjects`, [ws.id]);
  const { busy, run } = useAction();
  const [adding, setAdding] = useState<string | null>(null);
  const [showOld, setShowOld] = useState(false);
  const [editDoc, setEditDoc] = useState<Doc | null>(null);

  async function addSubject(name: string) {
    const r = await run('add', () => api.post<Subject>(`/api/classes/${ws.id}/subjects`, { name }), `${name} added.`);
    if (r) { setAdding(null); reload(); reloadWs(); }
  }
  async function upload(s: Subject, files: File[]) {
    const r = await run('up-' + s.id, () => api.upload<Subject>(`/api/subjects/${s.id}/documents`, files, 'files'));
    if (r && data) {
      setData({ ...data, subjects: data.subjects.map((x) => x.id === s.id ? r : x) });
      reloadWs();
    }
  }
  async function patchDoc(d: Doc, body: Partial<Doc>) {
    const r = await run('doc', () => api.patch<Subject>(`/api/documents/${d.id}`, body));
    if (r && data) { setData({ ...data, subjects: data.subjects.map((x) => x.id === r.id ? r : x) }); reloadWs(); }
  }
  async function removeSubject(s: Subject) {
    if (!window.confirm(`Remove ${s.name} and its ${s.documents.length} files from ${ws.name}?`)) return;
    const r = await run('rm', () => api.del(`/api/subjects/${s.id}`), `${s.name} removed.`);
    if (r) { reload(); reloadWs(); }
  }

  return <>
    <LoadState error={error} loading={loading && !data} />
    {data?.missing_from_datesheet.length ? (
      <Banner tone="warning" title="Subjects on the date sheet that are not set up"
        action={admin ? <div className="row">{data.missing_from_datesheet.map((n) => <Button key={n} size="sm" icon="plus" onClick={() => addSubject(n)}>{n}</Button>)}</div> : null}>
        Worksheets for these exams can’t be generated until the subject exists and has chapter PDFs.
      </Banner>
    ) : null}
    <div className="help"><b>Step 3 · Study material.</b> For each subject, upload the textbook chapters as PDFs. Questions are made
      only from these files. <b>Tip:</b> name files with the chapter number, like <span className="psa-mono">Chapter-03.pdf</span>,
      so they match the exam syllabus automatically.</div>
    {data?.subjects.map((s) => {
      const docs = s.documents.filter((d) => showOld || d.active);
      return (
        <Card key={s.id} title={s.name} flush actions={<div className="row">
          {s.readable ? <StatusBadge status="completed">{s.active_files} files</StatusBadge> : <StatusBadge status="failed">No readable PDFs</StatusBadge>}
          {admin ? <Button variant="quiet" size="sm" icon="trash" aria-label={`Remove ${s.name}`} onClick={() => removeSubject(s)} /> : null}
        </div>}>
          <div className="psa-card-body">
            <UploadDropzone title={`Upload ${s.name} PDFs`} icon="file" accept=".pdf" multiple busy={busy === 'up-' + s.id} disabled={!admin}
              hint="Syllabus and chapter PDFs. Drop several at once." onFiles={admin ? (f) => upload(s, f) : undefined} />
          </div>
          <DataTable empty="No files yet."
            columns={[
              { key: 'filename', label: 'File', mono: true, render: (d) => <a href="#" onClick={(e) => { e.preventDefault(); openFile(`/api/documents/${d.id}/file`); }}>{d.filename}</a> },
              { key: 'kind', label: 'Type', render: (d) => d.kind === 'syllabus' ? 'Syllabus' : 'Chapter' },
              { key: 'chapter', label: 'Chapter', render: (d) => d.chapter || <span className="psa-muted">—</span> },
              { key: 'version', label: 'Version', render: (d) => `v${d.version}` },
              { key: 'pages', label: 'Pages', align: 'right' },
              { key: 'uploaded_at', label: 'Uploaded' },
              { key: 'status', label: 'Status', render: (d) => !d.active ? <StatusBadge status="cancelled">Inactive</StatusBadge>
                : d.extraction === 'ok' ? <StatusBadge status="active">Ready</StatusBadge>
                  : <span title={d.extraction === 'garbled' ? 'This Hindi PDF uses an old (non-Unicode) font, so its text can’t be read. Upload a Unicode PDF or a scanned copy.' : 'No text could be read from this PDF.'}>
                    <StatusBadge status="failed">{d.extraction === 'empty' ? 'No text' : d.extraction === 'garbled' ? 'Old Hindi font' : 'Unreadable'}</StatusBadge></span> },
              ...(admin ? [{ key: 'act', label: '', render: (d: Doc) => <div className="row" style={{ gap: 2, flexWrap: 'nowrap' }}>
                <Button variant="quiet" size="sm" icon="edit" aria-label="Edit" onClick={() => setEditDoc(d)} />
                <Button variant="quiet" size="sm" onClick={() => patchDoc(d, { active: !d.active })}>{d.active ? 'Deactivate' : 'Activate'}</Button></div> }] : []),
            ]}
            rows={docs} />
        </Card>
      );
    })}
    <div className="row">
      {admin ? <Button icon="plus" onClick={() => setAdding('')}>Add subject</Button> : null}
      {data?.subjects.some((s) => s.documents.some((d) => !d.active)) ? <Button variant="quiet" size="sm" onClick={() => setShowOld(!showOld)}>{showOld ? 'Hide' : 'Show'} old versions</Button> : null}
    </div>
    {adding !== null ? (
      <Dialog title="Add subject" onClose={() => setAdding(null)}
        footer={<><Button variant="quiet" onClick={() => setAdding(null)}>Cancel</Button><Button variant="primary" disabled={!adding.trim()} onClick={() => addSubject(adding.trim())}>Add</Button></>}>
        <label className="field"><span>Subject name</span><input className="input" autoFocus value={adding} onChange={(e) => setAdding(e.target.value)} placeholder="Mathematics" />
          <small>Use the same name as on the date sheet.</small></label>
      </Dialog>
    ) : null}
    {editDoc ? <EditDoc doc={editDoc} onClose={() => setEditDoc(null)} onSave={(b) => { patchDoc(editDoc, b); setEditDoc(null); }} /> : null}
  </>;
}

function EditDoc({ doc, onClose, onSave }: { doc: Doc; onClose: () => void; onSave: (b: Partial<Doc>) => void }) {
  const [kind, setKind] = useState(doc.kind);
  const [chapter, setChapter] = useState(doc.chapter || '');
  return (
    <Dialog title={doc.filename} onClose={onClose}
      footer={<><Button variant="quiet" onClick={onClose}>Cancel</Button><Button variant="primary" onClick={() => onSave({ kind, chapter: chapter || null })}>Save</Button></>}>
      <div className="grid-2">
        <label className="field"><span>Type</span>
          <select className="select" value={kind} onChange={(e) => setKind(e.target.value as Doc['kind'])}>
            <option value="chapter">Chapter</option><option value="syllabus">Full syllabus</option></select></label>
        <label className="field"><span>Chapter</span><input className="input" placeholder="Chapter 3" value={chapter} onChange={(e) => setChapter(e.target.value)} />
          <small>Its number is matched against the exam syllabus.</small></label>
      </div>
    </Dialog>
  );
}
