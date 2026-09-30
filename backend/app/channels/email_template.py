"""The email every student receives with a worksheet: a branded HTML email plus a plain-text version.

Email clients ignore stylesheets and modern layout, so the HTML uses tables and inline styles only. The email is in
Hindi when the worksheet is in Hindi. A second (third …) worksheet for the same exam is introduced as extra practice."""
from datetime import date
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Exam, SchoolClass, Worksheet
from ..services.common import get_setting

HINDI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
HINDI_DAYS = ["सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"]
NAVY, INK, MUTED, SOFT, LINE, ACCENT = "#1b365d", "#13233a", "#4f5f75", "#eef2ff", "#d5dde8", "#4f46e5"

T = {
    "English": {
        "subject": "{subject} Practice Sheet – Class {grade} – Exam {day} {month}",
        "subject_extra": "{subject} Practice Sheet {n} – Class {grade} – Exam {day} {month}",
        "greeting": "Dear {name},",
        "intro": "Your <b>{subject}</b> exam is on <b>{when}</b>. To help you prepare, we have made a practice worksheet "
                 "based on your exam syllabus. It is attached to this email as a PDF.",
        "intro_extra": "Here is <b>one more practice worksheet</b> for your <b>{subject}</b> exam on <b>{when}</b>. It has "
                       "new questions on the same syllabus, so you get extra practice before the exam. It is attached as a PDF.",
        "details": "Worksheet details",
        "row_subject": "Subject", "row_class": "Class", "row_exam": "Exam date", "row_syllabus": "Syllabus covered",
        "row_questions": "Questions",
        "questions": "{n} questions ({types})",
        "how": "How to use this worksheet",
        "tips": ["Find a quiet place and try the questions on your own, without your book.",
                 "Give yourself about {minutes} minutes, as if it were the real exam.",
                 "When you finish, check your work with the answer key on the last page.",
                 "Note the questions you found hard and revise those topics once more."],
        "tips_nokey": ["Find a quiet place and try the questions on your own, without your book.",
                       "Give yourself about {minutes} minutes, as if it were the real exam.",
                       "Ask your teacher about any question you are not sure of."],
        "attachment": "Attached: {file}",
        "wish": "We wish you all the best for your exam!",
        "regards": "Best regards,",
        "footer": "This worksheet was sent to you by {inst} because you are in Class {grade}{section}. "
                  "If you have a question, please speak to your class teacher.",
        "section": ", Section {s}",
        "all_chapters": "As per your exam syllabus",
        "chapter_list": "Chapter {list}", "chapters_list": "Chapters {list}",
    },
    "Hindi": {
        "subject": "{subject} अभ्यास पत्रक – कक्षा {grade} – परीक्षा {day} {month}",
        "subject_extra": "{subject} अभ्यास पत्रक {n} – कक्षा {grade} – परीक्षा {day} {month}",
        "greeting": "प्रिय {name},",
        "intro": "आपकी <b>{subject}</b> की परीक्षा <b>{when}</b> को है। आपकी तैयारी के लिए हमने आपके परीक्षा पाठ्यक्रम पर आधारित "
                 "एक अभ्यास पत्रक बनाया है। यह इस ईमेल के साथ PDF के रूप में संलग्न है।",
        "intro_extra": "आपकी <b>{subject}</b> की परीक्षा (<b>{when}</b>) के लिए यह <b>एक और अभ्यास पत्रक</b> है। इसमें उसी पाठ्यक्रम "
                       "पर नए प्रश्न हैं, ताकि परीक्षा से पहले आपका अतिरिक्त अभ्यास हो सके। यह PDF के रूप में संलग्न है।",
        "details": "अभ्यास पत्रक का विवरण",
        "row_subject": "विषय", "row_class": "कक्षा", "row_exam": "परीक्षा तिथि", "row_syllabus": "पाठ्यक्रम",
        "row_questions": "प्रश्न",
        "questions": "{n} प्रश्न ({types})",
        "how": "इस अभ्यास पत्रक का उपयोग कैसे करें",
        "tips": ["किसी शांत जगह पर बैठकर, बिना किताब देखे, स्वयं प्रश्न हल करें।",
                 "लगभग {minutes} मिनट का समय लें, जैसे असली परीक्षा में।",
                 "हल करने के बाद अंतिम पृष्ठ पर दी गई उत्तर कुंजी से अपने उत्तर जाँचें।",
                 "जिन प्रश्नों में कठिनाई हुई, उनसे जुड़े विषय एक बार फिर दोहराएँ।"],
        "tips_nokey": ["किसी शांत जगह पर बैठकर, बिना किताब देखे, स्वयं प्रश्न हल करें।",
                       "लगभग {minutes} मिनट का समय लें, जैसे असली परीक्षा में।",
                       "जिस प्रश्न में संदेह हो, उसके बारे में अपने शिक्षक से पूछें।"],
        "attachment": "संलग्न: {file}",
        "wish": "परीक्षा के लिए आपको हार्दिक शुभकामनाएँ!",
        "regards": "सादर,",
        "footer": "यह अभ्यास पत्रक {inst} द्वारा आपको भेजा गया है क्योंकि आप कक्षा {grade}{section} में हैं। "
                  "किसी प्रश्न के लिए कृपया अपने कक्षा शिक्षक से संपर्क करें।",
        "section": ", अनुभाग {s}",
        "all_chapters": "परीक्षा पाठ्यक्रम के अनुसार",
        "chapter_list": "अध्याय {list}", "chapters_list": "अध्याय {list}",
    },
}
TYPE_NAMES = {
    "English": {"mcq": "multiple choice", "very_short": "very short", "short": "short answer", "application": "application",
                "long": "long answer", "hots": "HOTS"},
    "Hindi": {"mcq": "बहुविकल्पीय", "very_short": "अति लघु", "short": "लघु उत्तरीय", "application": "अनुप्रयोग",
              "long": "दीर्घ उत्तरीय", "hots": "HOTS"},
}
MINUTES = {"mcq": 1, "very_short": 2, "short": 4, "application": 5, "long": 8, "hots": 6}


def _when(d: date, time: str | None, lang: str) -> str:
    if lang == "Hindi":
        s = f"{HINDI_DAYS[d.weekday()]}, {d.day} {HINDI_MONTHS[d.month - 1]} {d.year}"
    else:
        s = f"{d.strftime('%A')}, {d.day} {d.strftime('%B %Y')}"
    return s + (f" ({time})" if time else "")


def sheet_number(db: Session, ws: Worksheet) -> int:
    """1 for the first worksheet sent for an exam, 2 for the next extra sheet, and so on."""
    earlier = db.scalars(select(Worksheet.id).where(Worksheet.exam_id == ws.exam_id, Worksheet.status == "released",
                                                    Worksheet.version < ws.version)).all()
    return 1 + len(earlier)


def render(db: Session, ws: Worksheet, school_class: SchoolClass, student_name: str, attachment_name: str) -> tuple[str, str, str]:
    """Returns (subject, plain text, html) for one student."""
    settings = ws.settings_used or {}
    lang = "Hindi" if settings.get("language") == "Hindi" else "English"
    t = T[lang]
    inst = get_setting(db, "institution_name") or "Practice Sheet Agent"
    exam = db.get(Exam, ws.exam_id) if ws.exam_id else None
    d = ws.exam_date
    month = HINDI_MONTHS[d.month - 1] if lang == "Hindi" else d.strftime("%B")
    n = sheet_number(db, ws)
    subject = (t["subject_extra"] if n > 1 else t["subject"]).format(subject=ws.subject_name, grade=school_class.grade,
                                                                      day=d.day, month=month, n=n)
    when = _when(d, exam.exam_time if exam else None, lang)
    intro = (t["intro_extra"] if n > 1 else t["intro"]).format(subject=escape(ws.subject_name), when=escape(when))
    counts = {s["type"]: len(s["questions"]) for s in ws.content.get("sections", []) if s.get("questions")}
    total = sum(counts.values())
    types = ", ".join(f"{c} {TYPE_NAMES[lang].get(k, k)}" for k, c in counts.items())
    minutes = max(15, round(sum(MINUTES.get(k, 3) * c for k, c in counts.items()) / 5) * 5)
    chapters = (ws.content.get("_scope") or {}).get("chapters") or []
    syllabus = (t["chapters_list" if len(chapters) > 1 else "chapter_list"].format(list=", ".join(map(str, chapters)))
                if chapters else t["all_chapters"])
    section_label = t["section"].format(s=ws.sections) if ws.sections else ""
    rows = [(t["row_subject"], ws.subject_name), (t["row_class"], f"{school_class.grade}{section_label.replace(', ', ' · ')}"),
            (t["row_exam"], when), (t["row_syllabus"], syllabus), (t["row_questions"], t["questions"].format(n=total, types=types))]
    tips = [x.format(minutes=minutes) for x in (t["tips"] if settings.get("answer_key", True) else t["tips_nokey"])]
    footer = t["footer"].format(inst=inst, grade=school_class.grade, section=section_label)
    greeting = t["greeting"].format(name=student_name)

    text = "\n".join([
        greeting, "", _strip(intro), "", t["details"].upper(), *[f"  {k}: {v}" for k, v in rows], "", t["how"].upper(),
        *[f"  {i}. {tip}" for i, tip in enumerate(tips, 1)], "", t["attachment"].format(file=attachment_name), "",
        t["wish"], "", t["regards"], inst, "", "—", footer])

    font = "'Segoe UI', Roboto, Arial, 'Nirmala UI', 'Noto Sans Devanagari', sans-serif"
    detail_rows = "".join(
        f'<tr><td style="padding:8px 12px;color:{MUTED};font-size:13px;width:38%;border-top:1px solid {LINE};">{escape(k)}</td>'
        f'<td style="padding:8px 12px;color:{INK};font-size:14px;font-weight:600;border-top:1px solid {LINE};">{escape(str(v))}</td></tr>'
        for k, v in rows)
    tip_rows = "".join(
        f'<tr><td style="width:28px;vertical-align:top;padding:4px 0;"><span style="display:inline-block;width:22px;height:22px;'
        f'line-height:22px;border-radius:11px;background:{ACCENT};color:#ffffff;font-size:12px;font-weight:700;text-align:center;">{i}</span></td>'
        f'<td style="padding:4px 0 4px 6px;color:{INK};font-size:14px;line-height:21px;">{escape(tip)}</td></tr>'
        for i, tip in enumerate(tips, 1))
    html = f"""<!doctype html>
<html lang="{'hi' if lang == 'Hindi' else 'en'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f4f6fb;font-family:{font};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6fb;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid {LINE};">
  <tr><td style="background:{NAVY};background-image:linear-gradient(135deg,{NAVY} 0%,{ACCENT} 100%);padding:22px 28px;">
    <div style="color:#ffffff;font-size:13px;letter-spacing:.06em;text-transform:uppercase;opacity:.85;">{escape(inst)}</div>
    <div style="color:#ffffff;font-size:22px;font-weight:700;line-height:30px;margin-top:4px;">{escape(subject)}</div>
  </td></tr>
  <tr><td style="padding:26px 28px 8px;">
    <p style="margin:0 0 12px;color:{INK};font-size:16px;font-weight:600;">{escape(greeting)}</p>
    <p style="margin:0 0 20px;color:{INK};font-size:15px;line-height:23px;">{intro}</p>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{SOFT};border-radius:10px;border:1px solid {LINE};">
      <tr><td colspan="2" style="padding:10px 12px;color:{NAVY};font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;">{escape(t['details'])}</td></tr>
      {detail_rows}
    </table>
    <p style="margin:24px 0 8px;color:{NAVY};font-size:15px;font-weight:700;">{escape(t['how'])}</p>
    <table role="presentation" cellpadding="0" cellspacing="0">{tip_rows}</table>
    <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:20px;"><tr>
      <td style="background:#f7f7fa;border:1px dashed {LINE};border-radius:8px;padding:10px 14px;color:{INK};font-size:13px;">
        &#128206; {escape(t['attachment'].format(file=attachment_name))}</td></tr></table>
    <p style="margin:24px 0 4px;color:{INK};font-size:15px;font-weight:600;">{escape(t['wish'])}</p>
    <p style="margin:16px 0 0;color:{INK};font-size:14px;line-height:21px;">{escape(t['regards'])}<br><b>{escape(inst)}</b></p>
  </td></tr>
  <tr><td style="padding:18px 28px 22px;">
    <div style="border-top:1px solid {LINE};padding-top:14px;color:{MUTED};font-size:12px;line-height:18px;">{escape(footer)}</div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""
    return subject, text, html


def _strip(html_text: str) -> str:
    return html_text.replace("<b>", "").replace("</b>", "")
