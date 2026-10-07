"""Render a worksheet to the PDF that students receive. The answer key, when enabled, starts on a
new page at the end so teachers can print the questions alone.

Font: PSA Sans (app/fonts), one font merged from Noto Sans (Latin/Greek), Noto Sans Devanagari (Hindi)
and Noto Sans Math (√ ≤ ≥ ∠ …). Hindi is shaped with HarfBuzz (uharfbuzz) so conjuncts and vowel signs
join correctly. A single font matters: ReportLab shapes each word with one font, so mixed words like
√2, △ABC or "(irrational)" inside a Hindi sentence only print correctly when one font has every glyph."""
import re
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..config import get_settings
from ..services.common import fmt_date, section_labels
from .mathtext import layout_answer, layout_question

NAVY = colors.HexColor("#1b365d")
MUTED = colors.HexColor("#4f5f75")
LINE = colors.HexColor("#d5dde8")
SOFT = colors.HexColor("#e8f0fa")
FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"


def _add_private(self, name, gid, advance):
    """Replacement for ReportLab's TTFont.__addPrivate. Shaped Hindi conjuncts are glyphs without a Unicode
    code point; ReportLab gives each one a private-use character keyed by glyph *name*. Fonts without glyph
    names (like the hinted Noto fonts) return '' for every glyph, so all conjuncts collided on one character
    and printed wrongly. Key by glyph id instead, which is always unique."""
    unis = self.__dict__.setdefault("_psa_private", {})
    uchar = unis.get(gid)
    if uchar is None:
        face = self.face
        uchar = max(self.__dict__.get("_psa_next", 0xE000), 0xE000)
        while uchar in face.charToGlyph:
            uchar += 1
        if uchar > 0xF8FF:
            raise ValueError("Too many shaped glyphs for one font")
        self._psa_next = uchar + 1
        unis[gid] = uchar
        face.charToGlyph[uchar] = gid
        face.glyphToChar.setdefault(gid, []).append(uchar)
        face.charWidths[uchar] = advance
    return uchar


TTFont._TTFont__addPrivate = _add_private  # used via self.__addPrivate inside TTFont.hbFont()


@lru_cache
def _fonts() -> dict:
    """Register PSA Sans once (built by scripts/build_fonts.py from Noto Sans + Devanagari + Math).
    Returns {font name: set of code points}; empty if the font files are missing (Helvetica fallback)."""
    files = {"PSA": "PSASans-Regular.ttf", "PSA-Bold": "PSASans-Bold.ttf"}
    if not all((FONT_DIR / f).exists() for f in files.values()):
        return {}
    cmaps = {}
    for name, f in files.items():
        font = TTFont(name, str(FONT_DIR / f))
        pdfmetrics.registerFont(font)
        cmaps[name] = set(font.face.charToGlyph)
        if font.shapable:
            font.hbFont()  # ReportLab only wires up its glyph fallback after the first hbFont() call
    pdfmetrics.registerFontFamily("PSA", normal="PSA", bold="PSA-Bold", italic="PSA", boldItalic="PSA-Bold")
    return cmaps


def rich(text: str, bold: bool = False) -> str:
    """Escape text for a Paragraph. One font covers Latin, Hindi and maths, so no font switching is needed."""
    return f"<b>{escape(text)}</b>" if bold and _fonts() else escape(text)


_STEP_LABEL = re.compile(r"^(Given|To find|Formula|Solution|Using|Answer|Final answer|Therefore|Hence|"
                         r"दिया गया है|सूत्र|हल|उत्तर|अतः)\b\s*:?", re.I)


def lines_markup(text: str, labels: bool = False) -> str:
    """Keep the answer's line breaks in the PDF; optionally bold step labels (Given:, Formula:, Answer: …)."""
    out = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        m = _STEP_LABEL.match(line) if labels else None
        out.append(f"<b>{escape(m.group(0))}</b>{escape(line[m.end():])}" if m else escape(line))
    return "<br/>".join(out)


def _styles():
    cm = _fonts()
    base_font = "PSA" if cm else "Helvetica"
    bold_font = "PSA-Bold" if cm else "Helvetica-Bold"
    shaping = 1 if cm else 0
    base = getSampleStyleSheet()
    mk = lambda name, parent, **kw: ParagraphStyle(name, parent=base[parent], shaping=shaping, **kw)  # noqa: E731
    return {
        "title": mk("t", "Title", fontName=bold_font, fontSize=17, leading=24, textColor=NAVY, alignment=TA_LEFT, spaceAfter=2),
        "meta": mk("m", "Normal", fontName=base_font, fontSize=9.5, leading=14, textColor=MUTED),
        "section": mk("s", "Heading2", fontName=bold_font, fontSize=12, leading=18, textColor=NAVY, spaceBefore=10, spaceAfter=4),
        "q": mk("q", "Normal", fontName=base_font, fontSize=10.5, leading=17, leftIndent=18, firstLineIndent=-18),
        "opt": mk("o", "Normal", fontName=base_font, fontSize=10, leading=16, leftIndent=30),
        "small": mk("sm", "Normal", fontName=base_font, fontSize=9, leading=13, textColor=MUTED),
        "ans": mk("a", "Normal", fontName=base_font, fontSize=9.5, leading=15, leftIndent=18, firstLineIndent=-18),
    }


def _footer(title: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        # Hindi titles can't be drawn with the canvas' base font, so the footer uses the ASCII part only.
        ascii_title = re.sub(r"[^\x20-\x7E]+", " ", title).strip()
        if len(re.sub(r"[^A-Za-z]", "", ascii_title)) < 3:  # mostly Hindi title
            ascii_title = "Practice sheet"
        canvas.drawString(18 * mm, 10 * mm, ascii_title[:110])
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()
    return draw


HI = {"Class": "कक्षा", "Section": "अनुभाग", "Exam": "परीक्षा", "Exam ID": "परीक्षा आईडी", "Name": "नाम",
      "Roll no.": "अनुक्रमांक", "Answer key": "उत्तर कुंजी", "Practice sheet": "अभ्यास पत्रक"}


def render_worksheet_pdf(ws, school_class, path: Path | None = None) -> Path:
    """ws is a Worksheet, or a ParentSheet (no exam: the header says 'Practice sheet' and its date instead)."""
    st = _styles()
    if path is None:
        folder = get_settings().worksheets_dir / f"class_{school_class.id}"
        slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{ws.subject_name}_Class{school_class.grade}_{ws.exam_date.isoformat()}").strip("_")
        path = folder / f"{slug}_v{ws.version}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    exam_date = getattr(ws, "exam_date", None)

    content = ws.content
    settings = ws.settings_used or {}
    hindi = str(settings.get("language", "")).lower().startswith("hindi")
    t = (lambda k: f"{HI[k]} / {k}") if hindi else (lambda k: k)
    labels = section_labels(settings.get("language"))

    story = [Paragraph(rich(ws.title, bold=True), st["title"])]
    meta = [f"{t('Class')} {school_class.grade}" + (f" · {t('Section')} {ws.sections}" if ws.sections else "")]
    meta += ([f"{t('Exam')} {fmt_date(exam_date)}", f"{t('Exam ID')} {ws.exam_code}"] if exam_date
             else [t("Practice sheet"), fmt_date(ws.created_at.date())])
    story.append(Paragraph(rich(" · ".join(meta)), st["meta"]))
    story.append(Spacer(1, 8))
    info = Table([[Paragraph(rich(t("Name")), st["small"]), "", Paragraph(rich(t("Roll no.")), st["small"]), ""]],
                 colWidths=[28 * mm if hindi else 18 * mm, 80 * mm, 34 * mm if hindi else 20 * mm, 32 * mm])
    info.setStyle(TableStyle([("LINEBELOW", (1, 0), (1, 0), 0.6, LINE), ("LINEBELOW", (3, 0), (3, 0), 0.6, LINE),
                              ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    story += [info, Spacer(1, 8)]
    if content.get("instructions"):
        box = Table([[Paragraph(rich(content["instructions"]), st["small"])]], colWidths=[174 * mm])
        box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#a9c4e6")),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        story += [box, Spacer(1, 4)]

    n = 0
    answers = []
    opt_letters = "कखगघ" if hindi else "abcd"
    for si, sec in enumerate(content.get("sections", [])):
        letter = "ABCDEFGHIJ"[si]
        label = labels.get(sec.get("type"), sec.get("type", "").title())
        story.append(Paragraph(rich(f"{'खंड' if hindi else 'Section'} {letter} · {label}", bold=True), st["section"]))
        for q in sec.get("questions", []):
            n += 1
            block = [Paragraph(f"<b>{n}.</b> {lines_markup(layout_question(q.get('text', '')))}", st["q"])]
            for oi, opt in enumerate(q.get("options", [])):
                mark = opt_letters[oi] if oi < 4 else str(oi + 1)
                block.append(Paragraph(rich(f"({mark}) {opt}"), st["opt"]))
            block.append(Spacer(1, 6))
            story.append(KeepTogether(block))
            answers.append((n, q))

    if settings.get("answer_key", True):
        story += [PageBreak(), Paragraph(rich(t("Answer key"), bold=True), st["title"]), Spacer(1, 6)]
        for n, q in answers:
            answer = q.get("answer", "")
            answer = answer if q.get("options") else layout_answer(answer)
            story.append(Paragraph(f"<b>{n}.</b> {lines_markup(answer, labels=True)}", st["ans"]))
            story.append(Spacer(1, 3))

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=18 * mm, title=ws.title, author=get_settings().institution_name)
    doc.build(story, onFirstPage=_footer(ws.title), onLaterPages=_footer(ws.title))
    return path
