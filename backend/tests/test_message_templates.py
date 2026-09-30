"""The email and WhatsApp messages sent with every worksheet: personalised, in the worksheet's language, and an extra
sheet for the same exam is introduced as extra practice."""
import copy
import json
from datetime import timedelta

from app.channels import email_template, whatsapp_template
from app.db import SessionLocal
from app.models import SchoolClass, Worksheet
from app.orchestrator import worker_tick
from app.services.common import local_today

from .test_cost_saving import _setup_class, fake_claude  # noqa: F401  (pytest fixture, used by name)


def _released_worksheet(client, name, grade):
    with SessionLocal() as db:
        today = local_today(db)
    cid = _setup_class(client, name, grade, today + timedelta(days=4), separate_rows=False)
    exam = client.get(f"/api/classes/{cid}").json()["datesheet"]["exams"][0]
    client.post(f"/api/exams/{exam['id']}/generate")
    with SessionLocal() as db:
        worker_tick(db)
        ws_id = db.query(Worksheet).filter(Worksheet.class_id == cid).one().id
    assert client.post(f"/api/worksheets/{ws_id}/approve", json={}).json()["status"] == "released"
    return cid, ws_id


def test_email_template(client, fake_claude):  # noqa: F811
    cid, ws_id = _released_worksheet(client, "Class 4", "4")
    with SessionLocal() as db:
        ws, sc = db.get(Worksheet, ws_id), db.get(SchoolClass, cid)
        subject, text, html = email_template.render(db, ws, sc, "Asha <Rao>", "Physics.pdf")
        assert subject.startswith("Physics Practice Sheet – Class 4 – Exam ")
        assert "Dear Asha <Rao>," in text and "Asha &lt;Rao&gt;" in html  # names are escaped in HTML
        assert "20 questions (5 multiple choice" in text and "09:00" in text
        assert "Chapter 1" in text and "answer key on the last page" in text and "Physics.pdf" in text
        assert "<table" in html and "<style" not in html  # inline styles only, for email clients
        # Hindi worksheet → Hindi email.
        ws.settings_used = {**ws.settings_used, "language": "Hindi"}
        subject, text, html = email_template.render(db, ws, sc, "आशा", "x.pdf")
        assert "अभ्यास पत्रक" in subject and "प्रिय आशा," in text and 'lang="hi"' in html
        db.rollback()

    # A second worksheet for the same exam is "Practice Sheet 2", introduced as extra practice.
    assert client.post(f"/api/worksheets/{ws_id}/another", json={}).status_code == 200
    with SessionLocal() as db:
        worker_tick(db)  # sends the first one
        worker_tick(db)
        v2 = db.query(Worksheet).filter(Worksheet.class_id == cid, Worksheet.version == 2).one()
        subject, text, _ = email_template.render(db, v2, db.get(SchoolClass, cid), "Asha", "x.pdf")
        assert "Physics Practice Sheet 2 – Class 4" in subject and "one more practice worksheet" in text


def test_whatsapp_template(client, fake_claude, tmp_path, monkeypatch):  # noqa: F811
    cid, ws_id = _released_worksheet(client, "Class 10", "10")
    with SessionLocal() as db:
        ws, sc = db.get(Worksheet, ws_id), db.get(SchoolClass, cid)
        lang, values = whatsapp_template.params(db, ws, sc, "Ravi\nKumar")
        assert lang == "en" and len(values) == 6
        assert values[0] == "Ravi Kumar"  # WhatsApp rejects line breaks in parameters
        assert values[1] == "Physics Practice Sheet" and values[2] == "10 A, B" and values[4] == "20"
        msg = whatsapp_template.fill(lang, values)
        assert "{{" not in msg and "Dear Ravi Kumar," in msg and "*Physics Practice Sheet*" in msg
        ws2 = copy.copy(ws)
        ws2.settings_used = {**ws.settings_used, "language": "Hindi"}
        assert whatsapp_template.params(db, ws2, sc, "Ravi")[0] == "hi"
        db.rollback()
    # The definition to submit to Meta: both languages, same number of placeholders as values.
    defs = whatsapp_template.meta_definition()
    assert [d["language"] for d in defs] == ["en", "hi"]
    for d in defs:
        body = next(c for c in d["components"] if c["type"] == "BODY")
        assert all("{{%d}}" % i in body["text"] for i in range(1, 7)) and len(body["example"]["body_text"][0]) == 6
    json.dumps(defs)
