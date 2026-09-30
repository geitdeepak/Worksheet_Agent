# AI Exam Practice Sheet Agent

A class-centric platform that automatically generates syllabus-grounded practice worksheets two days before each exam
and delivers them to the right students — by email in Phase 1, by email and WhatsApp in Phase 2.

An administrator configures each class once (date sheet, **exam syllabus**, subject PDFs, students, worksheet settings)
and activates automation. From then on the platform runs by itself.

```
Admin UI → Class workspace → Scheduler/Orchestrator → Worksheet Creation Agent (RAG + Claude)
        → Validation → Review/approval or auto release → Worksheet Sharing Agent → Email / WhatsApp → Tracking
```

## Quick start (Windows, PowerShell)

Requirements: Python 3.12+ and Node 20+.

```powershell
# Backend
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install --only-binary=:all: -r requirements.txt
copy .env.example .env        # then edit: JWT_SECRET, ADMIN_PASSWORD, GEMINI_API_KEY (or ANTHROPIC_API_KEY)
.venv\Scripts\python -m uvicorn app.main:app --port 8010

# Frontend (second terminal)
cd frontend
npm install
npm run dev                   # http://localhost:5173 (proxies /api to :8010)
```

Sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`.

**Production-style single server:** run `npm run build` in `frontend/`. FastAPI then serves the built UI from
`frontend/dist`, so http://localhost:8010 is the whole app.

**Demo data:** with the backend stopped, run `.venv\Scripts\python -m scripts.seed_demo` from `backend/`. It creates
Class 9 with a Mathematics exam two days from today, an exam syllabus (chapters 1, 2, 7 — chapter 6 explicitly excluded),
chapter PDFs including the excluded chapter, and five students. Start the server and click **Run check now**.

**Choosing the AI.** Set `LLM_PROVIDER` in `backend/.env`:

| Provider | Settings | Notes |
|---|---|---|
| `gemini` | `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-3.8-flash`), `GEMINI_FALLBACK_MODELS` | Backup models are tried automatically when a model is overloaded (503) or rate-limited (429). |
| `anthropic` | `ANTHROPIC_API_KEY`, `LLM_MODEL` (default `claude-sonnet-5`) | |
| `offline` | none | Builds questions from PDF sentences. For trying the workflow only; labelled in the UI. |

Both AI providers use the same prompt, the same worksheet JSON schema, the Batch API for scheduled worksheets, and the
same syllabus/validation checks afterwards. Settings › Services shows which one is active.

## Using it (for school staff)

Each class is set up in **4 steps**, shown as numbered tabs with a checklist on the right:

1. **Exam dates** – download the Excel template, fill in subject and date, upload, check the preview, save.
2. **Exam syllabus** – the template lists your subjects; write the chapters for each (or upload the school's PDF/Word notice).
3. **Study material** – upload the chapter PDFs for each subject (name them `Chapter-03.pdf` etc.).
4. **Students** – download the template, fill it in, upload. Or use **Classes › Upload students for all classes** to
   load the whole school from one file; each student goes to the right class by the Class column.

Then click **Start sending worksheets**. The **Home** page lists anything that needs you (worksheets to approve,
unfinished setup, undelivered emails) with a button for each.

**Language.** Worksheets are English by default. Choose Hindi per class or per subject in **Class › Settings**.
The Hindi subject is always prepared in Hindi. Hindi maths keeps standard notation (x², √2, π).

**PDF fonts.** Worksheets use *PSA Sans* (`backend/app/fonts`), one font merged from Noto Sans, Noto Sans Devanagari
and Noto Sans Math, with HarfBuzz shaping, so English, Hindi (conjuncts and matras) and maths symbols all print
correctly — including mixed words like √2 or △ABC. Rebuild with `python -m scripts.build_fonts` (needs `fonttools`).
Maths written as LaTeX by the model (`\frac{3}{4}`, `x^{2}`) is converted to plain symbols automatically.

## How a class is configured

| Step | Where | Notes |
|---|---|---|
| Create class | Classes › New class | The number in the name ("Class 9") is matched against the Class column of uploads. |
| Date sheet | Class › Date sheet & syllabus | `.xlsx`/`.csv` with Class, Section, Subject, Exam date (+ optional Exam time, Exam ID). Parsed rows are **previewed**; nothing is live until you confirm. |
| **Exam syllabus** | Class › Date sheet & syllabus | The school's own portion for this exam cycle — PDF, Word, Excel/CSV or text. Split per subject, previewed and **editable** before confirming. See below. |
| Subject PDFs | Class › Subjects | Chapter PDFs (name them `Chapter-03.pdf` etc. so chapter numbers are detected). Same file name = new version; old versions are kept. |
| Students | Class › Students | Student ID, Name, Class, Section, Email, WhatsApp. Contacts are masked in lists. |
| Worksheet settings | Class › Worksheet settings | Counts per question type, difficulty mix, answer key, language. Institution default → class → subject overrides. |
| Activate | Header button | Blocked until the Readiness card is all green. |

### The exam syllabus is the scope boundary

Every school sets its own portion per exam, so worksheets must never go beyond it. Enforcement happens at three layers:

1. **Retrieval** — only passages from chapter PDFs whose chapter number is in the confirmed exam syllabus (plus strong
   topic matches) are sent to the model. Lines like *"Chapter 6 is not included"* or *"excluding Ch 4"* are read as
   exclusions and always win.
2. **Generation** — the syllabus text is given to Claude as the authoritative boundary; it must cite the passage ids
   behind every question and flag anything outside scope.
3. **Validation** — the *Within exam syllabus* check fails the worksheet if any question cites a passage outside the
   scope or was flagged. Failed worksheets are never released automatically; they go to review.

If the syllabus is replaced, unreleased worksheets for changed subjects are marked for regeneration.

## Architecture

```
backend/app
├── main.py              FastAPI app, first-admin seeding, worker start, serves frontend/dist
├── models.py            Classes, exams, subjects, documents/chunks, students, jobs, worksheets, deliveries, audit
├── orchestrator.py      Daily two-day trigger, durable jobs, dedup by business key, release, cancellation, retries
├── worker.py            Background thread: runs the daily check at the configured time and drains the job queue
├── agents/
│   ├── creation_agent.py  Agent 1: scope → retrieval → Claude → validation → PDF
│   ├── llm.py             Claude call: structured JSON output, adaptive thinking, streaming, refusal fallback
│   ├── validation.py      Structure, grounding, duplicates, exam-syllabus scope, answer key, difficulty mix
│   ├── pdf_render.py      Worksheet PDF (answer key on its own page)
│   └── sharing_agent.py   Agent 2: eligible students × enabled channels, one tracked row per recipient per channel
├── channels/            email.py (SMTP / outbox), whatsapp.py (Cloud API / outbox)
├── services/            tabular parsing, syllabus parsing, PDF ingestion + chunking, BM25 retrieval, helpers
└── api/                 admin (auth, users, settings, dashboard, jobs, audit, webhooks), classes, worksheets
frontend/src
├── components/ds.tsx    The 14 design-system components, typed (prop names from index.d.ts)
├── styles/              tokens.css + bundle.css from the design system, app.css additions (tokens only)
└── pages/               Login, Dashboard, Classes, Class workspace (6 tabs), Worksheet review, Delivery monitor, History, Settings
```

**Deterministic where it matters.** Dates, triggers, class/section matching, deduplication and delivery state are plain
application logic. The model is used only to write questions from retrieved material.

**Duplicate prevention.** Creation jobs are unique on `Exam ID + Class + Section + Subject + Exam date + Worksheet
version`. Deliveries are unique on `worksheet × student × channel`, and each result is committed as it happens, so a
restart or retry never generates or sends twice. Jobs left running by a crash are resumed on startup.

**Schedule changes.** Editing or re-uploading the date sheet retires moved/removed exams and cancels their pending or
unreleased work; new trigger dates are computed from the new rows.

**Exceptions** follow the spec: missing date sheet or syllabus blocks the class; missing PDFs block that subject;
generation failures retry with backoff (3 attempts) and then alert; invalid emails fail only that recipient; missing
WhatsApp numbers are skipped and logged; provider outages retry per delivery.

## Phase 2 — WhatsApp

1. Configure the WhatsApp Business Platform: `WHATSAPP_PROVIDER=cloud_api`, `WHATSAPP_PHONE_NUMBER_ID`,
   `WHATSAPP_ACCESS_TOKEN`. Business-initiated messages need an approved template: set `WHATSAPP_TEMPLATE_NAME` to a
   template with a DOCUMENT header and three body parameters (subject, class, exam date).
2. Optional delivery receipts: set `WHATSAPP_WEBHOOK_VERIFY_TOKEN` and point the webhook at `/api/webhooks/whatsapp`.
3. In **Settings**, turn on *Phase 2*, then enable WhatsApp per class in **Class › Delivery**.

The creation workflow is unchanged; the same worksheet version goes to both channels, tracked independently.

## Tests

```powershell
cd backend
.venv\Scripts\python -m pytest -q
```

Covers date parsing and validation, contact normalisation, settings layering, syllabus chapter/exclusion parsing,
validation checks, and an end-to-end flow: configure → blocked activation → two-day trigger (not a day early, not
twice) → generation restricted to syllabus chapters → edit that cites out-of-scope material fails validation →
regenerate → approve → email delivery with one invalid address isolated → re-share sends nothing twice → schedule
change cancels pending work.

## Going to production

- Set a long random `JWT_SECRET` and a strong `ADMIN_PASSWORD`; serve behind HTTPS.
- Use PostgreSQL (`DATABASE_URL`) and put `DATA_DIR` on encrypted storage — it holds uploads, worksheets and outbox files.
- Run exactly one worker process (`WORKER_ENABLED=false` on extra API instances).
- Set a retention policy for `data/` (student data and documents) that matches your institution's rules.
- Worksheet PDFs use Helvetica. For Hindi or other non-Latin scripts, register a Unicode TTF font in `pdf_render.py`.
