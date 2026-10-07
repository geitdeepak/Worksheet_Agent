"""Parents: an administrator links a parent to their child; the parent makes private practice sheets for that child
(any subject, any time), limited per child per day, and can't reach any staff page or another family's sheets."""
from datetime import timedelta

from app.db import SessionLocal
from app.models import ParentSheet, Worksheet
from app.orchestrator import worker_tick
from app.services.common import local_today, set_setting

from .test_cost_saving import _setup_class, fake_claude  # noqa: F401  (pytest fixture, used by name)


def _login(client, email, password) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _outbox() -> set:
    from app.config import get_settings
    folder = get_settings().outbox_dir / "email"
    return set(folder.glob("*.eml")) if folder.exists() else set()


def _read_eml(path) -> tuple[str, str]:
    """(subject, plain-text body) of an outbox email."""
    from email import policy
    from email.parser import BytesParser
    msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    return msg["Subject"], msg.get_body(preferencelist=("plain",)).get_content()


def _drain():
    with SessionLocal() as db:
        worker_tick(db)


def test_parent_makes_private_practice_sheets(client, fake_claude):  # noqa: F811
    with SessionLocal() as db:
        today = local_today(db)
        set_setting(db, "parent_daily_limit", 2)
        db.commit()
    cid = _setup_class(client, "Class 2", "2", today + timedelta(days=30))
    students = {s["student_code"]: s["id"] for s in client.get(f"/api/classes/{cid}/students").json()["students"]}
    asha, ravi = students["P201"], students["P202"]

    # The admin creates parent accounts; a parent must be linked to a child.
    bad = {"email": "nochild@example.com", "name": "No Child", "role": "parent", "password": "parent-pass-1", "student_ids": []}
    assert client.post("/api/users", json=bad).status_code == 400
    r = client.post("/api/users", json={"email": "asha.parent@example.com", "name": "Asha's Parent", "role": "parent",
                                        "password": "parent-pass-1", "student_ids": [asha], "class_access": [cid]})
    assert r.status_code == 200, r.text
    assert r.json()["student_ids"] == [asha] and r.json()["class_access"] == []  # parents never get class access
    listed = next(u for u in client.get("/api/users").json() if u["email"] == "asha.parent@example.com")
    assert listed["children"][0]["name"] == "Asha"
    client.post("/api/users", json={"email": "ravi.parent@example.com", "name": "Ravi's Parent", "role": "parent",
                                    "password": "parent-pass-2", "student_ids": [ravi]})
    p1 = _login(client, "asha.parent@example.com", "parent-pass-1")
    p2 = _login(client, "ravi.parent@example.com", "parent-pass-2")

    # Parents can't reach any staff page, even read-only ones.
    for path in ("/api/dashboard", "/api/classes", f"/api/classes/{cid}", f"/api/classes/{cid}/students",
                 "/api/worksheets", "/api/jobs", "/api/audit", "/api/settings", "/api/users"):
        assert client.get(path, headers=p1).status_code == 403, path
    assert client.get("/api/auth/me", headers=p1).json()["role"] == "parent"
    # ...and staff can't use the parent pages.
    assert client.get("/api/parent/overview").status_code == 403

    ov = client.get("/api/parent/overview", headers=p1).json()
    assert [c["name"] for c in ov["children"]] == ["Asha"] and ov["limit"] == 2
    physics = next(s for s in ov["children"][0]["subjects"] if s["name"] == "Physics")
    assert physics["chapters"], physics

    # Only their own child, an existing subject and real chapters.
    assert client.post("/api/parent/sheets", headers=p1, json={"student_id": ravi, "subject": "Physics"}).status_code == 404
    assert client.post("/api/parent/sheets", headers=p1, json={"student_id": asha, "subject": "History"}).status_code == 400
    assert client.post("/api/parent/sheets", headers=p1, json={"student_id": asha, "subject": "Physics",
                                                               "chapters": ["Chapter 99"]}).status_code == 400

    r = client.post("/api/parent/sheets", headers=p1, json={"student_id": asha, "subject": "physics",
                                                           "chapters": physics["chapters"][:1]})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["status"] == "generating" and first["subject"] == "Physics"
    # One at a time per child.
    assert client.post("/api/parent/sheets", headers=p1, json={"student_id": asha, "subject": "Physics"}).status_code == 409
    _drain()
    sheet = next(s for s in client.get("/api/parent/overview", headers=p1).json()["sheets"] if s["id"] == first["id"])
    assert sheet["status"] == "ready" and sheet["has_pdf"] and sheet["questions"] > 0, sheet
    pdf = client.get(f"/api/parent/sheets/{first['id']}/pdf", headers=p1)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # Another family can't open it.
    assert client.get(f"/api/parent/sheets/{first['id']}/pdf", headers=p2).status_code == 404
    assert client.get("/api/parent/overview", headers=p2).json()["sheets"] == []

    # Private: it never reaches teacher review or class delivery.
    with SessionLocal() as db:
        assert db.query(Worksheet).filter(Worksheet.class_id == cid).count() == 0
        assert db.get(ParentSheet, first["id"]).title.startswith("Physics Practice Sheet")

    # A second sheet (all chapters) avoids repeating the first one's questions; then the daily limit applies.
    second = client.post("/api/parent/sheets", headers=p1, json={"student_id": asha, "subject": "Physics"}).json()
    _drain()
    with SessionLocal() as db:
        s2 = db.get(ParentSheet, second["id"])
        assert s2.status == "ready", (s2.error, [c for c in s2.validation.get("checks", []) if c["status"] == "failed"])
    # The brief says it is a parent's practice sheet; the first one names the chosen chapter, the second lists the
    # questions already practised so they are not repeated. Batch is never used: the parent is waiting.
    first_brief, second_brief = fake_claude["briefs"][-2:]
    assert "requested by a parent" in first_brief and physics["chapters"][0] in first_brief
    assert "<already_used>" in second_brief and "Exam:" not in second_brief
    assert fake_claude["batch_submit"] == 0
    r = client.post("/api/parent/sheets", headers=p1, json={"student_id": asha, "subject": "Physics"})
    assert r.status_code == 429 and "tomorrow" in r.json()["detail"]
    ov = client.get("/api/parent/overview", headers=p1).json()
    assert ov["children"][0]["used_today"] == 2 and all(s["status"] == "ready" for s in ov["sheets"])

    # Failed attempts don't count towards the limit.
    with SessionLocal() as db:
        db.get(ParentSheet, first["id"]).status = "failed"
        db.commit()
    assert client.post("/api/parent/sheets", headers=p1, json={"student_id": asha, "subject": "Physics"}).status_code == 200
    _drain()

    # Emailing the login details: on create (when asked), and when the admin sets a new password.
    before = _outbox()
    r = client.post("/api/users", json={"email": "meena.parent@example.com", "name": "Meena's Parent", "role": "parent",
                                        "password": "welcome-pass-9", "student_ids": [students["P203"]], "notify": True,
                                        "login_url": "https://school.example.org/login"})
    assert r.status_code == 200 and r.json()["email_sent"] is True, r.text
    (new,) = _outbox() - before
    subject, body = _read_eml(new)
    assert "Your login for practice sheets" in subject
    for expected in ("meena.parent@example.com", "welcome-pass-9", "https://school.example.org/login", "Meena (Class 2-B)"):
        assert expected in body, expected
    mid = r.json()["id"]
    before = _outbox()
    patch = {"email": "meena.parent@example.com", "name": "Meena's Parent", "role": "parent", "student_ids": [students["P203"]],
             "notify": True}
    assert "email_sent" not in client.patch(f"/api/users/{mid}", json=patch).json()  # no new password: nothing to send
    r = client.patch(f"/api/users/{mid}", json={**patch, "password": "changed-pass-7"})
    assert r.json()["email_sent"] is True
    (new,) = _outbox() - before
    subject, body = _read_eml(new)
    assert "new password" in subject.lower() and "changed-pass-7" in body
    assert _login(client, "meena.parent@example.com", "changed-pass-7")
    # Without "notify" nothing is sent, and passwords never reach the activity log.
    before = _outbox()
    client.post("/api/users", json={"email": "quiet.parent@example.com", "name": "Quiet", "role": "parent",
                                    "password": "quiet-pass-11", "student_ids": [asha]})
    assert _outbox() == before
    summaries = " ".join(a["summary"] + str(a["details"]) for a in client.get("/api/audit?limit=500").json())
    assert "Emailed login details to meena.parent@example.com" in summaries
    assert "welcome-pass-9" not in summaries and "changed-pass-7" not in summaries

    # A disabled parent can't sign in.
    pid = next(u["id"] for u in client.get("/api/users").json() if u["email"] == "ravi.parent@example.com")
    client.patch(f"/api/users/{pid}", json={"email": "ravi.parent@example.com", "name": "Ravi's Parent", "role": "parent",
                                            "student_ids": [ravi], "active": False})
    assert client.get("/api/parent/overview", headers=p2).status_code == 401
