"""Class workspace: class config, date sheet, exams, subjects + PDFs, students, worksheet settings."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Document, Exam, Job, SchoolClass, Student, Subject, Worksheet, utcnow
from ..orchestrator import cancel_obsolete, manual_generate, readiness_problems
from ..security import get_class_for, require_admin, require_staff
from ..models import User
from ..services.common import (LANGUAGES, SECTION_LABELS, audit, is_hindi_subject, worksheet_language, fmt_date, fmt_day_month, get_setting, local_today, mask_email,
                               mask_phone, merge_worksheet_settings, normalize_whatsapp, valid_email)
from ..services.documents import ingest_pdf
from ..services.tabular import parse_datesheet, parse_students
from ..worker import worker

router = APIRouter(prefix="/api")
MAX_UPLOAD = 40 * 1024 * 1024


async def _read(upload: UploadFile) -> bytes:
    data = await upload.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The file is larger than 40 MB.")
    if not data:
        raise HTTPException(400, "The file is empty.")
    return data


# --------------------------------------------------------------------------------------- classes
class ClassIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    grade: str | None = None
    academic_year: str = "2026–27"
    sections: str = "A"


class ClassPatch(BaseModel):
    name: str | None = None
    academic_year: str | None = None
    sections: str | None = None
    release_mode: str | None = Field(default=None, pattern="^(review|auto)$")
    channel_email: bool | None = None
    channel_whatsapp: bool | None = None


def _lead(db: Session) -> int:
    return int(get_setting(db, "lead_days") or 2)


def next_trigger(db: Session, c: SchoolClass) -> str | None:
    today = local_today(db)
    lead = _lead(db)
    upcoming = [e for e in c.exams if e.active and e.exam_date - timedelta(days=lead) >= today]
    if not upcoming:
        return None
    e = min(upcoming, key=lambda x: x.exam_date)
    return f"{fmt_day_month(e.exam_date - timedelta(days=lead))} · {e.subject_name}"


def class_card(db: Session, c: SchoolClass) -> dict:
    today = local_today(db)
    return {"id": c.id, "name": c.name, "grade": c.grade, "academic_year": c.academic_year, "sections": c.sections,
            "students": sum(1 for s in c.students if s.active), "subjects": len(c.subjects),
            "exams": sum(1 for e in c.exams if e.active and e.exam_date >= today),
            "automation": c.automation, "next_trigger": next_trigger(db, c) if c.automation == "active" else None}


def _grade_from_name(name: str) -> str:
    import re
    m = re.search(r"\d+", name)
    return m.group(0) if m else name.strip()


@router.get("/classes")
def list_classes(user: User = Depends(require_staff), db: Session = Depends(get_db)):
    rows = db.scalars(select(SchoolClass))
    visible = [c for c in rows if user.role == "admin" or c.id in (user.class_access or [])]
    visible.sort(key=lambda c: (int(c.grade) if c.grade.isdigit() else 99, c.name))
    return [class_card(db, c) for c in visible]


@router.post("/classes")
def create_class(body: ClassIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(SchoolClass).where(func.lower(SchoolClass.name) == body.name.strip().lower())):
        raise HTTPException(409, f"{body.name} already exists.")
    c = SchoolClass(name=body.name.strip(), grade=(body.grade or _grade_from_name(body.name)).strip(),
                    academic_year=body.academic_year, sections=_norm_sections(body.sections))
    db.add(c)
    db.flush()
    audit(db, "class", f"Created {c.name}", actor=admin.email, class_id=c.id)
    db.commit()
    return class_card(db, c)


def _norm_sections(s: str) -> str:
    return ", ".join(dict.fromkeys(p.strip().upper() for p in s.split(",") if p.strip())) or "A"


@router.get("/classes/{class_id}")
def get_class(class_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    c = get_class_for(db, user, class_id)
    return workspace(db, c)


def workspace(db: Session, c: SchoolClass) -> dict:
    docs = db.scalars(select(Document).join(Subject).where(Subject.class_id == c.id, Document.active.is_(True))).all()
    students = [s for s in c.students if s.active]
    missing_wa = sum(1 for s in students if not s.whatsapp)
    missing_email = sum(1 for s in students if not valid_email(s.email))
    settings = merge_worksheet_settings(get_setting(db, "worksheet_defaults"), c.worksheet_settings)
    total_q = sum(settings["counts"].values())
    subject_names = {s.name.lower() for s in c.subjects}
    subjects_without_pdfs = [s.name for s in c.subjects if not any(d.active and d.extraction == "ok" for d in s.documents)]
    active_exams = [e for e in c.exams if e.active]
    exam_subjects_missing = sorted({e.subject_name for e in active_exams if e.subject_name.lower() not in subject_names})
    syllabus_missing = sorted({e.subject_name for e in active_exams
                               if e.subject_name.lower() not in (c.syllabus_scope or {})}) if c.syllabus_confirmed else []
    readiness = [
        {"id": "datesheet", "label": "Date sheet",
         "ready": bool(c.datesheet_file and c.datesheet_confirmed),
         "detail": (f"{len(active_exams)} exams" + ("" if c.datesheet_confirmed else " · not confirmed"))
         if c.datesheet_file else "Not uploaded"},
        {"id": "syllabus", "label": "Exam syllabus",
         "ready": bool(c.syllabus_file and c.syllabus_confirmed) and not syllabus_missing,
         "detail": (f"{len(c.syllabus_scope or {})} subjects" + ("" if c.syllabus_confirmed else " · not confirmed")
                    + (f" · missing {', '.join(syllabus_missing)}" if syllabus_missing else ""))
         if c.syllabus_file else "Not uploaded"},
        {"id": "subjects", "label": "Subject PDFs",
         "ready": bool(c.subjects) and not subjects_without_pdfs and not exam_subjects_missing,
         "detail": (f"{len(c.subjects)} subjects · {len(docs)} files"
                    + (f" · no PDFs for {', '.join(subjects_without_pdfs)}" if subjects_without_pdfs else "")
                    + (f" · no subject for {', '.join(exam_subjects_missing)}" if exam_subjects_missing else ""))
         if c.subjects else "No subjects yet"},
        {"id": "students", "label": "Students", "ready": bool(students),
         "detail": (f"{len(students)}" + (f" · {missing_email} without a valid email" if missing_email else "")
                    + (f" · {missing_wa} missing WhatsApp" if missing_wa else "")) if students else "Not uploaded"},
        {"id": "settings", "label": "Worksheet settings", "ready": total_q > 0,
         "detail": f"{total_q} questions · answer key {'on' if settings.get('answer_key') else 'off'}"},
    ]
    return {**class_card(db, c), "release_mode": c.release_mode, "channel_email": c.channel_email,
            "channel_whatsapp": c.channel_whatsapp, "phase": int(get_setting(db, "phase") or 1),
            "scheduler_time": get_setting(db, "scheduler_time"), "timezone": get_setting(db, "timezone"),
            "lead_days": _lead(db), "datesheet": datesheet_state(db, c), "syllabus": syllabus_state(c),
            "readiness": readiness,
            "problems": readiness_problems(db, c), "subject_count": len(c.subjects),
            "student_count": len(students)}


@router.patch("/classes/{class_id}")
def patch_class(class_id: int, body: ClassPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = get_class_for(db, admin, class_id)
    changes = body.model_dump(exclude_none=True)
    if "sections" in changes:
        changes["sections"] = _norm_sections(changes["sections"])
    for k, v in changes.items():
        setattr(c, k, v)
    audit(db, "class", f"{c.name} · updated " + ", ".join(f"{k} → {v}" for k, v in changes.items()),
          actor=admin.email, class_id=c.id)
    db.commit()
    return workspace(db, c)


@router.delete("/classes/{class_id}")
def delete_class(class_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = get_class_for(db, admin, class_id)
    if c.automation == "active":
        raise HTTPException(409, "Pause automation before deleting this class.")
    audit(db, "class", f"Deleted {c.name}", actor=admin.email)
    db.delete(c)
    db.commit()
    return {"ok": True}


class AutomationIn(BaseModel):
    action: str = Field(pattern="^(activate|pause)$")


@router.post("/classes/{class_id}/automation")
def set_automation(class_id: int, body: AutomationIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = get_class_for(db, admin, class_id)
    if body.action == "activate":
        problems = readiness_problems(db, c)
        if problems:
            raise HTTPException(409, "Automation can't start yet. " + " ".join(problems))
        c.automation = "active"
        audit(db, "automation", f"{c.name} · automation activated ({c.release_mode} release)", actor=admin.email, class_id=c.id)
    else:
        c.automation = "paused"
        audit(db, "automation", f"{c.name} · automation paused", actor=admin.email, class_id=c.id, level="warning")
    db.commit()
    return workspace(db, c)


# ------------------------------------------------------------------------------------ date sheet
def _exam_row(db: Session, e: Exam, jobs: dict[int, Job], ws: dict[int, Worksheet]) -> dict:
    lead = _lead(db)
    job = jobs.get(e.id)
    w = ws.get(e.id)
    status = w.status if w and w.status not in ("superseded",) else (job.status if job else "pending")
    if w and w.status == "released" and job and job.status == "completed":
        status = "completed"
    return {"id": e.id, "exam_code": e.exam_code, "subject": e.subject_name, "sections": e.sections or "All",
            "exam_date": fmt_date(e.exam_date), "exam_date_iso": e.exam_date.isoformat(), "time": e.exam_time or "—",
            "trigger": fmt_day_month(e.exam_date - timedelta(days=lead)),
            "past": e.exam_date < local_today(db), "status": status, "worksheet_id": w.id if w else None,
            "in_progress": bool(job and job.status in ("pending", "running") and not w),
            "reused": bool(w and w.reused_from_id),
            "job_error": job.last_error if job and job.status == "failed" else None}


def datesheet_state(db: Session, c: SchoolClass) -> dict:
    exams = sorted([e for e in c.exams if e.active], key=lambda e: (e.exam_date, e.subject_name))
    jobs: dict[int, Job] = {}
    for j in db.scalars(select(Job).where(Job.class_id == c.id, Job.type == "CREATE_WORKSHEET").order_by(Job.id)):
        if j.exam_id:
            jobs[j.exam_id] = j
    ws: dict[int, Worksheet] = {}
    for w in db.scalars(select(Worksheet).where(Worksheet.class_id == c.id, Worksheet.status != "superseded").order_by(Worksheet.id)):
        if w.exam_id:
            ws[w.exam_id] = w
    pending = c.datesheet_pending
    scope = (c.syllabus_scope or {}) if c.syllabus_confirmed else {}
    rows = [_exam_row(db, e, jobs, ws) for e in exams]
    for r in rows:
        entry = scope.get(r["subject"].lower())
        r["syllabus"] = (("Ch " + ", ".join(map(str, entry["chapters"]))) if entry["chapters"]
                         else f"{len(entry['topics'])} topics") if entry else None
    return {"file": c.datesheet_file,
            "uploaded_at": fmt_date(c.datesheet_uploaded_at.date()) if c.datesheet_uploaded_at else None,
            "confirmed": c.datesheet_confirmed, "issues": c.datesheet_issues or [],
            "exams": rows,
            "pending": pending}


@router.post("/classes/{class_id}/datesheet")
async def upload_datesheet(class_id: int, file: UploadFile = File(...), admin: User = Depends(require_admin),
                           db: Session = Depends(get_db)):
    """Parse and preview. Nothing changes until the admin confirms."""
    c = get_class_for(db, admin, class_id)
    data = await _read(file)
    try:
        exams, issues = parse_datesheet(file.filename or "datesheet.xlsx", data, c.grade, c.section_list())
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(400, "The file could not be read. Upload an .xlsx or .csv date sheet.")
    today = local_today(db)
    lead = _lead(db)
    rows = [{**e, "exam_date": e["exam_date"].isoformat(), "exam_date_label": fmt_date(e["exam_date"]),
             "trigger": fmt_day_month(e["exam_date"] - timedelta(days=lead)),
             "past": e["exam_date"] < today, "late": today <= e["exam_date"] < today + timedelta(days=lead)} for e in exams]
    c.datesheet_pending = {"file": file.filename, "rows": rows, "issues": issues, "uploaded_by": admin.email,
                           "uploaded_at": utcnow().isoformat()}
    audit(db, "upload", f"{c.name} · date sheet {file.filename} uploaded · {len(rows)} exams, {len(issues)} issues",
          actor=admin.email, class_id=c.id, file=file.filename)
    db.commit()
    return datesheet_state(db, c)


@router.post("/classes/{class_id}/datesheet/discard")
def discard_datesheet(class_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = get_class_for(db, admin, class_id)
    c.datesheet_pending = None
    db.commit()
    return datesheet_state(db, c)


@router.post("/classes/{class_id}/datesheet/confirm")
def confirm_datesheet(class_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Apply the previewed schedule: match exams by exam ID, update changed rows, retire removed ones,
    then cancel jobs for exams that moved or disappeared."""
    c = get_class_for(db, admin, class_id)
    p = c.datesheet_pending
    if not p:
        if c.datesheet_file and not c.datesheet_confirmed:
            c.datesheet_confirmed = True
            audit(db, "datesheet", f"{c.name} · date sheet confirmed", actor=admin.email, class_id=c.id)
            db.commit()
            return datesheet_state(db, c)
        raise HTTPException(409, "There is no uploaded date sheet to confirm.")
    if not p["rows"]:
        raise HTTPException(409, "The uploaded date sheet has no valid rows. Fix the issues and upload again.")
    existing = {e.exam_code: e for e in c.exams if e.active}
    seen = set()
    changed = 0
    for r in p["rows"]:
        d = date.fromisoformat(r["exam_date"])
        e = existing.get(r["exam_code"])
        if e:
            if (e.subject_name, e.sections, e.exam_date, e.exam_time) != (r["subject_name"], r["sections"], d, r["exam_time"]):
                changed += 1
                # A moved exam becomes a new exam row, so its old jobs are cancelled and new ones created cleanly.
                e.active = False
                c.exams.append(Exam(exam_code=r["exam_code"], subject_name=r["subject_name"], sections=r["sections"],
                                    exam_date=d, exam_time=r["exam_time"]))
        else:
            c.exams.append(Exam(exam_code=r["exam_code"], subject_name=r["subject_name"], sections=r["sections"],
                                exam_date=d, exam_time=r["exam_time"]))
        seen.add(r["exam_code"])
    removed = [e for code, e in existing.items() if code not in seen]
    for e in removed:
        e.active = False
    db.flush()
    cancelled = cancel_obsolete(db, c.id, admin.email)
    c.datesheet_file, c.datesheet_uploaded_at = p["file"], datetime.fromisoformat(p["uploaded_at"])
    c.datesheet_issues, c.datesheet_pending, c.datesheet_confirmed = p["issues"], None, True
    audit(db, "datesheet", f"{c.name} · date sheet {p['file']} confirmed · {len(p['rows'])} exams"
          + (f" · {changed} changed, {len(removed)} removed, {cancelled} jobs cancelled" if existing else ""),
          actor=admin.email, class_id=c.id)
    db.commit()
    return datesheet_state(db, c)


# --------------------------------------------------------------------------------- exam syllabus
def _syllabus_subjects(c: SchoolClass) -> list[str]:
    """Subjects the syllabus should cover: those on the date sheet (pending or live), then class subjects."""
    names = [e.subject_name for e in c.exams if e.active]
    if c.datesheet_pending:
        names += [r["subject_name"] for r in c.datesheet_pending.get("rows", [])]
    names += [s.name for s in c.subjects]
    return list(dict.fromkeys(names))


def syllabus_state(c: SchoolClass) -> dict:
    required = [e.subject_name for e in c.exams if e.active]
    scope = c.syllabus_scope or {}
    return {"file": c.syllabus_file,
            "uploaded_at": fmt_date(c.syllabus_uploaded_at.date()) if c.syllabus_uploaded_at else None,
            "confirmed": c.syllabus_confirmed,
            "entries": sorted(scope.values(), key=lambda e: e["subject"]),
            "missing": sorted({s for s in required if s.lower() not in scope}) if c.syllabus_confirmed else [],
            "pending": c.syllabus_pending}


def _xlsx(data: bytes, name: str):
    from fastapi.responses import Response
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/classes/{class_id}/datesheet/template.xlsx")
def datesheet_template(class_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    from ..services.templates import datesheet_template as build
    c = get_class_for(db, user, class_id)
    subjects = [s.name for s in sorted(c.subjects, key=lambda s: s.name)]
    return _xlsx(build(c.grade, c.section_list(), subjects), f"DateSheet_{c.name.replace(' ', '_')}.xlsx")


@router.get("/classes/{class_id}/syllabus/template.xlsx")
def syllabus_template(class_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    from ..services.templates import syllabus_template as build
    c = get_class_for(db, user, class_id)
    return _xlsx(build(_syllabus_subjects(c)), f"Syllabus_{c.name.replace(' ', '_')}.xlsx")


@router.get("/classes/{class_id}/syllabus")
def get_syllabus(class_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return syllabus_state(get_class_for(db, user, class_id))


@router.post("/classes/{class_id}/syllabus")
async def upload_syllabus(class_id: int, file: UploadFile = File(...), admin: User = Depends(require_admin),
                          db: Session = Depends(get_db)):
    """Parse and preview. The live scope only changes when the admin confirms."""
    from ..services.syllabus import parse_syllabus, store_file
    c = get_class_for(db, admin, class_id)
    data = await _read(file)
    try:
        entries, issues, raw = parse_syllabus(file.filename or "syllabus.pdf", data, _syllabus_subjects(c))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(400, "The syllabus file could not be read.")
    path = store_file(c.id, file.filename or "syllabus", data)
    c.syllabus_pending = {"file": file.filename, "path": str(path), "entries": sorted(entries.values(), key=lambda e: e["subject"]),
                          "issues": issues, "raw": raw, "uploaded_at": utcnow().isoformat(), "uploaded_by": admin.email}
    audit(db, "upload", f"{c.name} · exam syllabus {file.filename} uploaded · {len(entries)} subjects, {len(issues)} issues",
          actor=admin.email, class_id=c.id, file=file.filename)
    db.commit()
    return syllabus_state(c)


class SyllabusEntryIn(BaseModel):
    subject: str = Field(min_length=1)
    text: str


class SyllabusEntriesIn(BaseModel):
    entries: list[SyllabusEntryIn]


@router.put("/classes/{class_id}/syllabus/pending")
def edit_pending_syllabus(class_id: int, body: SyllabusEntriesIn, admin: User = Depends(require_admin),
                          db: Session = Depends(get_db)):
    """Correct the parsed scope before confirming (fix a split, add a missing subject)."""
    from ..services.syllabus import make_entry
    c = get_class_for(db, admin, class_id)
    if not c.syllabus_pending:
        raise HTTPException(409, "There is no uploaded syllabus to edit.")
    entries = [make_entry(e.subject.strip(), e.text) for e in body.entries if e.text.strip()]
    have = {e["subject"].lower() for e in entries}
    issues = [{"subject": s, "message": f"No syllabus found for {s}. Add it below before confirming."}
              for s in dict.fromkeys(e.subject_name for e in c.exams if e.active) if s.lower() not in have]
    c.syllabus_pending = {**c.syllabus_pending, "entries": entries, "issues": issues}
    db.commit()
    return syllabus_state(c)


@router.post("/classes/{class_id}/syllabus/discard")
def discard_syllabus(class_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = get_class_for(db, admin, class_id)
    c.syllabus_pending = None
    db.commit()
    return syllabus_state(c)


@router.post("/classes/{class_id}/syllabus/confirm")
def confirm_syllabus(class_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = get_class_for(db, admin, class_id)
    p = c.syllabus_pending
    if not p:
        raise HTTPException(409, "There is no uploaded syllabus to confirm.")
    if not p["entries"]:
        raise HTTPException(409, "No subject syllabus was found. Edit the preview or upload a clearer file.")
    old = c.syllabus_scope or {}
    new = {e["subject"].lower(): e for e in p["entries"]}
    changed = sorted(k for k in set(old) | set(new) if (old.get(k) or {}).get("text") != (new.get(k) or {}).get("text"))
    c.syllabus_scope = new
    c.syllabus_file, c.syllabus_path = p["file"], p["path"]
    c.syllabus_uploaded_at = datetime.fromisoformat(p["uploaded_at"])
    c.syllabus_pending, c.syllabus_confirmed = None, True
    # Unreleased worksheets built against an older scope must not be released as-is.
    stale = 0
    if old:
        for w in db.scalars(select(Worksheet).where(Worksheet.class_id == c.id,
                                                    Worksheet.status.in_(["awaiting-approval", "validation-failed"]))):
            if w.subject_name.lower() in changed:
                w.status = "validation-failed"
                w.validation = {**w.validation, "passed": False, "summary": "Exam syllabus changed",
                                "checks": [{"id": "scope-changed", "label": "Exam syllabus unchanged", "status": "failed",
                                            "detail": "The exam syllabus changed after this worksheet was generated. Regenerate it.",
                                            "refs": []}] + [ch for ch in w.validation.get("checks", []) if ch["id"] != "scope-changed"]}
                stale += 1
    audit(db, "syllabus", f"{c.name} · exam syllabus {p['file']} confirmed · {len(new)} subjects"
          + (f" · {len(changed)} changed, {stale} unreleased worksheets need regenerating" if old else ""),
          actor=admin.email, class_id=c.id, subjects=sorted(e["subject"] for e in new.values()))
    db.commit()
    return syllabus_state(c)


@router.get("/classes/{class_id}/syllabus/file")
def syllabus_file(class_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    c = get_class_for(db, user, class_id)
    if not c.syllabus_path:
        raise HTTPException(404, "No syllabus uploaded.")
    return FileResponse(c.syllabus_path, filename=c.syllabus_file)


class ExamPatch(BaseModel):
    subject_name: str | None = None
    sections: str | None = None
    exam_date: date | None = None
    exam_time: str | None = None


@router.patch("/exams/{exam_id}")
def patch_exam(exam_id: int, body: ExamPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    e = db.get(Exam, exam_id)
    if e is None or not e.active:
        raise HTTPException(404, "Exam not found.")
    c = get_class_for(db, admin, e.class_id)
    changes = body.model_dump(exclude_none=True)
    if "sections" in changes:
        secs = [s.strip().upper() for s in changes["sections"].split(",") if s.strip()]
        bad = [s for s in secs if s not in c.section_list()]
        if bad:
            raise HTTPException(400, f"Section {', '.join(bad)} is not a section of {c.name}.")
        changes["sections"] = ", ".join(secs)
    e.active = False
    c.exams.append(Exam(exam_code=e.exam_code, subject_name=changes.get("subject_name", e.subject_name),
                        sections=changes.get("sections", e.sections), exam_date=changes.get("exam_date", e.exam_date),
                        exam_time=changes.get("exam_time", e.exam_time)))
    db.flush()
    cancel_obsolete(db, c.id, admin.email)
    audit(db, "datesheet", f"{c.name} · edited {e.exam_code}: " + ", ".join(f"{k} → {v}" for k, v in changes.items()),
          actor=admin.email, class_id=c.id)
    db.commit()
    return datesheet_state(db, c)


@router.delete("/exams/{exam_id}")
def delete_exam(exam_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    e = db.get(Exam, exam_id)
    if e is None or not e.active:
        raise HTTPException(404, "Exam not found.")
    c = get_class_for(db, admin, e.class_id)
    e.active = False
    db.flush()
    cancel_obsolete(db, c.id, admin.email)
    audit(db, "datesheet", f"{c.name} · removed {e.exam_code} ({e.subject_name}, {fmt_date(e.exam_date)})",
          actor=admin.email, class_id=c.id)
    db.commit()
    return datesheet_state(db, c)


@router.post("/exams/{exam_id}/generate")
def generate_now(exam_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    e = db.get(Exam, exam_id)
    if e is None or not e.active:
        raise HTTPException(404, "Exam not found.")
    get_class_for(db, admin, e.class_id)
    if e.exam_date < local_today(db):
        raise HTTPException(409, "This exam has already taken place.")
    job = manual_generate(db, e, admin.email)
    if job is None:
        raise HTTPException(409, "A worksheet for this exam has already been generated. Use Regenerate in Worksheet review.")
    db.commit()
    worker.poke()
    return {"job_id": job.id}


# -------------------------------------------------------------------------------------- subjects
class SubjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def doc_out(d: Document) -> dict:
    return {"id": d.id, "filename": d.filename, "kind": d.kind, "chapter": d.chapter, "version": d.version,
            "active": d.active, "pages": d.pages, "chars": d.chars, "extraction": d.extraction,
            "uploaded_at": fmt_date(d.uploaded_at.date()), "uploaded_by": d.uploaded_by}


def subject_out(s: Subject, include_inactive: bool = True) -> dict:
    docs = sorted(s.documents, key=lambda d: (d.kind != "syllabus", d.chapter or "", d.filename, -d.version))
    active = [d for d in docs if d.active]
    return {"id": s.id, "name": s.name, "documents": [doc_out(d) for d in docs if include_inactive or d.active],
            "active_files": len(active), "has_syllabus": any(d.kind == "syllabus" for d in active),
            "readable": any(d.extraction == "ok" for d in active), "settings_override": s.worksheet_settings}


@router.get("/classes/{class_id}/subjects")
def list_subjects(class_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    c = get_class_for(db, user, class_id)
    exam_subjects = sorted({e.subject_name for e in c.exams if e.active})
    have = {s.name.lower() for s in c.subjects}
    return {"subjects": [subject_out(s) for s in sorted(c.subjects, key=lambda s: s.name)],
            "missing_from_datesheet": [n for n in exam_subjects if n.lower() not in have]}


@router.post("/classes/{class_id}/subjects")
def create_subject(class_id: int, body: SubjectIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = get_class_for(db, admin, class_id)
    if any(s.name.lower() == body.name.strip().lower() for s in c.subjects):
        raise HTTPException(409, f"{c.name} already has {body.name}.")
    s = Subject(class_id=c.id, name=body.name.strip())
    db.add(s)
    audit(db, "subject", f"{c.name} · added subject {s.name}", actor=admin.email, class_id=c.id)
    db.commit()
    return subject_out(s)


@router.delete("/subjects/{subject_id}")
def delete_subject(subject_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Subject, subject_id)
    if s is None:
        raise HTTPException(404, "Subject not found.")
    c = get_class_for(db, admin, s.class_id)
    audit(db, "subject", f"{c.name} · removed subject {s.name}", actor=admin.email, class_id=c.id, level="warning")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.post("/subjects/{subject_id}/documents")
async def upload_documents(subject_id: int, files: list[UploadFile] = File(...), kind: str | None = Form(None),
                           chapter: str | None = Form(None), admin: User = Depends(require_admin),
                           db: Session = Depends(get_db)):
    s = db.get(Subject, subject_id)
    if s is None:
        raise HTTPException(404, "Subject not found.")
    c = get_class_for(db, admin, s.class_id)
    if kind not in (None, "", "syllabus", "chapter"):
        raise HTTPException(400, "Kind must be syllabus or chapter.")
    results = []
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            raise HTTPException(400, f"{f.filename} is not a PDF.")
        data = await _read(f)
        d = ingest_pdf(db, s, f.filename, data, kind=kind or None, chapter=chapter or None, uploaded_by=admin.email)
        results.append(d)
        audit(db, "upload", f"{c.name} · {s.name} · {d.filename} v{d.version} uploaded"
              + ("" if d.extraction == "ok" else " · no readable text"), actor=admin.email, class_id=c.id,
              level="info" if d.extraction == "ok" else "error", file=d.filename, version=d.version)
    db.commit()
    db.refresh(s)
    return subject_out(s)


class DocPatch(BaseModel):
    active: bool | None = None
    kind: str | None = Field(default=None, pattern="^(syllabus|chapter)$")
    chapter: str | None = None


@router.patch("/documents/{doc_id}")
def patch_document(doc_id: int, body: DocPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if d is None:
        raise HTTPException(404, "Document not found.")
    c = get_class_for(db, admin, d.subject.class_id)
    changes = body.model_dump(exclude_none=True)
    if changes.get("active"):
        for other in d.subject.documents:
            if other.filename == d.filename and other.id != d.id:
                other.active = False  # one active version per file name
    for k, v in changes.items():
        setattr(d, k, v)
    audit(db, "upload", f"{c.name} · {d.subject.name} · {d.filename} v{d.version} · "
          + ", ".join(f"{k} → {v}" for k, v in changes.items()), actor=admin.email, class_id=c.id)
    db.commit()
    return subject_out(d.subject)


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if d is None:
        raise HTTPException(404, "Document not found.")
    get_class_for(db, user, d.subject.class_id)
    return FileResponse(d.stored_path, media_type="application/pdf", filename=d.filename)


# -------------------------------------------------------------------------------------- students
def student_out(s: Student) -> dict:
    return {"id": s.id, "student_code": s.student_code, "name": s.name, "section": s.section,
            "email": mask_email(s.email), "email_valid": valid_email(s.email),
            "whatsapp": mask_phone(s.whatsapp), "has_whatsapp": bool(s.whatsapp), "active": s.active}


@router.get("/classes/{class_id}/students")
def list_students(class_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    c = get_class_for(db, user, class_id)
    rows = sorted(c.students, key=lambda s: (s.section, s.student_code))
    return {"students": [student_out(s) for s in rows],
            "summary": {"total": sum(1 for s in rows if s.active),
                        "by_section": {sec: sum(1 for s in rows if s.active and s.section == sec) for sec in c.section_list()},
                        "invalid_email": sum(1 for s in rows if s.active and not valid_email(s.email)),
                        "missing_whatsapp": sum(1 for s in rows if s.active and not s.whatsapp)}}


@router.post("/classes/{class_id}/students/upload")
async def upload_students(class_id: int, file: UploadFile = File(...), replace: bool = Form(False),
                          dry_run: bool = Form(False), admin: User = Depends(require_admin),
                          db: Session = Depends(get_db)):
    """Bulk upload for one class. dry_run=true returns the preview without saving anything."""
    from ..services.student_import import apply_plan, plan_class, summarize
    c = get_class_for(db, admin, class_id)
    data = await _read(file)
    try:
        rows, issues = parse_students(file.filename or "students.xlsx", data, c.grade, c.section_list(),
                                      get_settings().whatsapp_default_country_code)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(400, "The file could not be read. Upload an .xlsx or .csv student list.")
    plan = plan_class(c, rows, replace)
    result = summarize(plan, issues)
    if dry_run:
        return {"preview": True, "import": result}
    apply_plan(db, c, plan)
    audit(db, "upload", f"{c.name} · student list {file.filename} · {result['new']} added, {result['updated']} updated"
          + (f", {result['deactivated']} deactivated" if result["deactivated"] else "") + f", {len(issues)} issues",
          actor=admin.email, class_id=c.id, file=file.filename)
    db.commit()
    db.refresh(c)
    return {**list_students(class_id, admin, db), "import": {**result, "added": result["new"]}}


@router.post("/students/upload")
async def upload_students_school(file: UploadFile = File(...), replace: bool = Form(False), dry_run: bool = Form(False),
                                 admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """One file for the whole school. Each row goes to its class by the Class column."""
    from ..services.student_import import apply_plan, build_school_plan, summarize
    data = await _read(file)
    classes = list(db.scalars(select(SchoolClass)))
    if not classes:
        raise HTTPException(409, "Create the classes first. Each row is matched to a class by its Class column.")
    try:
        per_class, all_rows, issues = build_school_plan(file.filename or "students.xlsx", data, classes, replace,
                                                        get_settings().whatsapp_default_country_code)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(400, "The file could not be read. Upload an .xlsx or .csv student list.")
    result = summarize(all_rows, issues)
    by_class = {c.id: c for c in classes}
    result["classes"] = [{"id": cid, "name": by_class[cid].name,
                          **{k: sum(1 for p in plan if p["change"] == k) for k in ("new", "updated", "unchanged", "deactivated")}}
                         for cid, plan in sorted(per_class.items(), key=lambda x: by_class[x[0]].name)]
    if dry_run:
        return {"preview": True, "import": result}
    for cid, plan in per_class.items():
        apply_plan(db, by_class[cid], plan)
        n = {k: sum(1 for p in plan if p["change"] == k) for k in ("new", "updated", "deactivated")}
        audit(db, "upload", f"{by_class[cid].name} · school-wide student list {file.filename} · {n['new']} added, "
              f"{n['updated']} updated" + (f", {n['deactivated']} deactivated" if n["deactivated"] else ""),
              actor=admin.email, class_id=cid, file=file.filename)
    db.commit()
    return {"preview": False, "import": result}


@router.get("/students/template.xlsx")
def student_template(class_id: int | None = None, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    from fastapi.responses import Response
    from ..services.student_import import template_xlsx
    c = get_class_for(db, user, class_id) if class_id else None
    name = f"Students_{c.name.replace(' ', '_')}.xlsx" if c else "Students_all_classes.xlsx"
    return Response(template_xlsx(c), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


class StudentIn(BaseModel):
    student_code: str | None = None
    name: str | None = None
    section: str | None = None
    email: str | None = None
    whatsapp: str | None = None
    active: bool | None = None


@router.post("/classes/{class_id}/students")
def add_student(class_id: int, body: StudentIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = get_class_for(db, admin, class_id)
    if not (body.student_code and body.name and body.section):
        raise HTTPException(400, "Student ID, name and section are required.")
    if any(s.student_code == body.student_code for s in c.students):
        raise HTTPException(409, f"{body.student_code} already exists in {c.name}.")
    s = Student(class_id=c.id, student_code=body.student_code.strip(), name=body.name.strip(), active=True,
                section=body.section.strip().upper(), email=None, whatsapp=None)
    _apply_contacts(s, body, c)
    db.add(s)
    audit(db, "student", f"{c.name} · added {s.student_code}", actor=admin.email, class_id=c.id)
    db.commit()
    return student_out(s)


def _apply_contacts(s: Student, body: StudentIn, c: SchoolClass) -> None:
    if body.section is not None and body.section.strip().upper() not in c.section_list():
        raise HTTPException(400, f"Section {body.section} is not a section of {c.name}.")
    if body.email is not None:
        s.email = body.email.strip() or None
        if s.email and not valid_email(s.email):
            raise HTTPException(400, "That email address is not valid.")
    if body.whatsapp is not None:
        if body.whatsapp.strip():
            n = normalize_whatsapp(body.whatsapp, get_settings().whatsapp_default_country_code)
            if not n:
                raise HTTPException(400, "That WhatsApp number is not valid.")
            s.whatsapp = n
        else:
            s.whatsapp = None


@router.patch("/students/{student_id}")
def patch_student(student_id: int, body: StudentIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Student, student_id)
    if s is None:
        raise HTTPException(404, "Student not found.")
    c = get_class_for(db, admin, s.class_id)
    _apply_contacts(s, body, c)
    if body.name:
        s.name = body.name.strip()
    if body.section:
        s.section = body.section.strip().upper()
    if body.active is not None:
        s.active = body.active
    audit(db, "student", f"{c.name} · updated {s.student_code}", actor=admin.email, class_id=c.id)
    db.commit()
    return student_out(s)


# ---------------------------------------------------------------------------- worksheet settings
def check_worksheet_settings(v: dict, full: bool = False) -> dict:
    """Validate a settings layer. Partial layers (class/subject overrides) may omit keys."""
    out = {}
    if "counts" in v:
        counts = v["counts"]
        if not isinstance(counts, dict) or any(k not in SECTION_LABELS for k in counts):
            raise HTTPException(400, "Unknown question type in counts.")
        if any(not isinstance(n, int) or n < 0 or n > 30 for n in counts.values()):
            raise HTTPException(400, "Each question count must be a whole number from 0 to 30.")
        out["counts"] = counts
    if "difficulty" in v:
        d = v["difficulty"]
        if set(d) != {"easy", "medium", "hard"} or sum(d.values()) != 100 or any(x < 0 for x in d.values()):
            raise HTTPException(400, "The difficulty mix must cover easy, medium and hard and add up to 100%.")
        out["difficulty"] = d
    if "answer_key" in v:
        out["answer_key"] = bool(v["answer_key"])
    if "language" in v:
        from ..services.common import LANGUAGES
        lang = str(v["language"]).strip().capitalize() or "English"
        if lang not in LANGUAGES:
            raise HTTPException(400, "Language must be English or Hindi.")
        out["language"] = lang
    if full:
        merged = merge_worksheet_settings(out)
        if sum(merged["counts"].values()) == 0:
            raise HTTPException(400, "A worksheet needs at least one question.")
        return merged
    return out


class SettingsLayer(BaseModel):
    settings: dict | None  # None clears the override


@router.get("/classes/{class_id}/worksheet-settings")
def get_ws_settings(class_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    c = get_class_for(db, user, class_id)
    glob = get_setting(db, "worksheet_defaults")
    return {"global": merge_worksheet_settings(glob), "class_override": c.worksheet_settings,
            "effective": merge_worksheet_settings(glob, c.worksheet_settings),
            "subjects": [{"id": s.id, "name": s.name, "override": s.worksheet_settings, "language_locked": is_hindi_subject(s.name),
                          "effective": {**(eff := merge_worksheet_settings(glob, c.worksheet_settings, s.worksheet_settings)),
                                        "language": worksheet_language(eff, s.name)}}
                         for s in sorted(c.subjects, key=lambda s: s.name)],
            "labels": SECTION_LABELS, "languages": LANGUAGES}


@router.put("/classes/{class_id}/worksheet-settings")
def put_ws_settings(class_id: int, body: SettingsLayer, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = get_class_for(db, admin, class_id)
    c.worksheet_settings = check_worksheet_settings(body.settings) if body.settings else None
    if c.worksheet_settings is not None:
        check_worksheet_settings(merge_worksheet_settings(get_setting(db, "worksheet_defaults"), c.worksheet_settings), full=True)
    audit(db, "settings", f"{c.name} · worksheet settings " + ("updated" if body.settings else "reset to defaults"),
          actor=admin.email, class_id=c.id, override=c.worksheet_settings)
    db.commit()
    return get_ws_settings(class_id, admin, db)


@router.put("/subjects/{subject_id}/worksheet-settings")
def put_subject_settings(subject_id: int, body: SettingsLayer, admin: User = Depends(require_admin),
                         db: Session = Depends(get_db)):
    s = db.get(Subject, subject_id)
    if s is None:
        raise HTTPException(404, "Subject not found.")
    c = get_class_for(db, admin, s.class_id)
    s.worksheet_settings = check_worksheet_settings(body.settings) if body.settings else None
    audit(db, "settings", f"{c.name} · {s.name} worksheet settings " + ("updated" if body.settings else "reset"),
          actor=admin.email, class_id=c.id, override=s.worksheet_settings)
    db.commit()
    return get_ws_settings(c.id, admin, db)
