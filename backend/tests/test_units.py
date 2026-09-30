from datetime import date

from app.agents.validation import validate
from app.services.common import mask_email, mask_phone, merge_worksheet_settings, normalize_whatsapp
from app.services.syllabus import extract_chapters, parse_syllabus
from app.services.tabular import parse_datesheet, parse_date


def test_parse_date_formats():
    assert parse_date("10-Oct-2026") == date(2026, 10, 10)
    assert parse_date("10/10/2026") == date(2026, 10, 10)
    assert parse_date("2026-10-10") == date(2026, 10, 10)
    assert parse_date("10th October 2026") == date(2026, 10, 10)
    assert parse_date("next week") is None


def test_datesheet_rejects_other_class_and_bad_dates():
    csv = b"Class,Section,Subject,Exam Date,Exam Time,Exam ID\n9,A,Mathematics,10-Oct-2026,09:00 AM,EX9-MATH-001\n" \
          b"10,A,English,11-Oct-2026,09:00,\n9,A,Science,sometime,09:00,\n9,C,Hindi,12-Oct-2026,,\n9,,English,13-Oct-2026,,\n"
    exams, issues = parse_datesheet("ds.csv", csv, "9", ["A", "B"])
    assert [e["subject_name"] for e in exams] == ["Mathematics", "English"]
    assert exams[0]["exam_code"] == "EX9-MATH-001" and exams[0]["exam_time"] == "09:00"
    assert exams[1]["exam_code"] == "EX9-ENGL-001"
    msgs = " ".join(i["message"] for i in issues)
    assert "not Class 9" in msgs and "not a date" in msgs and "section C" in msgs


def test_contacts():
    assert normalize_whatsapp("98765 43210") == "919876543210"
    assert normalize_whatsapp("+44 7700 900123") == "447700900123"
    assert normalize_whatsapp("12345") is None
    assert mask_email("rahul@example.com") == "ra***@example.com"
    assert mask_phone("919876543210") == "987xxxxxxx"


def test_settings_layering():
    s = merge_worksheet_settings({"counts": {"mcq": 10}}, {"answer_key": False}, {"counts": {"long": 0}})
    assert s["counts"]["mcq"] == 10 and s["counts"]["long"] == 0 and s["counts"]["short"] == 5
    assert s["answer_key"] is False


def test_syllabus_chapters_and_split():
    assert extract_chapters("Ch 1-3, Chapter 7 and 9") == [1, 2, 3, 7, 9]
    assert extract_chapters("Chapters 2, 4 & 5") == [2, 4, 5]
    text = b"Half-yearly syllabus\nMathematics: Chapter 1, 2\nNumber systems, polynomials\nScience - Ch 1 Motion\nEnglish\nPoems 1-3"
    entries, issues, _ = parse_syllabus("s.txt", text, ["Mathematics", "Science", "English", "Hindi"])
    assert entries["mathematics"]["chapters"] == [1, 2]
    assert entries["science"]["chapters"] == [1]
    assert "english" in entries
    assert any(i["subject"] == "Hindi" for i in issues)


def test_syllabus_exclusions_win():
    text = b"Mathematics: Chapters 1 to 7\n(Chapter 6 Lines and Angles is NOT included)\nExcluding Ch 4"
    entries, _, _ = parse_syllabus("s.txt", text, ["Mathematics"])
    m = entries["mathematics"]
    assert m["chapters"] == [1, 2, 3, 5, 7]
    assert m["excluded_chapters"] == [4, 6]
    assert not any("Lines and Angles" in t for t in m["topics"])


def _q(text, ans, sources, **kw):
    return {"text": text, "options": kw.get("options", []), "answer": ans, "difficulty": kw.get("d", "medium"),
            "topic": "t", "source_ids": sources, "outside_syllabus": kw.get("oos", False), "review_note": ""}


def test_validation_catches_scope_duplicates_and_structure():
    settings = merge_worksheet_settings({"counts": {"mcq": 1, "very_short": 0, "short": 2, "application": 0, "long": 0, "hots": 0}})
    passages = {"C1": "Rational numbers can be written as p over q where q is not zero.",
                "C2": "A polynomial of degree two is called a quadratic polynomial."}
    content = {"sections": [
        {"type": "mcq", "questions": [_q("Which rational number lies between 1 and 2?", "3/2", ["C1"], options=["3/2", "5", "7", "9"])]},
        {"type": "short", "questions": [_q("Define a quadratic polynomial of degree two.", "A polynomial of degree two", ["C2"]),
                                        _q("Define a quadratic polynomial of degree two.", "Degree two polynomial", ["C9"])]},
    ]}
    r = validate(content, settings, passages | {"C9": "Lines and angles: vertically opposite angles are equal."}, scope_ids={"C1", "C2"})
    status = {c["id"]: c["status"] for c in r["checks"]}
    assert status["structure"] == "passed"
    assert status["duplicates"] == "failed"
    assert status["scope"] == "failed" and "B-2" in next(c for c in r["checks"] if c["id"] == "scope")["refs"]
    assert r["passed"] is False
