import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api, openFile } from '../api';
import { Dialog, Layout, LoadState, useAction, useIsAdmin, useLoad } from '../app';
import { Banner, Button, Card, Icon, Pipeline, StatusBadge } from '../components/ds';

interface Question {
  text: string; options: string[]; answer: string; difficulty: string; topic: string; source_ids: string[]; outside_syllabus: boolean;
  review_note: string; origin?: string; edited?: boolean; edited_by?: string;
}
const SECTION_ORDER = ['mcq', 'very_short', 'short', 'application', 'long', 'hots'];

/** Edit mode shows every section type (even empty ones) so teachers can add questions anywhere. */
function toEditable(c: Content): Content {
  const byType = new Map(c.sections.map((s) => [s.type, s.questions]));
  return { ...structuredClone(c), sections: SECTION_ORDER.map((t) => ({ type: t, questions: structuredClone(byType.get(t) ?? []) })) };
}
function blankQuestion(type: string): Question {
  return { text: '', options: type === 'mcq' ? ['', '', '', ''] : [], answer: '', difficulty: 'medium', topic: '', source_ids: [],
    outside_syllabus: false, review_note: '', origin: 'teacher' };
}
interface Content { title: string; instructions: string; coverage_plan: { topic: string; question_refs: string[] }[]; sections: { type: string; questions: Question[] }[] }
interface Check { id: string; label: string; status: 'passed' | 'warning' | 'failed'; detail: string; refs: string[] }
interface Detail {
  id: number; title: string; subject: string; class: string; class_id: number; grade: string; sections: string; exam_code: string; exam_date: string;
  version: number; status: string; generator: string; release_mode: 'review' | 'auto'; content: Content;
  validation: { passed: boolean; summary: string; checks: Check[] }; sources: { filename: string; version: number; chapter: string | null; passages: number }[];
  passages: Record<string, { text: string; source: string; page: number }>; scope: { text: string; chapters: number[]; file: string } | null;
  settings: { difficulty: Record<string, number>; answer_key: boolean }; labels: Record<string, string>; recipients: number; channels: string[];
  approved_by: string | null; regeneration_reason: string | null; versions: { id: number; version: number; status: string }[]; has_pdf: boolean;
}

const LETTERS = 'ABCDEFGHIJ';

function pipelineState(d: Detail): { current: number; failed?: boolean } {
  const review = d.release_mode === 'review' || d.status !== 'released' || !!d.approved_by;
  if (d.status === 'validation-failed') return { current: 1, failed: true };
  if (d.status === 'awaiting-approval') return { current: 2 };
  if (d.status === 'released') return { current: review ? 5 : 3 };
  return { current: 0 };
}

export default function WorksheetReview() {
  const { id } = useParams();
  const nav = useNavigate();
  const admin = useIsAdmin();
  const { data: d, setData, error, loading, reload } = useLoad<Detail>(`/api/worksheets/${id}`, [id]);
  const { busy, run } = useAction();
  const [editing, setEditing] = useState<Content | null>(null);
  const [regen, setRegen] = useState(false);
  const [override, setOverride] = useState(false);
  const [passage, setPassage] = useState<string | null>(null);

  useEffect(() => { setEditing(null); }, [id]);
  // /review/12?edit=1 opens straight into the editor (used by "Fix" links).
  useEffect(() => {
    if (d && new URLSearchParams(window.location.search).get('edit') === '1'
        && (d.status === 'awaiting-approval' || d.status === 'validation-failed')) setEditing(toEditable(d.content));
  }, [d?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return <Layout active="review" title="Check worksheets"><LoadState error={error} loading={loading} /></Layout>;

  const flagged = new Set(d.validation.checks.filter((c) => c.status !== 'passed').flatMap((c) => c.refs));
  const reviewable = d.status === 'awaiting-approval' || d.status === 'validation-failed';
  const total = d.content.sections.reduce((n, s) => n + s.questions.length, 0);
  const mix = Object.entries(d.settings.difficulty || {}).map(([k, v]) => `${v}% ${k}`).join(' / ');
  const ps = pipelineState(d);
  const failedChecks = d.validation.checks.filter((c) => c.status === 'failed');

  async function approve(withOverride = false, note?: string) {
    const r = await run('approve', () => api.post<Detail>(`/api/worksheets/${d!.id}/approve`, { override: withOverride, note }),
      `Released. The Sharing Agent is sending it to ${d!.recipients} students.`);
    if (r) { setData(r); setOverride(false); }
  }
  async function saveEdit() {
    const toSave = { ...editing!, sections: editing!.sections.filter((s) => s.questions.some((q) => q.text.trim())) };
    const r = await run('save', () => api.put<Detail>(`/api/worksheets/${d!.id}/content`, { content: toSave }),
      'Saved. The worksheet was checked again and the PDF updated.');
    if (r) { setData(r); setEditing(null); }
  }
  function cancelEdit() {
    if (JSON.stringify(editing) !== JSON.stringify(toEditable(d!.content)) && !window.confirm('Discard your changes?')) return;
    setEditing(null);
  }
  async function doRegen(reason: string) {
    const r = await run('regen', () => api.post(`/api/worksheets/${d!.id}/regenerate`, { reason }),
      'Regenerating. The new version replaces this one when it is ready.');
    if (r) { setRegen(false); setTimeout(reload, 4000); }
  }

  const actions = reviewable ? <>
    {!editing ? <Button variant="quiet" icon="refresh" onClick={() => setRegen(true)}>Regenerate</Button> : null}
    {!editing ? <Button icon="edit" onClick={() => setEditing(toEditable(d.content))}>Edit questions</Button>
      : <><Button variant="quiet" onClick={cancelEdit}>Cancel</Button><Button variant="primary" icon="check" onClick={saveEdit} disabled={busy === 'save'}>Save changes</Button></>}
    {!editing ? (d.status === 'awaiting-approval'
      ? <Button variant="primary" icon="check" onClick={() => approve()} disabled={busy === 'approve'}>Approve &amp; release</Button>
      : admin ? <Button variant="danger" onClick={() => setOverride(true)}>Release anyway</Button> : null) : null}
  </> : d.status === 'released' ? <Button icon="send" onClick={() => nav(`/delivery/${d.id}`)}>Delivery status</Button> : null;

  const content = editing ?? d.content;
  const update = (fn: (c: Content) => void) => { const c = structuredClone(editing!); fn(c); setEditing(c); };
  const setQ = (si: number, qi: number, q: Partial<Question>) => update((c) => {
    const cur = c.sections[si].questions[qi];
    c.sections[si].questions[qi] = { ...cur, ...q, edited: cur.origin === 'teacher' ? cur.edited : true };
  });
  const removeQ = (si: number, qi: number) => update((c) => { c.sections[si].questions.splice(qi, 1); });
  const moveQ = (si: number, qi: number, dir: -1 | 1) => update((c) => {
    const qs = c.sections[si].questions;
    const j = qi + dir;
    if (j < 0 || j >= qs.length) return;
    [qs[qi], qs[j]] = [qs[j], qs[qi]];
  });
  const changeType = (si: number, qi: number, type: string) => update((c) => {
    const [q] = c.sections[si].questions.splice(qi, 1);
    const moved: Question = { ...q, edited: q.origin === 'teacher' ? q.edited : true,
      options: type === 'mcq' ? (q.options.length === 4 ? q.options : ['', '', '', '']) : [] };
    if (type === 'mcq' && !moved.options.includes(moved.answer)) moved.answer = '';
    c.sections.find((s) => s.type === type)!.questions.push(moved);
  });
  const addQ = (si: number) => update((c) => { c.sections[si].questions.push(blankQuestion(c.sections[si].type)); });

  return (
    <Layout active="review" title={`${d.subject} practice sheet`} crumb={`Check worksheets › ${d.class}${d.sections ? '-' + d.sections : ''} · Exam ${d.exam_date} · v${d.version}`} actions={actions}>
      <Pipeline mode={d.release_mode === 'auto' && !d.approved_by && d.status === 'released' ? 'auto' : 'review'} current={ps.current} failed={ps.failed} />
      {d.status === 'superseded' ? <Banner tone="info" title="A newer version replaced this one"
        action={<Button size="sm" onClick={() => nav(`/review/${d.versions[d.versions.length - 1].id}`)}>Open latest</Button>}>Kept for the audit trail.</Banner> : null}
      {d.status === 'cancelled' ? <Banner tone="warning" title="Cancelled">The exam was moved or removed from the date sheet, so this worksheet will not be sent.</Banner> : null}
      {d.generator.startsWith('offline') ? <Banner tone="warning" title="Built without a language model">This worksheet was assembled directly from PDF sentences (LLM_PROVIDER=offline). Set up the Claude API for real questions.</Banner> : null}
      <div className="psa-two">
        <Card title={editing ? 'Edit worksheet' : 'Preview'} actions={d.has_pdf && !editing ? <Button variant="quiet" size="sm" icon="file" onClick={() => openFile(`/api/worksheets/${d.id}/pdf`)}>Open PDF</Button> : null}>
          <div className="stack">
            <div style={{ borderBottom: '1px solid var(--line)', paddingBottom: 12 }}>
              {editing ? (
                <div className="stack-sm">
                  <label className="field"><span>Title</span><input className="input" value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} /></label>
                  <label className="field"><span>Instructions for students</span>
                    <textarea className="textarea" rows={2} value={editing.instructions} onChange={(e) => setEditing({ ...editing, instructions: e.target.value })} /></label>
                </div>
              ) : <>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--navy)' }}>{content.title}</div>
                {content.instructions ? <div className="muted-sm" style={{ marginTop: 4 }}>{content.instructions}</div> : null}
              </>}
              <div className="muted-sm" style={{ marginTop: 6 }}>{total} questions · {mix}{d.settings.answer_key ? ' · answer key attached' : ''} · {d.generator}</div>
            </div>
            {editing ? <div className="help">Change anything below. You can also <b>add</b>, <b>delete</b>, <b>move</b> questions, or change a question’s
              section. Maths can be typed plainly: x², √2, π, ∠ABC, 3/4. When you save, the worksheet is checked again and the PDF is updated.</div> : null}
            {content.sections.map((s, si) => {
              if (!editing && !s.questions.length) return null;
              // Letters match the saved worksheet: empty sections (edit mode only) get no letter.
              const letter = s.questions.length ? LETTERS[content.sections.slice(0, si).filter((x) => x.questions.length).length] : '·';
              return (
                <div key={s.type + si} className="q-grid">
                  <div className="q-letter">{letter}</div>
                  <div>
                    <div className="psa-label">{d.labels[s.type] ?? s.type} · {s.questions.length} question{s.questions.length === 1 ? '' : 's'}</div>
                    {s.questions.map((q, qi) => {
                      const ref = `${letter}-${qi + 1}`;
                      return editing ? (
                        <QuestionEditor key={qi} q={q} type={s.type} refLabel={ref} labels={d.labels} flagged={flagged.has(ref)}
                          first={qi === 0} last={qi === s.questions.length - 1}
                          onChange={(patch) => setQ(si, qi, patch)} onRemove={() => removeQ(si, qi)}
                          onMove={(dir) => moveQ(si, qi, dir)} onType={(t) => changeType(si, qi, t)} />
                      ) : (
                        <div key={qi} className={'q-item' + (flagged.has(ref) ? ' is-flagged' : '')} id={`q-${ref}`}>
                          <div className="q-text"><b>{ref}.</b> {q.text}</div>
                          {q.options.length ? <ol type="a" className="q-opts">{q.options.map((o, oi) => <li key={oi}>{o}</li>)}</ol> : null}
                          <AnswerView answer={q.answer} />
                          <div className="q-meta">
                            <span className="muted-sm">{q.difficulty}{q.topic ? ` · ${q.topic}` : ''}</span>
                            {q.origin === 'teacher' ? <span className="edited-tag">Written by teacher</span>
                              : q.edited ? <span className="edited-tag">Edited by teacher</span> : null}
                            {q.source_ids.map((sid) => <button key={sid} className="chip" onClick={() => setPassage(sid)} title="Show the passage this question is based on">{d.passages[sid]?.source ?? sid}</button>)}
                            {q.review_note ? <span className="muted-sm" style={{ color: 'var(--warning)' }}>{q.review_note}</span> : null}
                          </div>
                        </div>
                      );
                    })}
                    {editing ? <Button size="sm" variant="quiet" icon="plus" onClick={() => addQ(si)}>Add a {(d.labels[s.type] ?? s.type).toLowerCase()} question</Button> : null}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
        <div className="stack-lg">
          <Card title="Validation">
            <div className="stack-sm" style={{ gap: 10 }}>
              {d.validation.checks.map((c) => (
                <div key={c.id} className="row-between" title={c.detail}>
                  <div><div>{c.label}</div>{c.status !== 'passed' ? <div className="muted-sm">{c.detail}</div> : null}</div>
                  <StatusBadge status={c.status === 'passed' ? 'completed' : c.status === 'warning' ? 'awaiting-approval' : 'failed'}>
                    {c.status === 'passed' ? 'Passed' : c.status === 'warning' ? 'Check' : c.refs.length ? `${c.refs.length} flagged` : 'Failed'}</StatusBadge>
                </div>
              ))}
            </div>
          </Card>
          {failedChecks.length && reviewable ? (
            <Banner tone="warning" title={`${failedChecks.length} check${failedChecks.length > 1 ? 's' : ''} failed · not released`}>
              {failedChecks.map((c) => c.detail).join(' ')} Edit the flagged questions or regenerate before release.
            </Banner>
          ) : null}
          {d.scope ? (
            <Card title="Exam syllabus">
              <div className="stack-sm">
                <div className="muted-sm">From {d.scope.file}{d.scope.chapters.length ? ` · chapters ${d.scope.chapters.join(', ')}` : ''}. Questions must stay inside it.</div>
                <div className="scope-box">{d.scope.text}</div>
              </div>
            </Card>
          ) : null}
          <Card title="Sources used">
            <div className="stack-sm">
              {d.sources.length === 0 ? <div className="muted-sm">No sources cited.</div> : null}
              {d.sources.map((s) => <div key={s.filename} className="psa-mono row" style={{ gap: 8 }}><Icon name="file" />{s.filename} · v{s.version}<span className="psa-muted">· {s.passages} citations</span></div>)}
            </div>
          </Card>
          <Card title="Recipients">
            <div><b>{d.recipients} students</b> of {d.class}{d.sections ? ` · section ${d.sections}` : ''} will receive this by {d.channels.length ? d.channels.join(' and ') : 'no channel (none enabled)'}.</div>
          </Card>
          {d.versions.length > 1 ? (
            <Card title="Versions">
              <div className="stack-sm">
                {d.versions.map((v) => <div key={v.id} className="row-between"><a href="#" onClick={(e) => { e.preventDefault(); nav(`/review/${v.id}`); }}>v{v.version}{v.id === d.id ? ' · this one' : ''}</a><StatusBadge status={v.status} /></div>)}
                {d.regeneration_reason ? <div className="muted-sm">Regenerated because: {d.regeneration_reason}</div> : null}
              </div>
            </Card>
          ) : null}
        </div>
      </div>
      {passage ? (
        <Dialog title={d.passages[passage]?.source ?? passage} onClose={() => setPassage(null)}>
          <div className="muted-sm">Page {d.passages[passage]?.page} · passage {passage}</div>
          <div className="passage">{d.passages[passage]?.text ?? 'This passage is not stored with the worksheet.'}</div>
        </Dialog>
      ) : null}
      {regen ? <RegenDialog onClose={() => setRegen(false)} onSubmit={doRegen} busy={busy === 'regen'} /> : null}
      {override ? <OverrideDialog onClose={() => setOverride(false)} onSubmit={(note) => approve(true, note)} checks={failedChecks} /> : null}
    </Layout>
  );
}

/** One-line answers stay inline; worked answers show one step per line with their labels in bold. */
const STEP_LABEL = /^(Given|To find|Formula|Solution|Using|Answer|Final answer|Therefore|Hence|दिया गया है|सूत्र|हल|उत्तर|अतः)\b\s*:?/i;
function AnswerView({ answer }: { answer: string }) {
  const lines = answer.split('\n').map((l) => l.trim()).filter(Boolean);
  if (lines.length <= 1) return <div className="q-answer"><b>Answer:</b> {answer}</div>;
  return (
    <div className="q-answer is-steps">
      <div className="q-answer-head">Answer</div>
      {lines.map((line, i) => {
        const m = STEP_LABEL.exec(line);
        const final = /^(answer|final answer|उत्तर)\b/i.test(line);
        return (
          <div key={i} className={'q-step' + (final ? ' is-final' : '')}>
            {m ? <><b>{m[0]}</b>{line.slice(m[0].length)}</> : line}
          </div>
        );
      })}
    </div>
  );
}

function QuestionEditor({ q, type, refLabel, labels, flagged, first, last, onChange, onRemove, onMove, onType }: {
  q: Question; type: string; refLabel: string; labels: Record<string, string>; flagged: boolean; first: boolean; last: boolean;
  onChange: (patch: Partial<Question>) => void; onRemove: () => void; onMove: (dir: -1 | 1) => void; onType: (t: string) => void;
}) {
  const isMcq = type === 'mcq';
  const correct = q.options.findIndex((o) => o.trim() && o === q.answer);
  const setOption = (i: number, value: string) => {
    const opts = [...q.options];
    const wasCorrect = i === correct;
    opts[i] = value;
    onChange(wasCorrect ? { options: opts, answer: value } : { options: opts });
  };
  return (
    <div className={'q-edit' + (flagged ? ' is-flagged' : '') + (q.origin === 'teacher' ? ' is-new' : '')}>
      <div className="q-edit-head">
        <b>{refLabel}</b>
        {q.origin === 'teacher' ? <span className="edited-tag">New</span> : q.edited ? <span className="edited-tag">Edited</span> : null}
        <span className="grow" />
        <select className="select sm" value={type} onChange={(e) => onType(e.target.value)} aria-label="Question type" title="Move to another section">
          {SECTION_ORDER.map((t) => <option key={t} value={t}>{labels[t] ?? t}</option>)}
        </select>
        <select className="select sm" value={q.difficulty} onChange={(e) => onChange({ difficulty: e.target.value })} aria-label="Difficulty">
          <option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option></select>
        <button type="button" className="icon-btn" onClick={() => onMove(-1)} disabled={first} aria-label="Move up" title="Move up">↑</button>
        <button type="button" className="icon-btn" onClick={() => onMove(1)} disabled={last} aria-label="Move down" title="Move down">↓</button>
        <button type="button" className="icon-btn danger" onClick={() => { if (!q.text.trim() || window.confirm('Delete this question?')) onRemove(); }}
          aria-label="Delete question" title="Delete question"><Icon name="trash" /></button>
      </div>
      <label className="field"><span>Question</span>
        <textarea className="textarea" rows={Math.min(8, Math.max(2, q.text.split('\n').length + 1))} value={q.text} placeholder="Type the question" autoFocus={q.origin === 'teacher' && !q.text}
          onChange={(e) => onChange({ text: e.target.value })} /></label>
      {isMcq ? (
        <div className="field"><span>Options · select the correct one</span>
          <div className="stack-sm">
            {q.options.map((o, oi) => (
              <label key={oi} className={'opt-row' + (oi === correct ? ' is-correct' : '')}>
                <input type="radio" name={`correct-${refLabel}`} checked={oi === correct} disabled={!o.trim()}
                  onChange={() => onChange({ answer: q.options[oi] })} aria-label={`Option ${'abcd'[oi]} is correct`} />
                <span className="opt-letter">{'abcd'[oi]}</span>
                <input className="input" value={o} placeholder={`Option ${'abcd'[oi]}`} onChange={(e) => setOption(oi, e.target.value)} />
              </label>
            ))}
          </div>
          {correct < 0 ? <small style={{ color: 'var(--warning)' }}>Fill in the options and choose the correct one.</small> : null}
        </div>
      ) : (
        <label className="field"><span>Answer</span>
          <textarea className="textarea" rows={Math.min(10, Math.max(2, q.answer.split('\n').length + 1))} value={q.answer}
            placeholder={'Model answer (used for the answer key). For numericals, one step per line:\nGiven: …\nFormula: …\nAnswer: …'} onChange={(e) => onChange({ answer: e.target.value })} /></label>
      )}
      <label className="row" style={{ gap: 6 }}>
        <input type="checkbox" checked={q.outside_syllabus} onChange={(e) => onChange({ outside_syllabus: e.target.checked, review_note: e.target.checked ? q.review_note : '' })} />
        <span className="muted-sm">This question goes beyond the exam syllabus (it will not be released until fixed)</span>
      </label>
    </div>
  );
}

function RegenDialog({ onClose, onSubmit, busy }: { onClose: () => void; onSubmit: (r: string) => void; busy: boolean }) {
  const [reason, setReason] = useState('');
  return (
    <Dialog title="Regenerate worksheet" onClose={onClose}
      footer={<><Button variant="quiet" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!reason.trim() || busy} onClick={() => onSubmit(reason)}>Regenerate</Button></>}>
      <div>A new version is generated from the same exam syllabus and PDFs. This version is kept in the history.</div>
      <label className="field"><span>Reason</span><textarea className="textarea" autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Q D-1 goes beyond Chapter 6" /></label>
    </Dialog>
  );
}

function OverrideDialog({ onClose, onSubmit, checks }: { onClose: () => void; onSubmit: (note: string) => void; checks: Check[] }) {
  const [note, setNote] = useState('');
  return (
    <Dialog title="Release despite failed validation" onClose={onClose}
      footer={<><Button variant="quiet" onClick={onClose}>Cancel</Button><Button variant="danger" disabled={note.trim().length < 5} onClick={() => onSubmit(note)}>Release to students</Button></>}>
      <Banner tone="danger" title="These checks failed">{checks.map((c) => <div key={c.id}>{c.label}: {c.detail}</div>)}</Banner>
      <label className="field"><span>Why is it safe to release?</span><textarea className="textarea" value={note} onChange={(e) => setNote(e.target.value)} />
        <small>Recorded in the audit trail with your name.</small></label>
    </Dialog>
  );
}
