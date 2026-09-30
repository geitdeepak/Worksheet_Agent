"""Agent 2 — Worksheet Sharing Agent. Owns distribution only; it never writes questions.

One Delivery row per worksheet × student × channel (unique), so re-running a share job after a
crash or a retry never sends twice: rows already sent are skipped."""
import logging
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..channels import PermanentError, TransientError, email_template, whatsapp_template
from ..channels import email as email_channel
from ..channels import whatsapp as whatsapp_channel
from ..config import get_settings
from ..models import Delivery, SchoolClass, Student, Worksheet, utcnow
from ..services.common import audit, get_setting, mask_email, mask_phone, normalize_whatsapp, valid_email

log = logging.getLogger("psa.sharing")
TERMINAL = {"sent", "delivered", "skipped", "failed"}


def eligible_students(db: Session, ws: Worksheet) -> list[Student]:
    """class + section + active. Sections come from the exam row; blank means every section."""
    q = select(Student).where(Student.class_id == ws.class_id, Student.active.is_(True))
    secs = [s.strip().upper() for s in (ws.sections or "").split(",") if s.strip()]
    if secs:
        q = q.where(Student.section.in_(secs))
    return list(db.scalars(q.order_by(Student.section, Student.student_code)))


def enabled_channels(db: Session, school_class: SchoolClass) -> list[str]:
    chans = []
    if school_class.channel_email:
        chans.append("email")
    if school_class.channel_whatsapp and int(get_setting(db, "phase") or 1) >= 2:
        chans.append("whatsapp")
    return chans


def prepare_deliveries(db: Session, ws: Worksheet) -> list[Delivery]:
    school_class = db.get(SchoolClass, ws.class_id)
    cc = get_settings().whatsapp_default_country_code
    existing = {(d.student_id, d.channel): d for d in db.scalars(select(Delivery).where(Delivery.worksheet_id == ws.id))}
    rows = []
    for student in eligible_students(db, ws):
        for channel in enabled_channels(db, school_class):
            d = existing.get((student.id, channel))
            if d is None:
                d = Delivery(worksheet_id=ws.id, student_id=student.id, channel=channel, status="queued")
                if channel == "email":
                    if not student.email:
                        d.status, d.error = "skipped", "No email address on file."
                    elif not valid_email(student.email):
                        d.status, d.error = "failed", "The email address is not valid."
                    d.recipient = student.email
                else:
                    number = normalize_whatsapp(student.whatsapp, cc)
                    if not number:
                        d.status, d.error = "skipped", "No valid WhatsApp number on file."
                    d.recipient = number
                db.add(d)
            rows.append(d)
    db.flush()
    return rows


def send_one(db: Session, d: Delivery, ws: Worksheet, school_class: SchoolClass, student: Student) -> None:
    s = get_settings()
    d.status = "sending"
    d.attempts += 1
    pdf = Path(ws.pdf_path) if ws.pdf_path else None
    try:
        if d.channel == "email":
            subject, text, html = email_template.render(db, ws, school_class, student.name, pdf.name if pdf else "")
            pid, resp = email_channel.send_email(d.recipient, subject, text, html, pdf)
        else:
            lang, values = whatsapp_template.params(db, ws, school_class, student.name)
            pid, resp = whatsapp_channel.send_document(d.recipient, pdf, whatsapp_template.fill(lang, values), values, lang)
        d.status, d.provider_id, d.provider_response, d.error, d.next_attempt_at = "sent", pid, resp, None, None
    except TransientError as e:
        max_attempts = s.delivery_max_attempts
        if d.attempts >= max_attempts:
            d.status, d.error = "failed", f"{e} (gave up after {d.attempts} attempts)"
        else:
            d.status, d.error = "retrying", str(e)
            d.next_attempt_at = utcnow() + timedelta(minutes=2 ** d.attempts)
        audit(db, "retry", f"{d.channel.title()} to {student.student_code} · attempt {d.attempts} · {d.status}",
              class_id=school_class.id, level="warning", delivery_id=d.id, reason=str(e))
    except PermanentError as e:
        d.status, d.error = "failed", str(e)
    recipient = mask_email(d.recipient) if d.channel == "email" else mask_phone(d.recipient)
    audit(db, d.channel, f"{d.channel.title()} {d.status} · {student.student_code} · {recipient}",
          class_id=school_class.id, level="error" if d.status == "failed" else "info",
          worksheet_id=ws.id, student=student.student_code, provider_id=d.provider_id, status=d.status)


def share_worksheet(db: Session, ws: Worksheet) -> dict:
    """Send every pending delivery for a released worksheet. Returns a summary per channel."""
    if ws.status != "released":
        raise ValueError("Only released worksheets can be shared.")
    school_class = db.get(SchoolClass, ws.class_id)
    rows = prepare_deliveries(db, ws)
    for d in rows:
        if d.status in ("queued", "sending"):
            send_one(db, d, ws, school_class, db.get(Student, d.student_id))
            db.commit()  # persist each result so a crash mid-run never resends
    return summarize(db, ws.id)


def retry_due(db: Session) -> int:
    """Called by the worker: re-send deliveries whose retry time has come."""
    due = list(db.scalars(select(Delivery).where(Delivery.status == "retrying", Delivery.next_attempt_at <= utcnow())))
    for d in due:
        ws = db.get(Worksheet, d.worksheet_id)
        send_one(db, d, ws, db.get(SchoolClass, ws.class_id), db.get(Student, d.student_id))
        db.commit()
    return len(due)


def summarize(db: Session, worksheet_id: int) -> dict:
    out: dict[str, dict[str, int]] = {}
    for d in db.scalars(select(Delivery).where(Delivery.worksheet_id == worksheet_id)):
        ch = out.setdefault(d.channel, {})
        ch[d.status] = ch.get(d.status, 0) + 1
    return out


def all_terminal(db: Session, worksheet_id: int) -> bool:
    return all(d.status in TERMINAL for d in db.scalars(select(Delivery).where(Delivery.worksheet_id == worksheet_id)))
