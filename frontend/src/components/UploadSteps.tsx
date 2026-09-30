/* Guided upload: ① download a ready-made template ② fill it in ③ upload. Used by every bulk upload. */
import type { ReactNode } from 'react';
import { openFile } from '../api';
import { useToast } from '../app';
import { Button, DataTable, Icon, StatusBadge, UploadDropzone, type IconName } from './ds';

export function UploadSteps(p: {
  template?: { url: string; fileName: string; label?: string };
  fillHint: ReactNode; accept: string; uploadTitle: string; uploadHint: string; icon: IconName;
  onFiles: (files: File[]) => void; busy?: boolean; disabled?: boolean; multiple?: boolean; extra?: ReactNode;
}) {
  const toast = useToast();
  const steps: { n: number; title: string; body: ReactNode }[] = [];
  if (p.template) {
    steps.push({
      n: 1, title: 'Download the template',
      body: <Button size="sm" icon="download" onClick={() => openFile(p.template!.url, p.template!.fileName).catch((e) => toast('danger', e.message))}>
        {p.template.label ?? 'Download Excel template'}</Button>,
    });
  }
  steps.push({ n: steps.length + 1, title: 'Fill it in', body: <span className="muted-sm">{p.fillHint}</span> });
  steps.push({ n: steps.length + 1, title: 'Upload it here', body: <span className="muted-sm">You’ll see a preview first. Nothing is saved until you confirm.</span> });
  return (
    <div className="stack">
      <ol className="steps">
        {steps.map((s) => <li key={s.n}><span className="step-n">{s.n}</span><div><div className="step-t">{s.title}</div>{s.body}</div></li>)}
      </ol>
      <UploadDropzone title={p.uploadTitle} hint={p.uploadHint} icon={p.icon} accept={p.accept} multiple={p.multiple}
        onFiles={p.onFiles} busy={p.busy} disabled={p.disabled} />
      {p.extra}
    </div>
  );
}

export interface ImportResult {
  new: number; updated: number; unchanged: number; deactivated: number; errors: number; warnings: number;
  issues: { row: number; message: string; warning?: boolean }[];
  rows: { student_code: string; name: string; section: string; class: string; email: string; whatsapp: string; active: boolean; change: string }[];
  classes?: { id: number; name: string; new: number; updated: number; unchanged: number; deactivated: number }[];
}

const CHANGE: Record<string, [string, string]> = {
  new: ['completed', 'New'], updated: ['running', 'Updated'], deactivated: ['cancelled', 'Deactivated'],
};

export function ImportPreview({ result, fileName, showClass, onConfirm, onCancel, busy, children }: {
  result: ImportResult; fileName: string; showClass?: boolean; onConfirm: () => void; onCancel: () => void; busy?: boolean; children?: ReactNode;
}) {
  const nothing = result.new + result.updated + result.deactivated === 0;
  const errors = result.issues.filter((i) => !i.warning);
  const warnings = result.issues.filter((i) => i.warning);
  return (
    <div className="preview">
      <div className="preview-head">
        <Icon name="sheet" />
        <div className="grow"><b>{fileName}</b><div className="muted-sm">Check the changes below, then confirm.</div></div>
      </div>
      <div className="preview-counts">
        <div><span className="num">{result.new}</span> new</div>
        <div><span className="num">{result.updated}</span> updated</div>
        <div><span className="num">{result.unchanged}</span> unchanged</div>
        {result.deactivated ? <div><span className="num">{result.deactivated}</span> deactivated</div> : null}
        {errors.length ? <div style={{ color: 'var(--danger)' }}><span className="num" style={{ color: 'var(--danger)' }}>{errors.length}</span> rows skipped</div> : null}
      </div>
      {result.classes && result.classes.length ? (
        <div className="muted-sm">{result.classes.map((c) => `${c.name}: ${c.new} new, ${c.updated} updated`).join(' · ')}</div>
      ) : null}
      {children}
      {errors.length ? (
        <div className="issue-box is-danger"><b>These rows will be skipped. Fix them in Excel and upload again if needed:</b>
          <ul>{errors.slice(0, 12).map((i) => <li key={i.row + i.message}>{i.message}</li>)}</ul>
          {errors.length > 12 ? <div>…and {errors.length - 12} more.</div> : null}</div>
      ) : null}
      {warnings.length ? (
        <div className="issue-box is-warning"><b>These will be imported, but check them:</b>
          <ul>{warnings.slice(0, 12).map((i) => <li key={i.row + i.message}>{i.message}</li>)}</ul></div>
      ) : null}
      {result.rows.length ? (
        <DataTable columns={[
          { key: 'change', label: 'Change', render: (r) => <StatusBadge status={CHANGE[r.change]?.[0] ?? 'pending'}>{CHANGE[r.change]?.[1] ?? r.change}</StatusBadge> },
          { key: 'student_code', label: 'Student ID', mono: true },
          { key: 'name', label: 'Name' },
          ...(showClass ? [{ key: 'class', label: 'Class' }] : []),
          { key: 'section', label: 'Section' },
          { key: 'email', label: 'Email', mono: true },
          { key: 'whatsapp', label: 'WhatsApp', mono: true },
        ]} rows={result.rows.slice(0, 200).map((r) => ({ ...r, id: r.class + r.student_code }))} />
      ) : null}
      {result.rows.length > 200 ? <div className="muted-sm">Showing the first 200 of {result.rows.length} changes.</div> : null}
      <div className="row">
        <Button variant="primary" icon="check" onClick={onConfirm} disabled={busy || nothing}>
          {nothing ? 'Nothing to change' : `Confirm and save ${result.new + result.updated + result.deactivated} change${result.new + result.updated + result.deactivated === 1 ? '' : 's'}`}</Button>
        <Button variant="quiet" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}
