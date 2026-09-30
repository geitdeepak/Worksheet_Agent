"""The WhatsApp message every student receives with a worksheet (Phase 2).

WhatsApp only lets a business start a conversation with a template that Meta has approved in advance. The template
text below is what you submit in WhatsApp Manager (one template name, two languages: en and hi). At send time only the
numbered placeholders are filled in; the rest of the wording is fixed by Meta. The same text, filled in, is used as the
document caption in outbox (development) mode and when no template name is configured."""
from sqlalchemy.orm import Session

from ..models import Exam, SchoolClass, Worksheet
from ..services.common import get_setting
from .email_template import HINDI_MONTHS, HINDI_DAYS, sheet_number

TEMPLATE_NAME = "exam_practice_sheet"
CATEGORY = "UTILITY"
# Header: DOCUMENT (the worksheet PDF). Placeholders: {{1}} student name, {{2}} worksheet name, {{3}} class,
# {{4}} exam date and time, {{5}} questions, {{6}} school name.
BODY = {
    "en": ("Dear {{1}},\n\n"
           "Your *{{2}}* for Class {{3}} is attached. It is made from your exam syllabus.\n\n"
           "📅 Exam: {{4}}\n"
           "📝 Questions: {{5}}\n\n"
           "Try all questions on your own first, then check your answers with the answer key on the last page.\n\n"
           "All the best for your exam!\n"
           "– {{6}}"),
    "hi": ("प्रिय {{1}},\n\n"
           "कक्षा {{3}} के लिए आपका *{{2}}* संलग्न है। यह आपके परीक्षा पाठ्यक्रम पर आधारित है।\n\n"
           "📅 परीक्षा: {{4}}\n"
           "📝 प्रश्न: {{5}}\n\n"
           "पहले सभी प्रश्न स्वयं हल करें, फिर अंतिम पृष्ठ पर दी गई उत्तर कुंजी से अपने उत्तर जाँचें।\n\n"
           "परीक्षा के लिए हार्दिक शुभकामनाएँ!\n"
           "– {{6}}"),
}
FOOTER = {"en": "Exam practice worksheet", "hi": "परीक्षा अभ्यास पत्रक"}
EXAMPLE = {
    "en": ["Priya Singh", "Mathematics Practice Sheet", "9 A", "Thursday, 1 October 2026 (09:00)", "20", "Your School"],
    "hi": ["प्रिया सिंह", "हिंदी अभ्यास पत्रक", "9 A", "गुरुवार, 1 अक्टूबर 2026 (09:00)", "20", "आपका विद्यालय"],
}


def language_code(ws: Worksheet) -> str:
    return "hi" if (ws.settings_used or {}).get("language") == "Hindi" else "en"


def params(db: Session, ws: Worksheet, school_class: SchoolClass, student_name: str) -> tuple[str, list[str]]:
    """(language code, the six placeholder values). WhatsApp rejects parameters with line breaks or tabs."""
    lang = language_code(ws)
    n = sheet_number(db, ws)
    exam = db.get(Exam, ws.exam_id) if ws.exam_id else None
    d = ws.exam_date
    if lang == "hi":
        name = f"{ws.subject_name} अभ्यास पत्रक" + (f" {n}" if n > 1 else "")
        when = f"{HINDI_DAYS[d.weekday()]}, {d.day} {HINDI_MONTHS[d.month - 1]} {d.year}"
    else:
        name = f"{ws.subject_name} Practice Sheet" + (f" {n}" if n > 1 else "")
        when = f"{d.strftime('%A')}, {d.day} {d.strftime('%B %Y')}"
    if exam and exam.exam_time:
        when += f" ({exam.exam_time})"
    total = sum(len(s.get("questions", [])) for s in ws.content.get("sections", []))
    grade = f"{school_class.grade} {ws.sections}".strip() if ws.sections else str(school_class.grade)
    inst = get_setting(db, "institution_name") or "Practice Sheet Agent"
    values = [student_name, name, grade, when, str(total), inst]
    return lang, [" ".join(str(v).split()) for v in values]


def fill(lang: str, values: list[str]) -> str:
    text = BODY[lang]
    for i, v in enumerate(values, 1):
        text = text.replace("{{%d}}" % i, v)
    return text


def meta_definition() -> list[dict]:
    """The template as WhatsApp Manager / the Business Management API expects it, one entry per language."""
    return [{
        "name": TEMPLATE_NAME, "language": lang, "category": CATEGORY,
        "components": [
            {"type": "HEADER", "format": "DOCUMENT"},
            {"type": "BODY", "text": BODY[lang], "example": {"body_text": [EXAMPLE[lang]]}},
            {"type": "FOOTER", "text": FOOTER[lang]},
        ]} for lang in ("en", "hi")]
