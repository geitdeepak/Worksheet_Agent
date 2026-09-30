"""Agent 1 — Worksheet Creation Agent. Owns the academic workflow:
confirm the exam → reuse a matching worksheet if one exists → retrieve in-syllabus material → generate →
validate → render PDF.

Cost saving:
  • Reuse   — when another section or class has a worksheet this term for the same subject, exam syllabus and
              worksheet settings, it is copied instead of generated (₹0). Every section's students still get it:
              each exam row keeps its own worksheet and its own deliveries.
  • Batch   — scheduled worksheets go through the Message Batches API (50% cheaper); manual ones ("Make it
              now", regenerate) call the model directly so the result is immediate.
  • The model, effort and amount of textbook text sent are set in config (cheaper defaults)."""
import copy
import logging
import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Chunk, Document, Exam, Job, SchoolClass, Subject, Worksheet, utcnow
from ..services.common import (SECTION_LABELS, audit, fmt_date, get_setting, is_hindi_subject, merge_worksheet_settings,
                               worksheet_language)
from ..services.rag import Passage, SubjectIndex, build_context, load_passages, tokenize
from . import llm
from .mathtext import normalize_content
from .pdf_render import render_worksheet_pdf
from .validation import validate

log = logging.getLogger("psa.creation")

SECTION_ORDER = ["mcq", "very_short", "short", "application", "long", "hots"]
HINDI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
REUSE_WINDOW_DAYS = 45  # "this term": worksheets for exams within this many days of each other can be shared


class BlockedError(Exception):
    """Generation cannot proceed until an administrator fixes configuration. Not retried."""


class Pending(Exception):
    """The worksheet is being written asynchronously (Batch API); check again on a later worker tick."""


def find_subject(db: Session, class_id: int, subject_name: str) -> Subject | None:
    return db.scalars(select(Subject).where(Subject.class_id == class_id,
                                            func.lower(Subject.name) == subject_name.strip().lower())).first()


def exam_scope(school_class: SchoolClass, subject_name: str) -> dict | None:
    """The confirmed exam-syllabus entry for a subject, or None."""
    if not school_class.syllabus_confirmed:
        return None
    return (school_class.syllabus_scope or {}).get(subject_name.strip().lower())


def standard_title(exam: Exam, grade: str, language: str) -> str:
    d = exam.exam_date
    if language == "Hindi":
        return f"{exam.subject_name} अभ्यास पत्रक – कक्षा {grade} – परीक्षा {d.day} {HINDI_MONTHS[d.month - 1]}"
    return f"{exam.subject_name} Practice Sheet – Class {grade} – Exam {d.day} {d.strftime('%B')}"


def standard_instructions(language: str) -> str:
    return ("सभी प्रश्न हल कीजिए। दोहराने के लिए अपनी पाठ्यपुस्तक के अध्याय देखें।" if language == "Hindi"
            else "Answer all questions. Refer to your textbook chapters for revision.")


# ------------------------------------------------------------------------------------------- planning

@dataclass
class Plan:
    school_class: SchoolClass
    exam: Exam
    subject: Subject
    scope: dict
    settings: dict
    passages: list[Passage] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)


def prepare(db: Session, job: Job) -> Plan:
    school_class = db.get(SchoolClass, job.class_id)
    exam = db.get(Exam, job.exam_id) if job.exam_id else None
    if exam is None or not exam.active:
        raise BlockedError("The exam is no longer on the confirmed date sheet.")
    subject = find_subject(db, school_class.id, exam.subject_name)
    if subject is None:
        raise BlockedError(f"{school_class.name} has no subject named {exam.subject_name}. "
                           f"Add it in {school_class.name} › Study material and upload its PDFs.")
    scope = exam_scope(school_class, exam.subject_name)
    if scope is None:
        raise BlockedError(f"{school_class.name} has no confirmed exam syllabus for {exam.subject_name}. "
                           f"Upload it in {school_class.name} › Exam syllabus and confirm it.")
    settings = merge_worksheet_settings(get_setting(db, "worksheet_defaults"), school_class.worksheet_settings,
                                        subject.worksheet_settings)
    settings["language"] = worksheet_language(settings, exam.subject_name)  # Hindi subject → always Hindi
    return Plan(school_class, exam, subject, scope, settings)


def load_material(db: Session, plan: Plan) -> None:
    """Retrieve the in-syllabus passages, capped at LLM_CONTEXT_CHARS (most relevant first)."""
    sc, exam = plan.school_class, plan.exam
    if not load_passages(db, plan.subject):
        raise BlockedError(f"{exam.subject_name} has no readable PDFs in {sc.name}. "
                           f"Upload the chapter PDFs in {sc.name} › Study material.")
    plan.passages, plan.topics = build_context(db, plan.subject, get_settings().llm_context_chars, scope=plan.scope)
    if not plan.passages:
        raise BlockedError(f"None of the {exam.subject_name} PDFs match the exam syllabus "
                           f"(chapters {', '.join(map(str, plan.scope.get('chapters') or [])) or '—'}). Upload the chapters "
                           f"it lists, or label each PDF with its chapter number in {sc.name} › Study material.")


def passages_by_ids(db: Session, chunk_ids: list[int]) -> list[Passage]:
    """Reload the exact passages a batch request was built from (documents are versioned, never overwritten)."""
    rows = db.execute(select(Chunk, Document).join(Document, Chunk.document_id == Document.id)
                      .where(Chunk.id.in_(chunk_ids))).all()
    by = {c.id: Passage(c.id, d.id, d.filename, d.version, d.kind, d.chapter, c.page, c.text) for c, d in rows}
    return [by[i] for i in chunk_ids if i in by]


def _passages_block(passages: list[Passage]) -> tuple[str, dict[str, Passage]]:
    by_id = {f"C{p.chunk_id}": p for p in passages}
    parts = ["<approved_material>"]
    for sid, p in by_id.items():
        label = f"{p.filename} v{p.version}" + (f" · {p.chapter}" if p.chapter else "") + f" · page {p.page}"
        parts.append(f'<passage id="{sid}" kind="{p.kind}" source="{label}">\n{p.text}\n</passage>')
    parts.append("</approved_material>")
    return "\n".join(parts), by_id


def _brief(plan: Plan) -> str:
    sc, exam, settings, scope = plan.school_class, plan.exam, plan.settings, plan.scope
    counts = {k: v for k, v in settings["counts"].items() if v}
    total = sum(counts.values())
    lines = [
        "Write a practice worksheet from the approved material above.",
        "",
        f"Class: {sc.grade}" + (f" (sections {exam.sections})" if exam.sections else ""),
        f"Subject: {exam.subject_name}",
        f"Exam: {fmt_date(exam.exam_date)} (exam ID {exam.exam_code})",
        f"Language: {settings.get('language', 'English')}",
        "",
        f"Questions per section type ({total} in total, emit sections in this order):",
        *[f"- {k} ({SECTION_LABELS[k]}): {n}" for k, n in sorted(counts.items(), key=lambda x: SECTION_ORDER.index(x[0]))],
        "",
        "Difficulty mix across the whole worksheet: " + ", ".join(f"{p}% {lvl}" for lvl, p in settings["difficulty"].items()),
        "Answers: " + ("write a model answer for every question (it becomes the answer key)." if settings.get("answer_key")
                       else "still write a brief answer for every question; it is used for review only."),
        "",
        "In coverage_plan, list each topic you covered with the question refs that cover it, where a ref is the "
        "section letter (A for the first section you emit, B for the next, …) and question number, like \"A-2\".",
    ]
    if settings.get("language") == "Hindi":
        lines += ["", "<language>",
                  "Write the whole worksheet in Hindi (Devanagari script): title, instructions, questions, options and answers. "
                  "Use simple, standard Hindi as used in school textbooks (NCERT style)."
                  + (" This is the Hindi language subject: test the Hindi passages themselves (grammar, vocabulary, "
                     "comprehension, literature) exactly as they are written." if is_hindi_subject(exam.subject_name) else
                     " If the passages are in English, translate the ideas faithfully; keep standard technical terms and "
                     "you may add the English term in brackets the first time, e.g. परिमेय संख्या (rational number).")
                  + " Keep numbers as 0-9, and keep units, variables and formulas in standard notation.",
                  "The title follows this form: \"<विषय> अभ्यास पत्रक – कक्षा <n> – परीक्षा <day> <महीना>\".",
                  "</language>"]
    lines += ["", "<notation>",
              "The worksheet is printed as a PDF that cannot render LaTeX or Markdown. Write all maths in plain Unicode "
              "notation: x², a³, √2, ∛27, ¾ or 3/4, π, θ, ×, ÷, ±, ≤, ≥, ≠, ∠ABC, △ABC, 60°, AB ∥ CD, AB ⊥ CD. "
              "Never use $…$, \\frac, \\sqrt, ^{…} or **bold**. For a long fraction use brackets: (x + 1)/(x − 1).",
              "</notation>", "", "<exam_syllabus>",
              "This is the school's official syllabus for this exam. It is the boundary: every question must "
              "test something listed here, even if the passages above mention other material. Flag anything "
              "that goes beyond it as outside_syllabus.",
              scope["text"], "</exam_syllabus>"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Offline generator: builds questions straight from the retrieved sentences. Used when
# LLM_PROVIDER=offline (development, tests, demos without an API key). Clearly labelled in the UI.

def _sentences(passages: list[Passage]) -> list[tuple[str, str]]:
    out, seen = [], set()
    for p in passages:
        if p.kind == "syllabus" and any(q.kind != "syllabus" for q in passages):
            continue
        for s in re.split(r"(?<=[.!?।])\s+|\n+", p.text):
            s = s.strip()
            n = len(s.split())
            key = s.lower()[:60]
            if 7 <= n <= 45 and key not in seen and re.search(r"[a-zA-Zऀ-ॿ]{3}", s):
                seen.add(key)
                out.append((f"C{p.chunk_id}", s))
    return out


def _difficulty_plan(total: int, mix: dict) -> list[str]:
    counts = {k: math.floor(total * v / 100) for k, v in mix.items()}
    order = sorted(mix, key=lambda k: -(total * mix[k] / 100 - counts[k]))
    for k in order[: total - sum(counts.values())]:
        counts[k] += 1
    return ["easy"] * counts.get("easy", 0) + ["medium"] * counts.get("medium", 0) + ["hard"] * counts.get("hard", 0)


def generate_offline(plan: Plan) -> dict:
    passages = plan.passages
    rng = random.Random(f"{plan.exam.id}-{plan.exam.exam_date}")
    sents = _sentences(passages)
    if not sents:
        raise BlockedError("The subject PDFs contain no readable text to build questions from.")
    index = SubjectIndex(passages)
    rng.shuffle(sents)

    def keyterm(sentence: str) -> str | None:
        toks = [t for t in tokenize(sentence) if not t.isdigit() and len(t) > 4]
        return max(toks, key=lambda t: (index.idf.get(t, 0), len(t))) if toks else None

    pool = [(sid, s, keyterm(s)) for sid, s in sents]
    pool = [x for x in pool if x[2]]
    all_terms = sorted({t for _, _, t in pool})
    counts = {k: v for k, v in plan.settings["counts"].items() if v}
    diffs = _difficulty_plan(sum(counts.values()), plan.settings["difficulty"])
    sections, coverage, cursor, used = [], {}, 0, 0
    for si, typ in enumerate([t for t in SECTION_ORDER if t in counts]):
        qs = []
        for qi in range(counts[typ]):
            sid, s, term = pool[cursor % len(pool)]
            cursor += 1
            difficulty = diffs[min(used, len(diffs) - 1)]
            used += 1
            topic = next((p.chapter for p in passages if f"C{p.chunk_id}" == sid and p.chapter), plan.exam.subject_name)
            if typ == "mcq":
                others = [t for t in all_terms if t != term]
                rng.shuffle(others)
                opts = [term] + others[:3]
                while len(opts) < 4:
                    opts.append(f"none of the above ({len(opts)})")
                rng.shuffle(opts)
                blank = re.sub(re.escape(term), "_____", s, count=1, flags=re.I)
                q = {"text": f"Choose the word that completes the statement: \"{blank}\"", "options": opts, "answer": term}
            elif typ == "very_short":
                lead = " ".join(s.split()[: max(6, len(s.split()) // 2)])
                q = {"text": f"Complete in one sentence, explaining the term \"{term}\": \"{lead} …\"", "options": [], "answer": s}
            elif typ == "short":
                q = {"text": f"Explain the following statement in your own words, with one example: \"{s}\"", "options": [], "answer": s}
            elif typ == "application":
                q = {"text": f"Apply the idea of \"{term}\" to a real-life situation. Base your answer on: \"{s}\"", "options": [], "answer": s}
            else:
                extra = pool[cursor % len(pool)]
                cursor += 1
                verb = "Justify, giving reasons," if typ == "hots" else "Write a detailed answer"
                q = {"text": f"{verb} on how \"{term}\" and \"{extra[2]}\" are connected. Refer to: \"{s}\" and \"{extra[1]}\"",
                     "options": [], "answer": f"{s} {extra[1]}"}
                sid = [sid, extra[0]]
            q.update({"difficulty": difficulty, "topic": topic, "source_ids": sid if isinstance(sid, list) else [sid],
                      "outside_syllabus": False, "review_note": ""})
            qs.append(q)
            coverage.setdefault(topic, []).append(f"{'ABCDEF'[si]}-{qi + 1}")
        sections.append({"type": typ, "questions": qs})
    lang = plan.settings.get("language", "English")
    return {"title": standard_title(plan.exam, plan.school_class.grade, lang), "instructions": standard_instructions(lang),
            "coverage_plan": [{"topic": t, "question_refs": r} for t, r in coverage.items()], "sections": sections}


# ------------------------------------------------------------------------------------------- helpers

def _normalize(content: dict) -> dict:
    """Keep sections in the canonical order and drop empty ones."""
    secs = [s for s in content.get("sections", []) if s.get("questions")]
    secs.sort(key=lambda s: SECTION_ORDER.index(s["type"]) if s.get("type") in SECTION_ORDER else 99)
    content["sections"] = secs
    return content


def sources_for(content: dict, by_id: dict[str, Passage]) -> list[dict]:
    used: dict[int, dict] = {}
    for sec in content.get("sections", []):
        for q in sec.get("questions", []):
            for sid in q.get("source_ids", []):
                p = by_id.get(sid)
                if p:
                    e = used.setdefault(p.document_id, {"document_id": p.document_id, "filename": p.filename,
                                                          "version": p.version, "chapter": p.chapter, "passages": 0})
                    e["passages"] += 1
    return sorted(used.values(), key=lambda e: (e["filename"]))


def _supersede(db: Session, exam_id: int) -> None:
    for old in db.scalars(select(Worksheet).where(Worksheet.exam_id == exam_id,
                                                  Worksheet.status.in_(["awaiting-approval", "validation-failed"]))):
        old.status = "superseded"


def _next_version(db: Session, exam_id: int) -> int:
    return (db.scalar(select(func.max(Worksheet.version)).where(Worksheet.exam_id == exam_id)) or 0) + 1


# ------------------------------------------------------------------------------------------- reuse

def _settings_key(s: dict) -> tuple:
    return (tuple(sorted((s.get("counts") or {}).items())), tuple(sorted((s.get("difficulty") or {}).items())),
            bool(s.get("answer_key")), s.get("language"))


def reuse_key(plan: Plan) -> str:
    """Identifies worksheets that can be shared: same grade, subject, syllabus text and settings."""
    import hashlib
    raw = repr((str(plan.school_class.grade), plan.exam.subject_name.strip().lower(), plan.scope.get("text", "").strip(),
                _settings_key(plan.settings)))
    return hashlib.sha1(raw.encode()).hexdigest()


def sibling_in_flight(db: Session, job: Job, key: str) -> Job | None:
    """Another job already writing the same worksheet (e.g. section A and B triggered on the same day)."""
    for other in db.scalars(select(Job).where(Job.type == "CREATE_WORKSHEET", Job.id != job.id,
                                              Job.status.in_(["pending", "running"]))):
        p = other.payload or {}
        if p.get("batch_id") and p.get("reuse_key") == key and abs((other.exam_date - job.exam_date).days) <= REUSE_WINDOW_DAYS:
            return other
    return None


def find_reusable(db: Session, plan: Plan) -> Worksheet | None:
    """A worksheet this term for the same grade, subject, language, exam syllabus and settings, made for another
    exam row (another section, or another class of the same grade)."""
    exam = plan.exam
    lo, hi = exam.exam_date - timedelta(days=REUSE_WINDOW_DAYS), exam.exam_date + timedelta(days=REUSE_WINDOW_DAYS)
    rows = db.execute(select(Worksheet, SchoolClass).join(SchoolClass, Worksheet.class_id == SchoolClass.id).where(
        func.lower(Worksheet.subject_name) == exam.subject_name.strip().lower(), SchoolClass.grade == plan.school_class.grade,
        Worksheet.status.in_(["released", "awaiting-approval"]), Worksheet.exam_date.between(lo, hi),
        Worksheet.exam_id != exam.id)).all()
    key = _settings_key(plan.settings)
    matches = [w for w, _ in rows
               if (w.content.get("_scope") or {}).get("text", "").strip() == plan.scope.get("text", "").strip()
               and _settings_key(w.settings_used or {}) == key and not (w.generator or "").startswith("offline")]
    matches.sort(key=lambda w: (w.status != "released", -w.id))  # approved ones first, then newest
    return matches[0] if matches else None


# ------------------------------------------------------------------------------------------- main

def create_worksheet(db: Session, job: Job) -> Worksheet:
    """Raises Pending while a batch request is in flight; BlockedError when configuration is missing."""
    plan = prepare(db, job)
    cfg = get_settings()
    payload = job.payload or {}

    # A batch submitted on an earlier tick: collect the result, or give up waiting and call directly.
    if payload.get("batch_id"):
        plan.passages = passages_by_ids(db, payload.get("chunk_ids", []))
        result = llm.poll_worksheet_batch(payload["batch_id"])
        if result is None:
            submitted = datetime.fromisoformat(payload["submitted_at"])
            if utcnow() - submitted < timedelta(hours=cfg.llm_batch_timeout_hours):
                raise Pending("The worksheet is being written (batch request in progress).")
            llm.cancel_batch(payload["batch_id"])
            audit(db, "retry", f"The batch took too long; writing {plan.exam.subject_name} directly",
                  class_id=plan.school_class.id, job_id=job.id, level="warning")
            block, _ = _passages_block(plan.passages)
            result = llm.generate_worksheet_json(block, _brief(plan))
            job.payload = None
            return finalize(db, job, plan, result[0], result[1])
        job.payload = None
        return finalize(db, job, plan, result[0], f"{result[1]} (batch)")

    # Reuse a matching worksheet from another section or class (not for explicit regenerations). If the matching
    # worksheet is still being written in a batch, wait for it rather than paying to write it twice.
    reusing = get_setting(db, "reuse_worksheets") and job.source != "regenerate"
    key = reuse_key(plan)
    if reusing:
        src = find_reusable(db, plan)
        if src is not None:
            return finalize_reuse(db, job, plan, src)
        if sibling_in_flight(db, job, key):
            raise Pending("Waiting for the same worksheet being written for another section, to reuse it.")

    load_material(db, plan)
    if cfg.llm_provider == "offline":
        return finalize(db, job, plan, generate_offline(plan), "offline (no model)")

    block, _ = _passages_block(plan.passages)
    brief = _brief(plan)
    if get_setting(db, "use_batch") and job.source == "scheduler":
        batch_id = llm.submit_worksheet_batch(f"job-{job.id}", block, brief)
        job.payload = {"batch_id": batch_id, "submitted_at": utcnow().isoformat(), "reuse_key": key,
                       "chunk_ids": [p.chunk_id for p in plan.passages]}
        audit(db, "job", f"{plan.exam.subject_name} · {plan.school_class.name}: sent to the batch queue (50% cheaper)",
              class_id=plan.school_class.id, job_id=job.id, batch_id=batch_id)
        raise Pending("The worksheet is being written (batch request submitted).")
    content, served_by = llm.generate_worksheet_json(block, brief)
    return finalize(db, job, plan, content, served_by)


def finalize(db: Session, job: Job, plan: Plan, content: dict, generator: str) -> Worksheet:
    sc, exam = plan.school_class, plan.exam
    content = normalize_content(_normalize(content))  # LaTeX leftovers → x², √2, ¾ …
    _, by_id = _passages_block(plan.passages)
    passage_text = {sid: p.text for sid, p in by_id.items()}
    scope_ids = set(by_id)  # every passage handed to the generator is inside the exam syllabus
    result = validate(content, plan.settings, passage_text, scope_ids)

    _supersede(db, exam.id)
    version = _next_version(db, exam.id)
    ws = Worksheet(class_id=sc.id, exam_id=exam.id, create_job_id=job.id, subject_name=exam.subject_name,
                   sections=exam.sections, exam_code=exam.exam_code, exam_date=exam.exam_date, version=version,
                   title=content.get("title") or standard_title(exam, sc.grade, plan.settings["language"]), content=content,
                   settings_used=plan.settings, validation=result, sources=sources_for(content, by_id),
                   generator=generator, regeneration_reason=(job.last_error if job.source == "regenerate" else None))
    ws.content["_passages"] = {sid: {"text": p.text[:1500], "source": f"{p.filename} v{p.version}", "page": p.page}
                               for sid, p in by_id.items()
                               if any(sid in q.get("source_ids", []) for s in content["sections"] for q in s["questions"])}
    ws.content["_scope"] = {"text": plan.scope["text"], "chapters": plan.scope.get("chapters", []), "ids": sorted(scope_ids),
                            "file": sc.syllabus_file}
    db.add(ws)
    db.flush()
    ws.pdf_path = str(render_worksheet_pdf(ws, sc))
    audit(db, "generation", f"Generated {ws.title} · v{version}", class_id=sc.id, job_id=job.id,
          worksheet_id=ws.id, exam=exam.exam_code, subject=exam.subject_name, generator=generator,
          source_versions=[f"{s['filename']} v{s['version']}" for s in ws.sources])
    audit(db, "validation", f"Validation {result['summary'].lower()} · {ws.title} · v{version}",
          class_id=sc.id, level="info" if result["passed"] else "warning", worksheet_id=ws.id,
          checks=[{c['label']: c['status']} for c in result["checks"]])
    return ws


def finalize_reuse(db: Session, job: Job, plan: Plan, src: Worksheet) -> Worksheet:
    """Copy the questions of a matching worksheet. This exam row still gets its own worksheet record, its own
    review/approval and its own deliveries to all of its sections' students."""
    sc, exam = plan.school_class, plan.exam
    src_class = db.get(SchoolClass, src.class_id)
    content = copy.deepcopy(src.content)
    content["title"] = standard_title(exam, sc.grade, plan.settings["language"])
    _supersede(db, exam.id)
    version = _next_version(db, exam.id)
    label = f"{src_class.name}{('-' + src.sections) if src.sections else ''}"
    ws = Worksheet(class_id=sc.id, exam_id=exam.id, create_job_id=job.id, subject_name=exam.subject_name,
                   sections=exam.sections, exam_code=exam.exam_code, exam_date=exam.exam_date, version=version,
                   title=content["title"], content=content, settings_used=copy.deepcopy(src.settings_used),
                   validation=copy.deepcopy(src.validation), sources=copy.deepcopy(src.sources),
                   generator=f"reused from {label} (v{src.version})", reused_from_id=src.id)
    db.add(ws)
    db.flush()
    revalidate(db, ws)
    ws.pdf_path = str(render_worksheet_pdf(ws, sc))
    audit(db, "generation", f"Reused the {label} worksheet for {sc.name}{('-' + exam.sections) if exam.sections else ''} · "
                            f"{exam.subject_name} · no AI cost", class_id=sc.id, job_id=job.id, worksheet_id=ws.id, reused_from=src.id)
    return ws


def revalidate(db: Session, ws: Worksheet) -> dict:
    """After a manual edit or a reuse: re-run checks against the passages the worksheet was built from."""
    passages = {sid: p["text"] for sid, p in ws.content.get("_passages", {}).items()}
    for sec in ws.content.get("sections", []):
        for q in sec.get("questions", []):
            for sid in q.get("source_ids", []):
                if sid not in passages and re.fullmatch(r"C\d+", sid):
                    c = db.get(Chunk, int(sid[1:]))
                    if c and c.document.subject.class_id == ws.class_id:
                        passages[sid] = c.text
    scope = ws.content.get("_scope")
    result = validate(ws.content, ws.settings_used, passages, set(scope["ids"]) if scope else None)
    ws.validation = result
    return result
