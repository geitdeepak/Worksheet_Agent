"""Scheduler / orchestrator — the deterministic control layer between the two agents.

Every day: load active classes → read each confirmed date sheet → find exams where
exam date − today = lead days → create CREATE_WORKSHEET jobs (idempotent by business key) →
the worker runs the Creation Agent → validation → release (auto or on approval) →
SHARE_WORKSHEET job → the Sharing Agent → dashboard."""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .agents import sharing_agent
from .agents.creation_agent import BlockedError, Pending, create_worksheet, find_subject
from .agents.llm import LLMError
from .config import get_settings
from .models import Document, Exam, Job, SchoolClass, Worksheet, utcnow
from .services.common import audit, fmt_date, get_setting, local_now, local_today, set_setting

log = logging.getLogger("psa.orchestrator")

OPEN_JOB_STATES = ("pending", "running")


def create_key(school_class: SchoolClass, exam: Exam, version: int = 1) -> str:
    """Exam ID + Class + Section + Subject + Exam date + Worksheet version."""
    return "|".join(["CREATE_WORKSHEET", exam.exam_code, school_class.grade, exam.sections or "ALL",
                     exam.subject_name.lower(), exam.exam_date.isoformat(), f"v{version}"])


def share_key(ws: Worksheet) -> str:
    return f"SHARE_WORKSHEET|worksheet:{ws.id}"


def _insert_job(db: Session, job: Job) -> Job | None:
    """Insert unless the business key already exists. Returns None for a duplicate."""
    if db.scalar(select(Job.id).where(Job.business_key == job.business_key)):
        return None
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
        return job
    except IntegrityError:
        return None


def readiness_problems(db: Session, school_class: SchoolClass) -> list[str]:
    problems = []
    if not school_class.datesheet_file:
        problems.append("No date sheet uploaded.")
    elif not school_class.datesheet_confirmed:
        problems.append("The date sheet has not been confirmed.")
    if not school_class.syllabus_file:
        problems.append("No exam syllabus uploaded.")
    elif not school_class.syllabus_confirmed:
        problems.append("The exam syllabus has not been confirmed.")
    if not school_class.students:
        problems.append("No students uploaded.")
    subjects = {s.name.lower() for s in school_class.subjects}
    scope = school_class.syllabus_scope or {}
    for e in school_class.exams:
        if e.active and e.subject_name.lower() not in subjects:
            problems.append(f"No subject set up for {e.subject_name}.")
        if e.active and school_class.syllabus_confirmed and e.subject_name.lower() not in scope:
            problems.append(f"The exam syllabus has nothing for {e.subject_name}.")
    if not school_class.channel_email and not school_class.channel_whatsapp:
        problems.append("No delivery channel is enabled.")
    return sorted(set(problems))


def subject_missing_pdfs(db: Session, class_id: int, subject_name: str) -> bool:
    subj = find_subject(db, class_id, subject_name)
    if subj is None:
        return True
    return db.scalar(select(Document.id).where(Document.subject_id == subj.id, Document.active.is_(True),
                                               Document.extraction == "ok")) is None


def daily_check(db: Session, today: date | None = None, actor: str = "scheduler") -> dict:
    """Create worksheet jobs for every active class with an exam exactly lead_days away."""
    today = today or local_today(db)
    lead = int(get_setting(db, "lead_days") or 2)
    target = today + timedelta(days=lead)
    created, skipped, blocked = [], 0, []
    for c in db.scalars(select(SchoolClass).where(SchoolClass.automation == "active")):
        if not c.datesheet_confirmed:
            blocked.append(c.name)
            audit(db, "alert", f"{c.name} · automation is blocked: no confirmed date sheet", class_id=c.id, level="error")
            continue
        exams = db.scalars(select(Exam).where(Exam.class_id == c.id, Exam.active.is_(True), Exam.exam_date == target))
        for e in exams:
            job = Job(type="CREATE_WORKSHEET", business_key=create_key(c, e), class_id=c.id, exam_id=e.id,
                      subject_name=e.subject_name, sections=e.sections, exam_date=e.exam_date, trigger_date=today,
                      source="scheduler" if actor == "scheduler" else "manual")
            if _insert_job(db, job):
                created.append(job)
                audit(db, "job", f"CREATE_WORKSHEET · {c.name} · {e.subject_name} · exam {fmt_date(e.exam_date)}",
                      actor=actor, class_id=c.id, job_id=job.id, business_key=job.business_key)
                if subject_missing_pdfs(db, c.id, e.subject_name):
                    audit(db, "alert", f"{c.name} · {e.subject_name} has no readable PDFs; the worksheet cannot be generated",
                          class_id=c.id, level="error", job_id=job.id)
            else:
                skipped += 1
    set_setting(db, "last_scheduler_run", {"at": local_now(db).isoformat(timespec="minutes"), "date": today.isoformat(),
                                           "created": len(created), "actor": actor})
    db.commit()
    return {"date": today.isoformat(), "target_exam_date": target.isoformat(), "created": len(created),
            "already_existed": skipped, "blocked_classes": blocked}


def scheduler_due(db: Session) -> bool:
    """True once per day, at or after the configured time. Catches up the same day after a restart."""
    now = local_now(db)
    hh, mm = (get_setting(db, "scheduler_time") or "06:00").split(":")
    last = get_setting(db, "last_scheduler_run") or {}
    return last.get("date") != now.date().isoformat() and (now.hour, now.minute) >= (int(hh), int(mm))


def manual_generate(db: Session, exam: Exam, actor: str) -> Job | None:
    """Admin-triggered generation for one exam (e.g. an exam missed by the two-day window)."""
    c = db.get(SchoolClass, exam.class_id)
    job = Job(type="CREATE_WORKSHEET", business_key=create_key(c, exam), class_id=c.id, exam_id=exam.id,
              subject_name=exam.subject_name, sections=exam.sections, exam_date=exam.exam_date,
              trigger_date=local_today(db), source="manual")
    job = _insert_job(db, job)
    if job:
        audit(db, "job", f"CREATE_WORKSHEET (manual) · {c.name} · {exam.subject_name}", actor=actor, class_id=c.id, job_id=job.id)
    return job


def regenerate(db: Session, ws: Worksheet, reason: str, actor: str) -> Job:
    c = db.get(SchoolClass, ws.class_id)
    exam = db.get(Exam, ws.exam_id)
    if exam is None or not exam.active:
        raise ValueError("The exam is no longer on the date sheet.")
    latest = max(w.version for w in db.scalars(select(Worksheet).where(Worksheet.exam_id == exam.id)))
    job = Job(type="CREATE_WORKSHEET", business_key=create_key(c, exam, latest + 1), class_id=c.id, exam_id=exam.id,
              subject_name=exam.subject_name, sections=exam.sections, exam_date=exam.exam_date,
              trigger_date=local_today(db), source="regenerate", last_error=reason)
    if not _insert_job(db, job):
        raise ValueError("A regeneration for this worksheet is already queued.")
    audit(db, "regeneration", f"Regeneration requested · {ws.title} · v{ws.version} → v{latest + 1}", actor=actor,
          class_id=c.id, original_version=ws.version, new_version=latest + 1, reason=reason)
    return job


def release(db: Session, ws: Worksheet, actor: str, *, approved: bool) -> Job | None:
    ws.status = "released"
    ws.released_at = utcnow()
    if approved:
        ws.approved_by, ws.approved_at = actor, utcnow()
        audit(db, "approval", f"Approved and released {ws.title} · v{ws.version}", actor=actor, class_id=ws.class_id,
              worksheet_id=ws.id)
    else:
        audit(db, "release", f"Auto-released {ws.title} · v{ws.version}", class_id=ws.class_id, worksheet_id=ws.id)
    create_job = db.get(Job, ws.create_job_id) if ws.create_job_id else None
    if create_job:
        create_job.status = "released"
    job = Job(type="SHARE_WORKSHEET", business_key=share_key(ws), class_id=ws.class_id, exam_id=ws.exam_id,
              worksheet_id=ws.id, subject_name=ws.subject_name, sections=ws.sections, exam_date=ws.exam_date,
              trigger_date=local_today(db), source="release")
    return _insert_job(db, job)


def cancel_obsolete(db: Session, class_id: int, actor: str) -> int:
    """After a date sheet change: cancel open jobs and unreleased worksheets for exams that were
    removed or moved. Released worksheets are history and are left alone."""
    n = 0
    jobs = db.scalars(select(Job).where(Job.class_id == class_id, Job.type == "CREATE_WORKSHEET",
                                        Job.status.in_(["pending", "validation-failed", "awaiting-approval"])))
    for j in jobs:
        exam = db.get(Exam, j.exam_id) if j.exam_id else None
        if exam is None or not exam.active or exam.exam_date != j.exam_date or exam.subject_name != j.subject_name:
            j.status = "cancelled"
            if j.payload and j.payload.get("batch_id"):
                from .agents.llm import cancel_batch
                cancel_batch(j.payload["batch_id"])
            n += 1
            for ws in db.scalars(select(Worksheet).where(Worksheet.create_job_id == j.id,
                                                         Worksheet.status.in_(["awaiting-approval", "validation-failed"]))):
                ws.status = "cancelled"
            audit(db, "job", f"Cancelled {j.subject_name} · exam {fmt_date(j.exam_date)}: the date sheet changed",
                  actor=actor, class_id=class_id, job_id=j.id, level="warning")
    return n


# ------------------------------------------------------------------------------------ job runner

def claim_next_job(db: Session) -> Job | None:
    now = utcnow()
    candidates = db.scalars(select(Job).where(Job.status == "pending").order_by(Job.created_at, Job.id).limit(10))
    for job in candidates:
        if job.next_attempt_at and job.next_attempt_at > now:
            continue
        # Atomic claim: only one worker can move pending → running.
        updated = db.query(Job).filter(Job.id == job.id, Job.status == "pending").update(
            {"status": "running", "attempts": Job.attempts + 1, "updated_at": now}, synchronize_session=False)
        db.commit()
        if updated:
            db.refresh(job)
            return job
    return None


def run_job(db: Session, job: Job) -> None:
    try:
        if job.type == "CREATE_WORKSHEET":
            _run_create(db, job)
        elif job.type == "SHARE_WORKSHEET":
            _run_share(db, job)
        db.commit()
    except Pending:
        # Batch request in flight: keep the payload, check again in a few minutes. Not a failed attempt.
        job.status = "pending"
        job.attempts = max(job.attempts - 1, 0)
        job.next_attempt_at = utcnow() + timedelta(minutes=3)
        db.commit()
    except BlockedError as e:
        db.rollback()
        job = db.get(Job, job.id)
        job.status, job.last_error = "failed", str(e)
        audit(db, "alert", f"{job.subject_name} · {e}", class_id=job.class_id, level="error", job_id=job.id)
        db.commit()
    except Exception as e:  # noqa: BLE001 — every other failure is retried, then surfaced
        db.rollback()
        log.exception("Job %s failed", job.id)
        job = db.get(Job, job.id)
        msg = str(e) if isinstance(e, LLMError) else f"{type(e).__name__}: {e}"
        job.last_error = msg
        if job.attempts >= get_settings().job_max_attempts:
            job.status = "failed"
            audit(db, "alert", f"{job.type} failed after {job.attempts} attempts · {job.subject_name} · {msg}",
                  class_id=job.class_id, level="error", job_id=job.id)
        else:
            job.status = "pending"
            job.next_attempt_at = utcnow() + timedelta(minutes=5 * job.attempts)
            audit(db, "retry", f"{job.type} attempt {job.attempts} failed; retrying · {msg}", class_id=job.class_id,
                  level="warning", job_id=job.id)
        db.commit()


def _run_create(db: Session, job: Job) -> None:
    school_class = db.get(SchoolClass, job.class_id)
    if job.source == "scheduler" and school_class.automation != "active":
        job.status, job.last_error = "cancelled", "Automation was paused before the job ran."
        return
    ws = create_worksheet(db, job)
    job.worksheet_id = ws.id
    if not ws.validation.get("passed"):
        ws.status = job.status = "validation-failed"
        audit(db, "alert", f"{ws.title} failed validation and needs review", class_id=ws.class_id, level="warning",
              worksheet_id=ws.id)
    elif school_class.release_mode == "auto":
        release(db, ws, "system", approved=False)
        job.status = "released"
    else:
        ws.status = job.status = "awaiting-approval"


def _run_share(db: Session, job: Job) -> None:
    ws = db.get(Worksheet, job.worksheet_id)
    if ws is None or ws.status != "released":
        job.status, job.last_error = "cancelled", "The worksheet is not released."
        return
    summary = sharing_agent.share_worksheet(db, ws)
    job = db.get(Job, job.id)
    total = sum(sum(v.values()) for v in summary.values())
    failed = sum(v.get("failed", 0) for v in summary.values())
    job.status = "failed" if total and failed == total else "completed"
    job.last_error = None if job.status == "completed" else "Every delivery failed."
    create_job = db.get(Job, ws.create_job_id) if ws.create_job_id else None
    if create_job and create_job.status == "released":
        create_job.status = "completed"
    audit(db, "delivery", f"Shared {ws.title} · " + "; ".join(
        f"{ch}: " + ", ".join(f"{n} {st}" for st, n in sorted(v.items())) for ch, v in summary.items()),
          class_id=ws.class_id, worksheet_id=ws.id, counts=summary)


def recover_stale_jobs(db: Session) -> int:
    """On startup: a job left 'running' means the process died mid-run. Put it back in the queue;
    dedup (business keys + unique deliveries) makes the re-run safe."""
    stale = list(db.scalars(select(Job).where(Job.status == "running")))
    for j in stale:
        j.status = "pending"
        audit(db, "retry", f"Resumed {j.type} after a restart · {j.subject_name}", class_id=j.class_id, job_id=j.id)
    db.commit()
    return len(stale)


def worker_tick(db: Session) -> dict:
    ran = 0
    if scheduler_due(db):
        daily_check(db)
    while (job := claim_next_job(db)) is not None and ran < 20:
        run_job(db, job)
        ran += 1
    retried = sharing_agent.retry_due(db)
    return {"jobs": ran, "delivery_retries": retried, "at": datetime.now().isoformat(timespec="seconds")}
