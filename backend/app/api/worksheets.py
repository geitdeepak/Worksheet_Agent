"""Worksheet review (preview, edit, approve, regenerate) and the delivery monitor."""
import csv
import io
from datetime import timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents import sharing_agent
from ..agents.creation_agent import revalidate
from ..agents.pdf_render import render_worksheet_pdf
from ..db import get_db
from ..models import Delivery, Job, SchoolClass, Student, User, Worksheet
from ..orchestrator import regenerate, release, share_key
from ..security import can_access_class, current_user, get_class_for
from ..services.common import SECTION_LABELS, audit, fmt_date, fmt_day_month, get_setting, institution_tz, mask_email, mask_phone
from ..worker import worker
from .admin import visible_class_ids

router = APIRouter(prefix="/api")


def _ws(db: Session, user: User, ws_id: int) -> Worksheet:
    ws = db.get(Worksheet, ws_id)
    if ws is None or not can_access_class(user, ws.class_id):
        raise HTTPException(404, "Worksheet not found.")
    return ws


def ws_summary(db: Session, ws: Worksheet, c: SchoolClass) -> dict:
    return {"id": ws.id, "title": ws.title, "subject": ws.subject_name, "class": c.name, "class_id": c.id,
            "grade": c.grade, "sections": ws.sections, "exam_code": ws.exam_code, "exam_date": fmt_date(ws.exam_date),
            "exam_day": fmt_day_month(ws.exam_date), "version": ws.version, "status": ws.status,
            "generator": ws.generator, "created": fmt_date(ws.created_at.date()),
            "questions": sum(len(s.get("questions", [])) for s in ws.content.get("sections", [])),
            "validation": ws.validation.get("summary"), "release_mode": c.release_mode}


@router.get("/worksheets")
def list_worksheets(status: str | None = None, class_id: int | None = None, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    ids = visible_class_ids(db, user)
    q = select(Worksheet).where(Worksheet.class_id.in_(ids))
    if status:
        q = q.where(Worksheet.status.in_(status.split(",")))
    if class_id:
        q = q.where(Worksheet.class_id == class_id)
    classes = {c.id: c for c in db.scalars(select(SchoolClass))}
    return [ws_summary(db, w, classes[w.class_id]) for w in db.scalars(q.order_by(Worksheet.exam_date.desc(), Worksheet.id.desc()))]


@router.get("/worksheets/{ws_id}")
def get_worksheet(ws_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ws = _ws(db, user, ws_id)
    c = db.get(SchoolClass, ws.class_id)
    recipients = sharing_agent.eligible_students(db, ws)
    channels = sharing_agent.enabled_channels(db, c)
    content = {k: v for k, v in ws.content.items() if not k.startswith("_")}
    versions = [{"id": w.id, "version": w.version, "status": w.status}
                for w in db.scalars(select(Worksheet).where(Worksheet.exam_id == ws.exam_id).order_by(Worksheet.version))]
    return {**ws_summary(db, ws, c), "content": content, "validation": ws.validation, "sources": ws.sources,
            "passages": ws.content.get("_passages", {}), "scope": ws.content.get("_scope"),
            "settings": ws.settings_used, "labels": SECTION_LABELS, "recipients": len(recipients),
            "channels": channels, "approved_by": ws.approved_by, "regeneration_reason": ws.regeneration_reason,
            "versions": versions, "has_pdf": bool(ws.pdf_path and Path(ws.pdf_path).exists())}


@router.get("/worksheets/{ws_id}/pdf")
def worksheet_pdf(ws_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ws = _ws(db, user, ws_id)
    if not ws.pdf_path or not Path(ws.pdf_path).exists():
        raise HTTPException(404, "The PDF has not been generated.")
    return FileResponse(ws.pdf_path, media_type="application/pdf", filename=Path(ws.pdf_path).name,
                        content_disposition_type="inline")


class ContentIn(BaseModel):
    content: dict


@router.put("/worksheets/{ws_id}/content")
def edit_worksheet(ws_id: int, body: ContentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Teachers and admins can edit everything during review: wording, answers, options, difficulty, and add,
    delete, reorder or move questions between sections. Validation re-runs on every save."""
    from ..agents.mathtext import normalize_content
    ws = _ws(db, user, ws_id)
    if ws.status not in ("awaiting-approval", "validation-failed"):
        raise HTTPException(409, "Only worksheets under review can be edited.")
    private = {k: v for k, v in ws.content.items() if k.startswith("_")}
    incoming = {k: v for k, v in body.content.items() if not k.startswith("_")}
    sections = []
    for sec in incoming.get("sections", []):
        if sec.get("type") not in SECTION_LABELS:
            raise HTTPException(400, "Unknown section type.")
        qs = []
        for q in sec.get("questions", []):
            if not str(q.get("text", "")).strip():
                continue  # blank questions added and never filled in are dropped
            q.setdefault("options", [])
            q.setdefault("source_ids", [])
            q.setdefault("outside_syllabus", False)
            q.setdefault("review_note", "")
            q.setdefault("difficulty", "medium")
            q.setdefault("topic", "")
            if sec["type"] != "mcq":
                q["options"] = []
            if not q["source_ids"]:
                q["origin"] = "teacher"  # written by a teacher: trusted, no textbook citation required
            if q.get("origin") == "teacher" or q.get("edited"):
                q["edited_by"] = user.email
            qs.append(q)
        if qs:
            sections.append({**sec, "questions": qs})
    if not sections:
        raise HTTPException(400, "A worksheet needs at least one question.")
    incoming["sections"] = sections
    incoming = normalize_content(incoming)  # typed maths like x^2 or \frac{1}{2} → x², 1/2
    # Reassign (not mutate) so the JSON column is marked dirty. _manual relaxes the question-count check:
    # a teacher may deliberately add or remove questions.
    ws.content = {**incoming, **private, "_manual": True}
    ws.title = incoming.get("title") or ws.title
    result = revalidate(db, ws)
    ws.status = "awaiting-approval" if result["passed"] else "validation-failed"
    c = db.get(SchoolClass, ws.class_id)
    ws.pdf_path = str(render_worksheet_pdf(ws, c))
    job = db.get(Job, ws.create_job_id) if ws.create_job_id else None
    if job and job.status in ("awaiting-approval", "validation-failed"):
        job.status = ws.status
    audit(db, "edit", f"Edited {ws.title} · v{ws.version} · validation {result['summary'].lower()}", actor=user.email,
          class_id=ws.class_id, worksheet_id=ws.id)
    db.commit()
    return get_worksheet(ws_id, user, db)


class ApproveIn(BaseModel):
    override: bool = False
    note: str | None = None


@router.post("/worksheets/{ws_id}/approve")
def approve(ws_id: int, body: ApproveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ws = _ws(db, user, ws_id)
    if ws.status == "validation-failed":
        if not body.override:
            raise HTTPException(409, "This worksheet failed validation. Edit or regenerate it, or approve with override.")
        if user.role != "admin":
            raise HTTPException(403, "Only administrators can release a worksheet that failed validation.")
        audit(db, "approval", f"Released despite failed validation · {ws.title} · {body.note or 'no note'}",
              actor=user.email, class_id=ws.class_id, level="warning", worksheet_id=ws.id)
    elif ws.status != "awaiting-approval":
        raise HTTPException(409, f"This worksheet is {ws.status.replace('-', ' ')} and can't be approved.")
    release(db, ws, user.email, approved=True)
    db.commit()
    worker.poke()
    return get_worksheet(ws_id, user, db)


class RegenerateIn(BaseModel):
    reason: str = "Regenerated from review"


@router.post("/worksheets/{ws_id}/regenerate")
def regen(ws_id: int, body: RegenerateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ws = _ws(db, user, ws_id)
    if ws.status == "released":
        raise HTTPException(409, "This worksheet has already been released to students.")
    try:
        job = regenerate(db, ws, body.reason, user.email)
    except ValueError as e:
        raise HTTPException(409, str(e))
    db.commit()
    worker.poke()
    return {"job_id": job.id}


# ------------------------------------------------------------------------------------ deliveries
def _deliveries(db: Session, ws: Worksheet) -> list[dict]:
    students = {s.id: s for s in db.scalars(select(Student).where(Student.class_id == ws.class_id))}
    rows: dict[int, dict] = {}
    tz = institution_tz(db)
    for d in db.scalars(select(Delivery).where(Delivery.worksheet_id == ws.id)):
        s = students.get(d.student_id)
        if s is None:
            continue
        r = rows.setdefault(s.id, {"id": s.id, "student_code": s.student_code, "name": s.name, "section": s.section,
                                   "email": mask_email(s.email), "whatsapp": mask_phone(s.whatsapp),
                                   "email_status": None, "whatsapp_status": None})
        r[f"{d.channel}_status"] = d.status
        r[f"{d.channel}_error"] = d.error
        r[f"{d.channel}_attempts"] = d.attempts
        r[f"{d.channel}_at"] = d.updated_at.replace(tzinfo=timezone.utc).astimezone(tz).strftime("%H:%M")
    return sorted(rows.values(), key=lambda r: (r["section"], r["student_code"]))


@router.get("/deliveries")
def delivery_overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Released worksheets with per-channel counts, newest first."""
    ids = visible_class_ids(db, user)
    classes = {c.id: c for c in db.scalars(select(SchoolClass))}
    out = []
    for ws in db.scalars(select(Worksheet).where(Worksheet.class_id.in_(ids), Worksheet.status == "released")
                         .order_by(Worksheet.released_at.desc())):
        out.append({**ws_summary(db, ws, classes[ws.class_id]), "summary": sharing_agent.summarize(db, ws.id)})
    return out


@router.get("/worksheets/{ws_id}/deliveries")
def worksheet_deliveries(ws_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ws = _ws(db, user, ws_id)
    c = db.get(SchoolClass, ws.class_id)
    job = db.scalar(select(Job).where(Job.business_key == share_key(ws)))
    tz = institution_tz(db)
    return {**ws_summary(db, ws, c), "summary": sharing_agent.summarize(db, ws.id), "rows": _deliveries(db, ws),
            "released_at": ws.released_at.replace(tzinfo=timezone.utc).astimezone(tz).strftime("%H:%M")
            if ws.released_at else None,
            "share_job": {"status": job.status, "error": job.last_error} if job else None,
            "phase": int(get_setting(db, "phase") or 1), "channels": sharing_agent.enabled_channels(db, c),
            "channel_whatsapp": c.channel_whatsapp}


@router.post("/worksheets/{ws_id}/retry-failed")
def retry_failed(ws_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Re-send failed deliveries (after contacts were fixed) and pick up newly enabled channels/students."""
    ws = _ws(db, user, ws_id)
    get_class_for(db, user, ws.class_id)
    if ws.status != "released":
        raise HTTPException(409, "Only released worksheets can be re-sent.")
    n = 0
    students = {s.id: s for s in db.scalars(select(Student).where(Student.class_id == ws.class_id))}
    for d in db.scalars(select(Delivery).where(Delivery.worksheet_id == ws.id, Delivery.status.in_(["failed", "skipped"]))):
        s = students.get(d.student_id)
        if s is None or not s.active:
            continue
        db.delete(d)  # prepare_deliveries rebuilds it from the student's current contact details
        n += 1
    db.flush()
    audit(db, "retry", f"Re-sending {n} failed deliveries · {ws.title}", actor=user.email, class_id=ws.class_id)
    summary = sharing_agent.share_worksheet(db, ws)
    db.commit()
    return {"retried": n, "summary": summary}


@router.get("/worksheets/{ws_id}/deliveries.csv")
def export_csv(ws_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ws = _ws(db, user, ws_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Student ID", "Name", "Section", "Email", "Email status", "Email error", "WhatsApp",
                "WhatsApp status", "WhatsApp error"])
    for r in _deliveries(db, ws):
        w.writerow([r["student_code"], r["name"], r["section"], r["email"], r["email_status"] or "",
                    r.get("email_error") or "", r["whatsapp"], r["whatsapp_status"] or "", r.get("whatsapp_error") or ""])
    buf.seek(0)
    name = f"deliveries_{ws.subject_name}_{ws.exam_date.isoformat()}.csv".replace(" ", "_")
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
