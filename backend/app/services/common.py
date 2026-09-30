"""Small shared helpers: institution time, app settings, audit log, contact masking."""
import re
from copy import deepcopy
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AppSetting, AuditEvent

DEFAULT_WORKSHEET_SETTINGS = {
    "counts": {"mcq": 5, "very_short": 3, "short": 5, "application": 4, "long": 2, "hots": 1},
    "difficulty": {"easy": 30, "medium": 50, "hard": 20},
    "answer_key": True,
    "language": "English",
}

SECTION_LABELS = {
    "mcq": "Multiple choice",
    "very_short": "Very short answer",
    "short": "Short answer",
    "application": "Application based",
    "long": "Long answer",
    "hots": "Higher order thinking (HOTS)",
}
SECTION_LABELS_HI = {
    "mcq": "बहुविकल्पीय प्रश्न",
    "very_short": "अति लघु उत्तरीय प्रश्न",
    "short": "लघु उत्तरीय प्रश्न",
    "application": "अनुप्रयोग आधारित प्रश्न",
    "long": "दीर्घ उत्तरीय प्रश्न",
    "hots": "उच्च स्तरीय चिंतन (HOTS)",
}
LANGUAGES = ["English", "Hindi"]


def section_labels(language: str | None) -> dict:
    return SECTION_LABELS_HI if str(language or "").lower().startswith("hindi") else SECTION_LABELS


def is_hindi_subject(subject_name: str) -> bool:
    """Hindi (the subject) is always taught and tested in Hindi: 'Hindi', 'Hindi A', 'Hindi Course B', 'हिंदी'."""
    s = subject_name.strip().lower()
    return s.startswith("hindi") or "हिंदी" in subject_name or "हिन्दी" in subject_name


def worksheet_language(settings: dict, subject_name: str) -> str:
    if is_hindi_subject(subject_name):
        return "Hindi"
    lang = str(settings.get("language") or "English").strip().capitalize()
    return lang if lang in LANGUAGES else "English"


def _defaults() -> dict:
    s = get_settings()
    return {
        "institution_name": s.institution_name,
        "timezone": s.timezone,
        "scheduler_time": s.scheduler_time,
        "lead_days": s.lead_days,
        "phase": 1,
        "worksheet_defaults": deepcopy(DEFAULT_WORKSHEET_SETTINGS),
        "last_scheduler_run": None,
        # Cost saving
        "reuse_worksheets": True,  # reuse another section's/class's worksheet with the same syllabus this term
        "use_batch": True,  # Batch API for scheduled worksheets (50% cheaper)
    }


def get_setting(db: Session, key: str):
    row = db.get(AppSetting, key)
    if row is None:
        return _defaults().get(key)
    return row.value


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def all_settings(db: Session) -> dict:
    return {k: get_setting(db, k) for k in _defaults()}


def institution_tz(db: Session) -> ZoneInfo:
    return ZoneInfo(get_setting(db, "timezone") or "Asia/Kolkata")


def local_now(db: Session) -> datetime:
    return datetime.now(institution_tz(db))


def local_today(db: Session) -> date:
    return local_now(db).date()


def merge_worksheet_settings(*layers: dict | None) -> dict:
    """Global → class → subject. Later layers override earlier ones, nested dicts merge."""
    out = deepcopy(DEFAULT_WORKSHEET_SETTINGS)
    for layer in layers:
        if not layer:
            continue
        for k, v in layer.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = {**out[k], **v}
            else:
                out[k] = v
    return out


def audit(db: Session, event: str, summary: str, *, actor: str = "system", class_id: int | None = None,
          level: str = "info", **details) -> AuditEvent:
    ev = AuditEvent(event=event, summary=summary, actor=actor, class_id=class_id, level=level, details=details)
    db.add(ev)
    return ev


def fmt_date(d: date | None) -> str:
    """10 Oct 2026 — day month year, no ordinals."""
    return f"{d.day} {d.strftime('%b %Y')}" if d else ""


def fmt_day_month(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")


def valid_email(value: str | None) -> bool:
    return bool(value) and bool(_EMAIL_RE.match(value.strip()))


def normalize_whatsapp(value: str | None, default_cc: str = "91") -> str | None:
    """Digits-only E.164 without '+'. Returns None when the number cannot be valid."""
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith(".0"):  # numbers read from spreadsheets as floats
        raw = raw[:-2]
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    elif len(digits) == 10:
        digits = default_cc + digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = default_cc + digits[1:]
    return digits if 11 <= len(digits) <= 15 else None


def mask_email(value: str | None) -> str:
    if not value or "@" not in value:
        return "—"
    local, domain = value.split("@", 1)
    return f"{local[:2]}***@{domain}"


def mask_phone(value: str | None) -> str:
    if not value:
        return "—"
    digits = re.sub(r"\D", "", value)
    if len(digits) > 10:
        digits = digits[-10:]
    return digits[:3] + "x" * max(len(digits) - 3, 0)
