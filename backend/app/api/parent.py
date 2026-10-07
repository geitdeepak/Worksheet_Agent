"""Parents: make practice sheets for their own children. A parent only ever sees the children an administrator
linked to their account, and the sheets made for those children."""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agents.creation_agent import find_subject, has_material, subject_chapters
from ..db import get_db
from ..models import Job, ParentSheet, SchoolClass, Student, User
from ..security import require_parent
from ..services.common import audit, fmt_date, get_setting, institution_tz, local_today
from ..worker import worker

router = APIRouter(prefix="/api/parent")


def _children(db: Session, user: User) -> list[Student]:
    ids = user.student_ids or []
    rows = {s.id: s for s in db.scalars(select(Student).where(Student.id.in_(ids), Student.active.is_(True)))} if ids else {}
    return [rows[i] for i in ids if i in rows]


def _day_start(db: Session) -> datetime:
    tz = institution_tz(db)
    return datetime.combine(local_today(db), datetime.min.time(), tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)


def _used_today(db: Session, student_id: int) -> int:
    """Sheets made for this child today (by any parent). Failed attempts are not counted."""
    return db.scalar(select(func.count(ParentSheet.id)).where(
        ParentSheet.student_id == student_id, ParentSheet.created_at >= _day_start(db),
        ParentSheet.status != "failed")) or 0


def _subjects(db: Session, c: SchoolClass) -> list[dict]:
    """Subjects of the child's class that have readable study material, with the chapters to choose from."""
    return [{"name": s.name, "chapters": subject_chapters(db, s)}
            for s in sorted(c.subjects, key=lambda s: s.name.lower()) if has_material(db, s)]


def sheet_out(db: Session, sh: ParentSheet, names: dict[int, str]) -> dict:
    local = sh.created_at.replace(tzinfo=timezone.utc).astimezone(institution_tz(db))
    return {"id": sh.id, "student_id": sh.student_id, "student": names.get(sh.student_id, "—"),
            "subject": sh.subject_name, "chapters": sh.chapters or [], "status": sh.status, "title": sh.title,
            "error": sh.error, "created": f"{fmt_date(local.date())} {local.strftime('%H:%M')}",
            "questions": sum(len(s.get("questions", [])) for s in (sh.content or {}).get("sections", [])),
            "has_pdf": bool(sh.pdf_path and Path(sh.pdf_path).exists())}


@router.get("/overview")
def overview(user: User = Depends(require_parent), db: Session = Depends(get_db)):
    limit = int(get_setting(db, "parent_daily_limit") or 3)
    kids = _children(db, user)
    classes = {c.id: c for c in db.scalars(select(SchoolClass).where(SchoolClass.id.in_({k.class_id for k in kids})))}
    names = {k.id: k.name for k in kids}
    sheets = list(db.scalars(select(ParentSheet).where(ParentSheet.student_id.in_(list(names)))
                             .order_by(ParentSheet.id.desc()).limit(50))) if names else []
    return {
        "limit": limit,
        "children": [{"id": k.id, "name": k.name, "class": classes[k.class_id].name, "section": k.section,
                      "used_today": _used_today(db, k.id), "subjects": _subjects(db, classes[k.class_id])} for k in kids],
        "sheets": [sheet_out(db, s, names) for s in sheets],
    }


class SheetIn(BaseModel):
    student_id: int
    subject: str
    chapters: list[str] = []


@router.post("/sheets")
def make_sheet(body: SheetIn, user: User = Depends(require_parent), db: Session = Depends(get_db)):
    child = next((k for k in _children(db, user) if k.id == body.student_id), None)
    if child is None:
        raise HTTPException(404, "Child not found.")
    c = db.get(SchoolClass, child.class_id)
    subject = find_subject(db, c.id, body.subject)
    if subject is None or not has_material(db, subject):
        raise HTTPException(400, f"{body.subject} has no study material for {c.name} yet. Ask the school to upload it.")
    available = set(subject_chapters(db, subject))
    chapters = list(dict.fromkeys(body.chapters))
    if any(ch not in available for ch in chapters):
        raise HTTPException(400, "One of the chosen chapters is not available for this subject.")
    limit = int(get_setting(db, "parent_daily_limit") or 3)
    if _used_today(db, child.id) >= limit:
        raise HTTPException(429, f"{child.name} already has {limit} practice sheet{'s' if limit != 1 else ''} today. "
                                 "You can make more tomorrow.")
    if db.scalar(select(ParentSheet.id).where(ParentSheet.student_id == child.id, ParentSheet.status == "generating")):
        raise HTTPException(409, f"A practice sheet for {child.name} is already being made. Please wait for it to finish.")

    sheet = ParentSheet(parent_id=user.id, student_id=child.id, class_id=c.id, subject_name=subject.name,
                        chapters=chapters, sections=child.section, status="generating")
    db.add(sheet)
    db.flush()
    today = local_today(db)
    db.add(Job(type="PARENT_WORKSHEET", business_key=f"PARENT_WORKSHEET|sheet:{sheet.id}", class_id=c.id,
               subject_name=subject.name, sections=child.section, exam_date=today, trigger_date=today, source="parent",
               payload={"parent_sheet_id": sheet.id}))
    audit(db, "parent", f"Parent practice sheet requested · {child.name} · {c.name} · {subject.name}"
                        + (f" · {', '.join(chapters)}" if chapters else ""), actor=user.email, class_id=c.id)
    db.commit()
    worker.poke()
    return sheet_out(db, sheet, {child.id: child.name})


@router.get("/sheets/{sheet_id}/pdf")
def sheet_pdf(sheet_id: int, user: User = Depends(require_parent), db: Session = Depends(get_db)):
    sheet = db.get(ParentSheet, sheet_id)
    if sheet is None or sheet.student_id not in (user.student_ids or []):
        raise HTTPException(404, "Practice sheet not found.")
    if sheet.status != "ready" or not sheet.pdf_path or not Path(sheet.pdf_path).exists():
        raise HTTPException(409, "This practice sheet is not ready.")
    return FileResponse(sheet.pdf_path, media_type="application/pdf", filename=Path(sheet.pdf_path).name)
