"""Maths notation, Hindi language rules and the PDF fonts."""
from datetime import date
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from app.agents.mathtext import to_plain_math
from app.agents.pdf_render import _fonts, render_worksheet_pdf, rich
from app.services.common import is_hindi_subject, merge_worksheet_settings, worksheet_language


@pytest.mark.parametrize("src,want", [
    (r"Simplify $\frac{3}{4} + \frac{1}{2}$", "Simplify 3/4 + 1/2"),
    (r"Solve x^{2} - 5x + 6 = 0", "Solve x² - 5x + 6 = 0"),
    (r"\sqrt{2} is irrational", "√2 is irrational"),
    (r"In \triangle ABC, \angle A = 60^\circ", "In △ ABC, ∠ A = 60°"),
    (r"Area = \pi r^2", "Area = π r²"),
    (r"\frac{x+1}{x-1} \geq 0", "(x+1)/(x-1) ≥ 0"),
    (r"\sqrt[3]{27} = 3", "³√27 = 3"),
    (r"a_{1} + a_{n}", "a₁ + aₙ"),
    (r"x_{12}", "x₁₂"),
    ("x² + 2x already plain", "x² + 2x already plain"),
    ("Rs 50 and 10% off", "Rs 50 and 10% off"),
    (r"\left( \frac{1}{2} \right)^{-1}", "( 1/2 )⁻¹"),
    ("ends with a backslash \\", "ends with a backslash "),
])
def test_plain_math(src, want):
    assert to_plain_math(src) == want


def test_hindi_subject_is_always_hindi():
    s = merge_worksheet_settings({"language": "English"})
    assert worksheet_language(s, "Hindi") == "Hindi"
    assert worksheet_language(s, "Hindi Course B") == "Hindi"
    assert worksheet_language(s, "हिंदी") == "Hindi"
    assert worksheet_language(s, "Mathematics") == "English"
    assert worksheet_language(merge_worksheet_settings({"language": "Hindi"}), "Science") == "Hindi"
    assert not is_hindi_subject("Mathematics")


def test_fonts_cover_every_character_we_use():
    cm = _fonts()
    assert cm, "bundled fonts in app/fonts are missing"
    sample = "AZaz09 ²³⁻¹₁₂ₙᵢ√∛π×÷±≤≥≠∠°θ△∥⊥≅½¾–’“” अआइकखगघ क्षत्रज्ञ श्र ि ी ु ू े ै ो ौ ं ः ँ ् । ॥ ०१२३"
    for font in ("PSA", "PSA-Bold"):
        missing = [f"{c} U+{ord(c):04X}" for c in sample if not c.isspace() and ord(c) not in cm[font]]
        assert not missing, f"{font} cannot draw {missing}"


def test_rich_only_escapes():
    assert rich("x < 5 & (क)") == "x &lt; 5 &amp; (क)"


def test_hindi_and_math_pdf_renders(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config.get_settings(), "data_dir", tmp_path)
    ws = SimpleNamespace(
        title="गणित अभ्यास पत्रक – कक्षा 9 – परीक्षा 1 अक्टूबर", subject_name="Mathematics", sections="A", exam_code="EX9-MATH-001",
        exam_date=date(2026, 10, 1), version=1, settings_used={"language": "Hindi", "answer_key": True},
        content={"instructions": "सभी प्रश्न हल कीजिए।", "sections": [
            {"type": "mcq", "questions": [{"text": "√2 एक अपरिमेय संख्या है। x² − 5x + 6 = 0 के मूल ज्ञात कीजिए।",
                                           "options": ["2, 3", "−2, −3", "1, 6", "π"], "answer": "2, 3"}]},
            {"type": "short", "questions": [{"text": "∠ABC = 60° हो तो त्रिभुज की प्रकृति बताइए।", "options": [], "answer": "समबाहु"}]},
        ]})
    path = render_worksheet_pdf(ws, SimpleNamespace(id=1, grade="9"))
    text = "".join(p.extract_text() for p in PdfReader(str(path)).pages)
    assert "√" in text and "∠" in text and "परी" in text
    # Shaped conjuncts use private-use codes; each distinct conjunct must get its own (no collisions).
    private = {c for c in text if 0xE000 <= ord(c) <= 0xF8FF}
    assert len(private) >= 8, private
