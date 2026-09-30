"""Cost saving: Batch API for scheduled worksheets, direct calls for manual ones, and reuse of one worksheet
across sections with the same syllabus, while every section's students still receive it.
Claude is simulated here; no real API calls are made."""
import re
from datetime import timedelta

import pytest

from app import config
from app.agents import creation_agent
from app.db import SessionLocal
from app.models import Delivery, Job, Worksheet
from app.orchestrator import daily_check, worker_tick
from app.services.common import local_today, set_setting

from .conftest import make_pdf

_WORDS = ("velocity acceleration displacement distance inertia momentum friction gravity pressure density buoyancy "
          "energy power work torque pulley lever pendulum frequency amplitude wavelength echo reflection refraction "
          "lens mirror prism spectrum current voltage resistance circuit magnet compass orbit satellite rocket thrust "
          "impulse collision elastic spring tension stress strain viscosity turbulence vacuum barometer thermometer "
          "calorie conduction convection radiation insulator conductor filament battery generator turbine dynamo "
          "transformer kinetic potential").split()
# 30 sentences, each built from a different combination of words, so no two questions look alike.
SENTENCES = [f"The {_WORDS[i % len(_WORDS)]} of a body relates closely to {_WORDS[(i + 17) % len(_WORDS)]}, "
             f"{_WORDS[(i + 31) % len(_WORDS)]} and {_WORDS[(i + 47) % len(_WORDS)]} in everyday situations."
             for i in range(30)]
COUNTS = {"mcq": 5, "very_short": 3, "short": 5, "application": 4, "long": 2, "hots": 1}


def fake_worksheet(passages_block: str) -> dict:
    """What a well-behaved model returns: grounded, distinct questions citing real passage ids."""
    ids = re.findall(r'<passage id="(C\d+)"', passages_block)
    texts = dict(zip(ids, re.findall(r'<passage id="C\d+"[^>]*>\n(.*?)\n</passage>', passages_block, re.S)))
    sents, seen = [], set()
    for pid in ids:  # neighbouring chunks overlap, so skip sentences already taken
        for s in re.split(r"(?<=\.)\s+", texts[pid]):
            s = " ".join(s.split())
            if len(s.split()) > 8 and s not in seen:
                seen.add(s)
                sents.append((pid, s))
    sections, i = [], 0
    for qtype, n in COUNTS.items():
        qs = []
        for _ in range(n):
            pid, s = sents[i % len(sents)]
            i += 1
            opts = ["uniform", "zero", "three", "metre"] if qtype == "mcq" else []
            qs.append({"text": f"Q{i}. Using this statement, explain: {s}", "options": opts,
                       "answer": "zero" if opts else s, "difficulty": ["easy", "medium", "hard"][i % 3], "topic": "Motion",
                       "source_ids": [pid], "outside_syllabus": False, "review_note": ""})
        sections.append({"type": qtype, "questions": qs})
    return {"title": "Physics Practice Sheet – Class 11", "instructions": "Answer all.", "coverage_plan": [], "sections": sections}


@pytest.fixture
def fake_claude(monkeypatch):
    calls = {"direct": 0, "batch_submit": 0, "batch_poll": 0, "blocks": {}}

    def direct(block, brief):
        calls["direct"] += 1
        return fake_worksheet(block), "claude-sonnet-5"

    def submit(custom_id, block, brief):
        calls["batch_submit"] += 1
        calls["blocks"][custom_id] = block
        return f"batch-{custom_id}"

    def poll(batch_id):
        calls["batch_poll"] += 1
        if calls["batch_poll"] == 1:
            return None  # still running on the first check
        return fake_worksheet(calls["blocks"][batch_id.removeprefix("batch-")]), "claude-sonnet-5"

    monkeypatch.setattr(config.get_settings(), "llm_provider", "anthropic")
    monkeypatch.setattr(creation_agent.llm, "generate_worksheet_json", direct)
    monkeypatch.setattr(creation_agent.llm, "submit_worksheet_batch", submit)
    monkeypatch.setattr(creation_agent.llm, "poll_worksheet_batch", poll)
    monkeypatch.setattr(creation_agent.llm, "cancel_batch", lambda b: None)
    return calls


def _setup_class(client, name: str, grade: str, exam_day, separate_rows: bool = True) -> int:
    cid = client.post("/api/classes", json={"name": name, "grade": grade, "sections": "A, B"}).json()["id"]
    d = exam_day.strftime("%d-%b-%Y")
    rows = (f"{grade},A,Physics,{d},09:00,EX{grade}-PHY-A\n{grade},B,Physics,{d},09:00,EX{grade}-PHY-B\n" if separate_rows
            else f"{grade},\"A, B\",Physics,{d},09:00,EX{grade}-PHY\n")
    client.post(f"/api/classes/{cid}/datesheet", files={"file": ("ds.csv", f"Class,Section,Subject,Exam Date,Exam Time,Exam ID\n{rows}".encode(), "text/csv")})
    client.post(f"/api/classes/{cid}/datesheet/confirm")
    client.post(f"/api/classes/{cid}/syllabus", files={"file": ("s.txt", b"Physics: Chapter 1 Motion", "text/plain")})
    client.post(f"/api/classes/{cid}/syllabus/confirm")
    sid = client.post(f"/api/classes/{cid}/subjects", json={"name": "Physics"}).json()["id"]
    client.post(f"/api/subjects/{sid}/documents", files=[("files", ("Chapter-01.pdf", make_pdf(SENTENCES), "application/pdf"))])
    students = (f"Student ID,Name,Class,Section,Email\nP{grade}01,Asha,{grade},A,asha{grade}@example.com\n"
                f"P{grade}02,Ravi,{grade},A,ravi{grade}@example.com\nP{grade}03,Meena,{grade},B,meena{grade}@example.com\n").encode()
    client.post(f"/api/classes/{cid}/students/upload", files={"file": ("s.csv", students, "text/csv")})
    r = client.post(f"/api/classes/{cid}/automation", json={"action": "activate"})
    assert r.status_code == 200, r.text
    return cid


def test_batch_and_reuse_across_sections(client, fake_claude):
    with SessionLocal() as db:
        today = local_today(db)
        set_setting(db, "reuse_worksheets", True)
        set_setting(db, "use_batch", True)
        db.commit()
    cid = _setup_class(client, "Class 11", "11", today + timedelta(days=2))

    with SessionLocal() as db:
        assert daily_check(db, today=today)["created"] == 2  # section A and section B rows
        worker_tick(db)  # A: batch submitted; B: waits for A instead of paying twice
        assert fake_claude["batch_submit"] == 1 and fake_claude["direct"] == 0
        jobs = db.query(Job).filter(Job.class_id == cid).order_by(Job.id).all()
        assert all(j.status == "pending" for j in jobs)
        for j in jobs:
            j.next_attempt_at = None  # skip the 3-minute wait in the test
        db.commit()
        worker_tick(db)  # A: batch still running (poll 1)
        for j in db.query(Job).filter(Job.class_id == cid):
            j.next_attempt_at = None
        db.commit()
        worker_tick(db)  # A: batch done → worksheet; B: reuses A's worksheet
        wss = db.query(Worksheet).filter(Worksheet.class_id == cid).order_by(Worksheet.id).all()
        assert len(wss) == 2, [c for w in wss for c in w.validation["checks"] if c["status"] == "failed"]
        a, b = wss
        assert a.generator.endswith("(batch)") and a.reused_from_id is None
        assert b.reused_from_id == a.id and b.generator.startswith("reused from")
        assert b.content["sections"] == a.content["sections"]
        assert a.status == b.status == "awaiting-approval"
        assert fake_claude["batch_submit"] == 1 and fake_claude["direct"] == 0  # one AI call for two sections
        a_id, b_id = a.id, b.id

    # Each section's worksheet is approved and sent to its own students.
    for ws_id in (a_id, b_id):
        assert client.post(f"/api/worksheets/{ws_id}/approve", json={}).json()["status"] == "released"
    with SessionLocal() as db:
        worker_tick(db)
        sent_a = {d.recipient for d in db.query(Delivery).filter(Delivery.worksheet_id == a_id)}
        sent_b = {d.recipient for d in db.query(Delivery).filter(Delivery.worksheet_id == b_id)}
    assert sent_a == {"asha11@example.com", "ravi11@example.com"}
    assert sent_b == {"meena11@example.com"}


def test_manual_generation_is_direct_and_reuse_can_be_turned_off(client, fake_claude):
    with SessionLocal() as db:
        today = local_today(db)
        set_setting(db, "reuse_worksheets", False)
        db.commit()
    cid = _setup_class(client, "Class 12", "12", today + timedelta(days=5))
    exams = client.get(f"/api/classes/{cid}").json()["datesheet"]["exams"]
    for e in exams:
        assert client.post(f"/api/exams/{e['id']}/generate").status_code == 200
    with SessionLocal() as db:
        worker_tick(db)
        wss = db.query(Worksheet).filter(Worksheet.class_id == cid).all()
        assert len(wss) == 2 and all(w.reused_from_id is None for w in wss)
    assert fake_claude["direct"] == 2 and fake_claude["batch_submit"] == 0  # "Make it now" never waits for a batch

    # With reuse on, a regeneration still writes a fresh worksheet (the teacher asked for new questions).
    with SessionLocal() as db:
        set_setting(db, "reuse_worksheets", True)
        db.commit()
    ws_id = wss[0].id
    assert client.post(f"/api/worksheets/{ws_id}/regenerate", json={"reason": "new questions please"}).status_code == 200
    with SessionLocal() as db:
        worker_tick(db)
        v2 = db.query(Worksheet).filter(Worksheet.exam_id == wss[0].exam_id, Worksheet.version == 2).one()
        assert v2.reused_from_id is None
    assert fake_claude["direct"] == 3
