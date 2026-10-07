import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, openFile } from '../api';
import { LoadState, ThemeToggle, useAction, useAuth, useLoad } from '../app';
import { Banner, Button, Card, SiteFooter, StatusBadge } from '../components/ds';
import { PasswordCard } from './Settings';

interface Child { id: number; name: string; class: string; section: string; used_today: number; subjects: { name: string; chapters: string[] }[] }
interface Sheet {
  id: number; student_id: number; student: string; subject: string; chapters: string[]; status: 'generating' | 'ready' | 'failed';
  title: string; error: string | null; created: string; questions: number; has_pdf: boolean;
}
interface Overview { limit: number; children: Child[]; sheets: Sheet[] }

/** The parent's page: make a practice sheet for their own child, then download it. Nothing here reaches the class. */
export default function ParentHome() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const { data, error, loading, reload } = useLoad<Overview>('/api/parent/overview');
  const generating = data?.sheets.some((s) => s.status === 'generating') ?? false;

  // While a sheet is being written, check every few seconds so it appears as soon as it is ready.
  useEffect(() => {
    if (!generating) return;
    const t = setInterval(reload, 4000);
    return () => clearInterval(t);
  }, [generating, reload]);

  return (
    <div className="parent-page psa">
      <header className="parent-top">
        <div className="psa-brand"><span className="psa-brand-mark">PS</span><span>Practice Sheet Agent</span></div>
        <div className="row" style={{ gap: 8 }}>
          <ThemeToggle />
          <Button size="sm" variant="quiet" icon="logout" onClick={() => { logout(); nav('/login'); }}>Sign out</Button>
        </div>
      </header>
      <main className="parent-main stack-lg">
        <div>
          <div className="psa-crumb">Signed in as {user?.name}</div>
          <h1 className="parent-title">Practice sheets</h1>
          <div className="muted-sm">Make a fresh practice sheet for your child whenever you like. The questions come from the
            school's own study material, with an answer key at the end.</div>
        </div>
        <LoadState error={error} loading={loading && !data} />
        {data && !data.children.length ? (
          <Banner tone="warning" title="No child is linked to your account yet">Please ask the school to link your child to your account.</Banner>
        ) : null}
        {data && data.children.length ? <MakeSheet data={data} onMade={reload} /> : null}
        {data && data.sheets.length ? <SheetList sheets={data.sheets} showChild={data.children.length > 1} /> : null}
        <div className="parent-narrow"><PasswordCard /></div>
      </main>
      <SiteFooter />
    </div>
  );
}

function MakeSheet({ data, onMade }: { data: Overview; onMade: () => void }) {
  const [childId, setChildId] = useState(data.children[0].id);
  const child = data.children.find((c) => c.id === childId) ?? data.children[0];
  const [subject, setSubject] = useState(child.subjects[0]?.name ?? '');
  const [chapters, setChapters] = useState<string[]>([]);
  const { busy, run } = useAction();
  const subj = child.subjects.find((s) => s.name === subject);
  const left = Math.max(data.limit - child.used_today, 0);
  const inProgress = data.sheets.some((s) => s.student_id === child.id && s.status === 'generating');

  function pickChild(id: number) {
    const c = data.children.find((x) => x.id === id)!;
    setChildId(id);
    setSubject(c.subjects[0]?.name ?? '');
    setChapters([]);
  }
  async function make() {
    const r = await run('make', () => api.post('/api/parent/sheets', { student_id: child.id, subject, chapters }),
      'Making the practice sheet. It will appear below in a minute or two.');
    if (r) { setChapters([]); onMade(); }
  }

  return (
    <Card title="Make a practice sheet">
      <div className="stack">
        <div className="form-grid">
          <label className="field"><span>Child</span>
            {data.children.length > 1 ? (
              <select className="select" value={child.id} onChange={(e) => pickChild(Number(e.target.value))}>
                {data.children.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.class}-{c.section}</option>)}
              </select>
            ) : <div className="parent-child">{child.name} · {child.class}-{child.section}</div>}
          </label>
          {child.subjects.length ? (
            <label className="field"><span>Subject</span>
              <select className="select" value={subject} onChange={(e) => { setSubject(e.target.value); setChapters([]); }}>
                {child.subjects.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
              </select>
            </label>
          ) : null}
        </div>
        {!child.subjects.length ? (
          <Banner tone="warning">The school hasn't added study material for {child.class} yet, so practice sheets can't be made.</Banner>
        ) : null}
        {subj && subj.chapters.length ? (
          <div className="field"><span>Chapters (optional)</span>
            <div className="chapter-picks">
              {subj.chapters.map((ch) => (
                <label key={ch} className={'chapter-pick' + (chapters.includes(ch) ? ' is-on' : '')}>
                  <input type="checkbox" checked={chapters.includes(ch)}
                    onChange={(e) => setChapters(e.target.checked ? [...chapters, ch] : chapters.filter((x) => x !== ch))} />{ch}
                </label>
              ))}
            </div>
            <small>Leave them all unticked to practise every chapter.</small>
          </div>
        ) : null}
        <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
          <Button variant="primary" icon="plus" onClick={make}
            disabled={!subj || !left || inProgress || busy === 'make'}>{busy === 'make' ? 'Starting…' : 'Make practice sheet'}</Button>
          <span className="muted-sm">{inProgress ? `A sheet for ${child.name} is being made…`
            : left ? `${left} of ${data.limit} left today for ${child.name}` : `${child.name} has used all ${data.limit} for today. More tomorrow.`}</span>
        </div>
      </div>
    </Card>
  );
}

function SheetList({ sheets, showChild }: { sheets: Sheet[]; showChild: boolean }) {
  const { busy, run } = useAction();
  return (
    <Card title="Your practice sheets" flush>
      <ul className="sheet-list">
        {sheets.map((s) => (
          <li key={s.id} className="sheet-item">
            <div className="grow">
              <div className="sheet-title">{s.status === 'ready' ? s.title : `${s.subject} practice sheet`}</div>
              <div className="muted-sm">
                {showChild ? `${s.student} · ` : ''}{s.chapters.length ? s.chapters.join(', ') : 'All chapters'} · {s.created}
                {s.status === 'ready' ? ` · ${s.questions} questions` : ''}
              </div>
              {s.status === 'failed' && s.error ? <div className="sheet-error">{s.error}</div> : null}
            </div>
            {s.status === 'generating' ? <StatusBadge status="generating">Being made…</StatusBadge> : null}
            {s.status === 'failed' ? <StatusBadge status="failed" /> : null}
            {s.status === 'ready' && s.has_pdf ? (
              <Button size="sm" icon="download" disabled={busy === `pdf${s.id}`}
                onClick={() => run(`pdf${s.id}`, () => openFile(`/api/parent/sheets/${s.id}/pdf`,
                  `${s.subject.replace(/\W+/g, '_')}_practice_sheet_${s.id}.pdf`))}>Download PDF</Button>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}
