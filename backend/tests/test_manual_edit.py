"""Manual editing during review: teachers can delete, add, move and rewrite questions; validation treats
teacher-written questions as trusted and a changed question count as a warning, but still blocks broken MCQs."""
from datetime import timedelta

from app.db import SessionLocal
from app.models import Worksheet
from app.orchestrator import worker_tick
from app.services.common import local_today

from .test_cost_saving import _setup_class, fake_claude  # noqa: F401  (pytest fixture, used by name)


def _checks(detail):
    return {c["id"]: c["status"] for c in detail["validation"]["checks"]}


def test_teacher_can_edit_everything(client, fake_claude):  # noqa: F811
    with SessionLocal() as db:
        today = local_today(db)
    cid = _setup_class(client, "Class 3", "3", today + timedelta(days=6), separate_rows=False)
    exam = client.get(f"/api/classes/{cid}").json()["datesheet"]["exams"][0]
    assert client.post(f"/api/exams/{exam['id']}/generate").status_code == 200
    with SessionLocal() as db:
        worker_tick(db)
        ws_id = db.query(Worksheet).filter(Worksheet.class_id == cid).one().id
    d = client.get(f"/api/worksheets/{ws_id}").json()
    assert d["status"] == "awaiting-approval", _checks(d)
    content = d["content"]
    by_type = {s["type"]: s for s in content["sections"]}

    # Delete one MCQ, move a short answer into long answer, add a teacher-written question, edit the title.
    by_type["mcq"]["questions"].pop()
    moved = by_type["short"]["questions"].pop(0)
    moved["edited"] = True
    by_type["long"]["questions"].append(moved)
    by_type["short"]["questions"].append({"text": "Explain why a moving bus slows down when the brakes are applied.",
                                          "options": [], "answer": "Friction between the brakes and wheels opposes motion.",
                                          "difficulty": "easy", "source_ids": [], "origin": "teacher"})
    content["title"] = "Physics revision sheet"
    r = client.put(f"/api/worksheets/{ws_id}/content", json={"content": content})
    assert r.status_code == 200, r.text
    d = r.json()
    checks = _checks(d)
    assert checks["structure"] == "warning"  # counts differ, but the teacher chose that
    assert checks["grounding"] == "passed"  # the teacher's own question needs no textbook citation
    assert d["status"] == "awaiting-approval" and d["title"] == "Physics revision sheet"
    new_q = next(q for s in d["content"]["sections"] if s["type"] == "short" for q in s["questions"] if q.get("origin") == "teacher")
    assert new_q["edited_by"] == "admin@test.school"

    # A broken MCQ (empty option) still blocks release.
    content = d["content"]
    mcq = next(s for s in content["sections"] if s["type"] == "mcq")["questions"][0]
    mcq["options"][3] = ""
    d = client.put(f"/api/worksheets/{ws_id}/content", json={"content": content}).json()
    assert _checks(d)["structure"] == "failed" and d["status"] == "validation-failed"
    assert client.post(f"/api/worksheets/{ws_id}/approve", json={}).status_code == 409

    # Fix it, typing maths the plain way; LaTeX is converted too.
    mcq["options"][3] = r"x^{2}"
    d = client.put(f"/api/worksheets/{ws_id}/content", json={"content": content}).json()
    assert d["status"] == "awaiting-approval"
    assert next(s for s in d["content"]["sections"] if s["type"] == "mcq")["questions"][0]["options"][3] == "x²"
    assert client.post(f"/api/worksheets/{ws_id}/approve", json={}).json()["status"] == "released"
    # Once released, it is locked.
    assert client.put(f"/api/worksheets/{ws_id}/content", json={"content": content}).status_code == 409

    # "Make another worksheet": new questions for the same exam, sent separately; the first one is untouched.
    with SessionLocal() as db:
        worker_tick(db)  # deliver the first worksheet
    assert client.post(f"/api/worksheets/{ws_id}/regenerate", json={"reason": "x"}).status_code == 409  # sent: locked
    r = client.post(f"/api/worksheets/{ws_id}/another", json={"reason": "More numericals"})
    assert r.status_code == 200, r.text
    assert client.post(f"/api/worksheets/{ws_id}/another", json={}).status_code == 409  # already being made
    with SessionLocal() as db:
        worker_tick(db)
        v2 = db.query(Worksheet).filter(Worksheet.class_id == cid, Worksheet.version == 2).one()
        assert v2.status == "awaiting-approval" and v2.regeneration_reason == "More numericals"
        assert db.get(Worksheet, ws_id).status == "released"
        v2_id = v2.id
    assert "<already_used>" in fake_claude["briefs"][-1]
    assert "moving bus slows down" in fake_claude["briefs"][-1]  # the teacher's question is on the do-not-repeat list
    assert client.post(f"/api/worksheets/{v2_id}/approve", json={}).json()["status"] == "released"
    with SessionLocal() as db:
        worker_tick(db)
    first = client.get(f"/api/worksheets/{ws_id}/deliveries").json()["summary"]["email"]
    second = client.get(f"/api/worksheets/{v2_id}/deliveries").json()["summary"]["email"]
    assert first == second == {"sent": 3}  # the same three students received both, separately
