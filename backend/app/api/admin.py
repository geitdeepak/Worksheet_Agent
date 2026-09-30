"""Auth, users, institution settings, dashboard, history (audit), scheduler control, webhooks."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AuditEvent, Delivery, Exam, Job, SchoolClass, User, Worksheet
from ..orchestrator import daily_check, readiness_problems
from ..security import create_token, current_user, hash_password, require_admin, verify_password
from ..services.common import (all_settings, audit, fmt_date, fmt_day_month, institution_tz, local_today,
                               set_setting)
from ..worker import worker

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------------------------------ auth
class LoginIn(BaseModel):
    email: str
    password: str


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "class_access": u.class_access or [],
            "active": u.active}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if u is None or not u.active or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "The email or password is not correct.")
    audit(db, "login", f"{u.email} signed in", actor=u.email)
    db.commit()
    return {"token": create_token(u), "user": user_out(u)}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=8)


@router.post("/auth/password")
def change_password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current, user.password_hash):
        raise HTTPException(400, "The current password is not correct.")
    user.password_hash = hash_password(body.new)
    audit(db, "user", f"{user.email} changed their password", actor=user.email)
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------------------- users
class UserIn(BaseModel):
    email: str
    name: str
    role: str = "teacher"
    password: str | None = None
    class_access: list[int] = []
    active: bool = True


@router.get("/users")
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.name))]


@router.post("/users")
def create_user(body: UserIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.role not in ("admin", "teacher"):
        raise HTTPException(400, "Role must be admin or teacher.")
    if not body.password or len(body.password) < 8:
        raise HTTPException(400, "Set a password of at least 8 characters.")
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "A user with this email already exists.")
    u = User(email=body.email.strip(), name=body.name.strip(), role=body.role, class_access=body.class_access,
             password_hash=hash_password(body.password))
    db.add(u)
    audit(db, "user", f"Added {body.role} {u.email}", actor=admin.email)
    db.commit()
    return user_out(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found.")
    u.name, u.role, u.class_access, u.active = body.name, body.role, body.class_access, body.active
    if body.password:
        u.password_hash = hash_password(body.password)
    audit(db, "user", f"Updated {u.email}", actor=admin.email)
    db.commit()
    return user_out(u)


# -------------------------------------------------------------------------------------- settings
class SettingsIn(BaseModel):
    institution_name: str | None = None
    timezone: str | None = None
    scheduler_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    lead_days: int | None = Field(default=None, ge=1, le=14)
    phase: int | None = Field(default=None, ge=1, le=2)
    worksheet_defaults: dict | None = None
    reuse_worksheets: bool | None = None
    use_batch: bool | None = None


def settings_out(db: Session) -> dict:
    s = all_settings(db)
    cfg = get_settings()
    model = {"anthropic": cfg.llm_model, "gemini": cfg.gemini_model}.get(cfg.llm_provider)
    s["providers"] = {"llm": cfg.llm_provider, "llm_model": model,
                      "llm_effort": cfg.llm_effort, "llm_context_chars": cfg.llm_context_chars,
                      "email": cfg.email_provider, "whatsapp": cfg.whatsapp_provider}
    return s


@router.get("/settings")
def get_app_settings(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return settings_out(db)


@router.put("/settings")
def put_app_settings(body: SettingsIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    changes = body.model_dump(exclude_none=True)
    if "timezone" in changes:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(changes["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(400, "Unknown timezone. Use an IANA name such as Asia/Kolkata.")
    if "worksheet_defaults" in changes:
        from .classes import check_worksheet_settings
        changes["worksheet_defaults"] = check_worksheet_settings(changes["worksheet_defaults"], full=True)
    for k, v in changes.items():
        set_setting(db, k, v)
    audit(db, "settings", "Updated institution settings: " + ", ".join(changes), actor=admin.email, **changes)
    db.commit()
    return settings_out(db)


# ------------------------------------------------------------------------------------- dashboard
def _time_label(db: Session, dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.replace(tzinfo=timezone.utc).astimezone(institution_tz(db)).strftime("%H:%M")


def visible_class_ids(db: Session, user: User) -> list[int]:
    ids = list(db.scalars(select(SchoolClass.id)))
    return ids if user.role == "admin" else [i for i in ids if i in (user.class_access or [])]


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = visible_class_ids(db, user)
    today = local_today(db)
    tz = institution_tz(db)
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    classes = list(db.scalars(select(SchoolClass).where(SchoolClass.id.in_(ids))))
    names = {c.id: c for c in classes}
    lead = int(all_settings(db)["lead_days"] or 2)
    upcoming = list(db.scalars(select(Exam).where(Exam.class_id.in_(ids), Exam.active.is_(True), Exam.exam_date >= today,
                                                  Exam.exam_date <= today + timedelta(days=14)).order_by(Exam.exam_date)))
    awaiting = list(db.scalars(select(Worksheet).where(Worksheet.class_id.in_(ids), Worksheet.status.in_(
        ["awaiting-approval", "validation-failed"])).order_by(Worksheet.exam_date)))
    generated_today = list(db.scalars(select(Worksheet).where(Worksheet.class_id.in_(ids), Worksheet.created_at >= day_start)))
    deliveries_today = db.execute(select(Delivery.channel, Delivery.status, func.count()).join(
        Worksheet, Delivery.worksheet_id == Worksheet.id).where(Worksheet.class_id.in_(ids), Delivery.updated_at >= day_start)
        .group_by(Delivery.channel, Delivery.status)).all()
    dcount = {(ch, st): n for ch, st, n in deliveries_today}
    email_sent = dcount.get(("email", "sent"), 0) + dcount.get(("email", "delivered"), 0)
    email_failed = dcount.get(("email", "failed"), 0)
    wa_sent = dcount.get(("whatsapp", "sent"), 0) + dcount.get(("whatsapp", "delivered"), 0)
    phase = int(all_settings(db)["phase"] or 1)
    scheduled = [e for e in upcoming if e.exam_date - timedelta(days=lead) >= today and names[e.class_id].automation == "active"]
    exceptions = list(db.scalars(select(AuditEvent).where(AuditEvent.level == "error", AuditEvent.ts >= day_start,
                                                          (AuditEvent.class_id.in_(ids)) | (AuditEvent.class_id.is_(None)))
                                 .order_by(AuditEvent.ts.desc()).limit(20)))
    jobs = list(db.scalars(select(Job).where(Job.class_id.in_(ids), Job.updated_at >= day_start).order_by(Job.created_at.desc())))

    def cls_label(class_id, sections):
        c = names.get(class_id)
        return (c.name + (f"-{sections}" if sections else "")) if c else "—"

    todo = build_todo(db, classes, awaiting, jobs, names, day_start)

    return {
        "todo": todo,
        "today": fmt_date(today), "weekday": today.strftime("%A"),
        "last_run": all_settings(db)["last_scheduler_run"], "scheduler_time": all_settings(db)["scheduler_time"],
        "timezone": all_settings(db)["timezone"], "phase": phase,
        "kpis": {
            "active_classes": sum(1 for c in classes if c.automation == "active"), "configured_classes": len(classes),
            "upcoming_exams": len(upcoming), "worksheets_scheduled": len(scheduled),
            "generated_today": len(generated_today),
            "generated_subjects": sorted({w.subject_name for w in generated_today}),
            "awaiting_approval": sum(1 for w in awaiting if w.status == "awaiting-approval"),
            "validation_failed": sum(1 for w in awaiting if w.status == "validation-failed"),
            "email_sent": email_sent, "email_failed": email_failed,
            "whatsapp_sent": wa_sent if phase >= 2 else None, "content_exceptions": len(exceptions),
        },
        "awaiting": [{"id": w.id, "title": w.title, "subject": w.subject_name, "class": cls_label(w.class_id, w.sections),
                      "exam_date": fmt_day_month(w.exam_date), "status": w.status, "version": w.version} for w in awaiting],
        "jobs": [{"id": j.id, "time": _time_label(db, j.created_at), "type": j.type, "class": cls_label(j.class_id, j.sections),
                  "subject": j.subject_name, "exam": fmt_day_month(j.exam_date), "status": j.status,
                  "worksheet_id": j.worksheet_id, "error": j.last_error, "attempts": j.attempts} for j in jobs],
        "upcoming": [{"id": e.id, "class": names[e.class_id].name, "class_id": e.class_id, "subject": e.subject_name,
                      "exam_date": fmt_day_month(e.exam_date), "trigger": fmt_day_month(e.exam_date - timedelta(days=lead)),
                      "automation": names[e.class_id].automation} for e in upcoming[:8]],
        "exceptions": [{"id": a.id, "summary": a.summary, "class_id": a.class_id, "time": _time_label(db, a.ts)}
                       for a in exceptions],
    }


_STEP_FOR = [("date sheet", "dates", "Upload the exam dates"), ("syllabus", "syllabus", "Upload the exam syllabus"),
             ("subject", "material", "Add the study material (chapter PDFs)"), ("students", "students", "Upload the student list"),
             ("channel", "settings", "Turn on email delivery")]


def build_todo(db: Session, classes, awaiting, jobs, names, day_start) -> list[dict]:
    """Plain-language to-dos, most urgent first. Each has a link to the exact page that fixes it."""
    todo = []
    for w in awaiting:
        c = names[w.class_id]
        label = f"{w.subject_name} · {c.name}" + (f"-{w.sections}" if w.sections else "") + f" · exam {fmt_day_month(w.exam_date)}"
        if w.status == "awaiting-approval":
            todo.append({"tone": "warning", "title": f"Check and approve a worksheet: {label}",
                         "detail": "Students get it as soon as you approve.", "action": "Review", "to": f"/review/{w.id}"})
        else:
            todo.append({"tone": "danger", "title": f"A worksheet needs fixing: {label}",
                         "detail": "Some questions went outside the syllabus or had problems, so it was not sent.",
                         "action": "Fix", "to": f"/review/{w.id}"})
    for j in jobs:
        if j.status == "failed" and j.type == "CREATE_WORKSHEET":
            todo.append({"tone": "danger", "title": f"Could not make the {j.subject_name} worksheet for {names[j.class_id].name}",
                         "detail": j.last_error or "", "action": "See why", "to": "/history?tab=jobs"})
    failed = db.execute(select(Delivery.worksheet_id, func.count()).join(Worksheet, Delivery.worksheet_id == Worksheet.id)
                        .where(Worksheet.class_id.in_([c.id for c in classes]), Delivery.status == "failed",
                               Delivery.updated_at >= day_start).group_by(Delivery.worksheet_id)).all()
    for ws_id, n in failed:
        w = db.get(Worksheet, ws_id)
        todo.append({"tone": "danger", "title": f"{n} student{'s' if n > 1 else ''} did not receive the {w.subject_name} worksheet",
                     "detail": "Usually a wrong email address. Fix it and send again.", "action": "Fix", "to": f"/delivery/{ws_id}"})
    for c in classes:
        if c.automation == "active":
            continue
        problems = readiness_problems(db, c)
        if problems:
            step = next(((tab, text) for key, tab, text in _STEP_FOR if any(key in p.lower() for p in problems)),
                        ("dates", "Finish setting up"))
            todo.append({"tone": "info", "title": f"Finish setting up {c.name}: {step[1].lower()}",
                         "detail": f"{len(problems)} thing{'s' if len(problems) > 1 else ''} left before worksheets can be sent.",
                         "action": "Continue", "to": f"/classes/{c.id}/{step[0]}"})
        else:
            todo.append({"tone": "info", "title": f"{c.name} is ready. Start sending worksheets automatically",
                         "detail": "Everything is set up." if c.automation == "draft" else "Automatic worksheets are paused for this class.",
                         "action": "Open", "to": f"/classes/{c.id}"})
    return todo


@router.post("/scheduler/run")
def run_check_now(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    result = daily_check(db, actor=admin.email)
    worker.poke()
    return result


@router.get("/jobs")
def list_jobs(status: str | None = None, class_id: int | None = None, limit: int = Query(100, le=500),
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = visible_class_ids(db, user)
    q = select(Job).where(Job.class_id.in_(ids))
    if status:
        q = q.where(Job.status == status)
    if class_id:
        q = q.where(Job.class_id == class_id)
    names = {c.id: c.name for c in db.scalars(select(SchoolClass))}
    return [{"id": j.id, "type": j.type, "business_key": j.business_key, "class": names.get(j.class_id), "class_id": j.class_id,
             "subject": j.subject_name, "sections": j.sections, "exam_date": fmt_date(j.exam_date),
             "trigger_date": fmt_date(j.trigger_date), "status": j.status, "attempts": j.attempts, "error": j.last_error,
             "source": j.source, "worksheet_id": j.worksheet_id, "created": _time_label(db, j.created_at),
             "created_date": fmt_date(j.created_at.date())}
            for j in db.scalars(q.order_by(Job.created_at.desc()).limit(limit))]


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404, "Job not found.")
    if j.status != "failed":
        raise HTTPException(409, "Only failed jobs can be retried.")
    j.status, j.attempts, j.next_attempt_at = "pending", 0, None
    audit(db, "retry", f"Manual retry of {j.type} · {j.subject_name}", actor=admin.email, class_id=j.class_id, job_id=j.id)
    db.commit()
    worker.poke()
    return {"ok": True}


# --------------------------------------------------------------------------------------- history
@router.get("/audit")
def audit_log(event: str | None = None, class_id: int | None = None, level: str | None = None,
              q: str | None = None, before_id: int | None = None, limit: int = Query(100, le=500),
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = visible_class_ids(db, user)
    stmt = select(AuditEvent)
    if user.role != "admin":
        stmt = stmt.where(AuditEvent.class_id.in_(ids))
    if event:
        stmt = stmt.where(AuditEvent.event == event)
    if class_id:
        stmt = stmt.where(AuditEvent.class_id == class_id)
    if level:
        stmt = stmt.where(AuditEvent.level == level)
    if q:
        stmt = stmt.where(AuditEvent.summary.ilike(f"%{q}%"))
    if before_id:
        stmt = stmt.where(AuditEvent.id < before_id)
    names = {c.id: c.name for c in db.scalars(select(SchoolClass))}
    tz = institution_tz(db)
    rows = db.scalars(stmt.order_by(AuditEvent.id.desc()).limit(limit))
    return [{"id": a.id, "ts": a.ts.replace(tzinfo=timezone.utc).astimezone(tz).strftime("%d %b %Y %H:%M"),
             "actor": a.actor, "event": a.event, "class": names.get(a.class_id), "summary": a.summary, "level": a.level,
             "details": a.details} for a in rows]


# ---------------------------------------------------------------------------------- WhatsApp hook
@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
def whatsapp_verify(request: Request):
    p = request.query_params
    token = get_settings().whatsapp_webhook_verify_token
    if token and p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == token:
        return p.get("hub.challenge", "")
    raise HTTPException(403, "Verification failed.")


@router.post("/webhooks/whatsapp")
async def whatsapp_status(request: Request, db: Session = Depends(get_db)):
    """Delivery receipts from the WhatsApp Business Platform: sent → delivered, or failed."""
    if not get_settings().whatsapp_webhook_verify_token:
        raise HTTPException(404, "Not enabled.")
    body = await request.json()
    updated = 0
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            for st in change.get("value", {}).get("statuses", []):
                d = db.scalar(select(Delivery).where(Delivery.provider_id == st.get("id"), Delivery.channel == "whatsapp"))
                if d is None:
                    continue
                if st.get("status") in ("delivered", "read"):
                    d.status = "delivered"
                elif st.get("status") == "failed":
                    errs = st.get("errors") or [{}]
                    d.status, d.error = "failed", f"{errs[0].get('code')}: {errs[0].get('title')}"
                updated += 1
    db.commit()
    return {"updated": updated}
