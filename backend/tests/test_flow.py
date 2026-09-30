"""End to end: configure a class, trigger two days before the exam, generate within the exam
syllabus, approve, share by email, and prove nothing is generated or sent twice."""
from datetime import timedelta

from app.db import SessionLocal
from app.models import Delivery, Job, Worksheet
from app.orchestrator import daily_check, worker_tick
from app.services.common import local_today

from .conftest import make_pdf

CH1 = ["Chapter 1 Number Systems", "A rational number is a number that can be written in the form p over q where p and q "
       "are integers and q is not zero.", "Every rational number has a decimal expansion that either terminates or "
       "repeats. Irrational numbers have decimal expansions that neither terminate nor repeat.",
       "The square root of two is an irrational number. Real numbers include both rational and irrational numbers.",
       "Between any two rational numbers there are infinitely many rational numbers on the number line."]
CH2 = ["Chapter 2 Polynomials", "A polynomial in one variable x is an algebraic expression with whole number powers of x.",
       "The degree of a polynomial is the highest power of the variable in the polynomial expression.",
       "A polynomial of degree one is called linear, degree two is quadratic and degree three is cubic.",
       "The remainder theorem states that dividing a polynomial by x minus a leaves the remainder p of a.",
       "The factor theorem states that x minus a is a factor when p of a equals zero for the polynomial."]
CH6 = ["Chapter 6 Lines and Angles", "When two lines intersect, vertically opposite angles are always equal in measure.",
       "If a transversal intersects two parallel lines then each pair of alternate interior angles is equal.",
       "The sum of all interior angles of a triangle is one hundred and eighty degrees in Euclidean geometry."]


def test_full_flow(client):
    today = local_today(SessionLocal())
    exam_day = today + timedelta(days=2)
    later = today + timedelta(days=6)

    r = client.post("/api/classes", json={"name": "Class 9", "sections": "A, B"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    # Activation is blocked until everything is configured.
    assert client.post(f"/api/classes/{cid}/automation", json={"action": "activate"}).status_code == 409

    ds = (f"Class,Section,Subject,Exam Date,Exam Time\n9,A,Mathematics,{exam_day:%d-%b-%Y},09:00\n"
          f"9,\"A, B\",Science,{later:%d-%b-%Y},09:00\n").encode()
    r = client.post(f"/api/classes/{cid}/datesheet", files={"file": ("Class_9_DateSheet.csv", ds, "text/csv")})
    assert r.status_code == 200 and len(r.json()["pending"]["rows"]) == 2
    assert r.json()["exams"] == []  # preview only
    r = client.post(f"/api/classes/{cid}/datesheet/confirm")
    assert r.status_code == 200 and len(r.json()["exams"]) == 2

    # Exam syllabus: Mathematics covers chapters 1 and 2 only.
    syl = b"Half yearly examination syllabus\nMathematics: Chapter 1 Number Systems, Chapter 2 Polynomials\nScience: Chapter 1 Motion"
    r = client.post(f"/api/classes/{cid}/syllabus", files={"file": ("syllabus.txt", syl, "text/plain")})
    assert r.status_code == 200, r.text
    assert {e["subject"]: e["chapters"] for e in r.json()["pending"]["entries"]}["Mathematics"] == [1, 2]
    assert client.post(f"/api/classes/{cid}/syllabus/confirm").status_code == 200

    subj = client.post(f"/api/classes/{cid}/subjects", json={"name": "Mathematics"}).json()
    files = [("files", ("Chapter-01.pdf", make_pdf(CH1), "application/pdf")),
             ("files", ("Chapter-02.pdf", make_pdf(CH2), "application/pdf")),
             ("files", ("Chapter-06.pdf", make_pdf(CH6), "application/pdf"))]
    r = client.post(f"/api/subjects/{subj['id']}/documents", files=files)
    assert r.status_code == 200, r.text
    assert {d["chapter"] for d in r.json()["documents"]} == {"Chapter 1", "Chapter 2", "Chapter 6"}
    sci = client.post(f"/api/classes/{cid}/subjects", json={"name": "Science"}).json()
    client.post(f"/api/subjects/{sci['id']}/documents",
                files=[("files", ("Chapter-01-Motion.pdf", make_pdf(["Motion is a change in position over time."] * 3), "application/pdf"))])

    students = (b"Student ID,Name,Class,Section,Email,WhatsApp\nST001,Rahul Sharma,9,A,rahul@example.com,9876543210\n"
                b"ST002,Priya Singh,9,A,priya@example.com,9876543211\nST003,Aman Verma,9,A,aman@exmaple,\n"
                b"ST004,Neha Gupta,9,B,neha@example.com,9876543213\n")
    r = client.post(f"/api/classes/{cid}/students/upload", files={"file": ("students.csv", students, "text/csv")})
    assert r.status_code == 200 and r.json()["import"]["added"] == 4
    assert r.json()["students"][0]["email"] == "ra***@example.com"  # masked in lists

    r = client.post(f"/api/classes/{cid}/automation", json={"action": "activate"})
    assert r.status_code == 200, r.text

    # Two-day trigger, idempotent.
    with SessionLocal() as db:
        assert daily_check(db, today=today - timedelta(days=1))["created"] == 0
        assert daily_check(db, today=today)["created"] == 1
        assert daily_check(db, today=today)["created"] == 0
        worker_tick(db)
        ws = db.query(Worksheet).filter(Worksheet.class_id == cid).one()
        assert ws.status == "awaiting-approval", [c for c in ws.validation["checks"] if c["status"] == "failed"]
        cited = {s["filename"] for s in ws.sources}
        assert "Chapter-06.pdf" not in cited  # outside the exam syllabus: never used
        assert cited <= {"Chapter-01.pdf", "Chapter-02.pdf"}
        assert sum(len(s["questions"]) for s in ws.content["sections"]) == 20
        ws_id = ws.id

    detail = client.get(f"/api/worksheets/{ws_id}").json()
    assert detail["recipients"] == 3  # Mathematics is section A only
    assert {c["id"]: c["status"] for c in detail["validation"]["checks"]}["scope"] == "passed"
    assert client.get(f"/api/worksheets/{ws_id}/pdf").status_code == 200

    # Editing in a question that cites an out-of-scope chunk fails validation.
    content = detail["content"]
    with SessionLocal() as db:
        from app.models import Chunk, Document
        ch6_chunk = db.query(Chunk).join(Document).filter(Document.filename == "Chapter-06.pdf").first()
    content["sections"][1]["questions"][0]["source_ids"] = [f"C{ch6_chunk.id}"]
    r = client.put(f"/api/worksheets/{ws_id}/content", json={"content": content})
    assert r.json()["status"] == "validation-failed"
    assert client.post(f"/api/worksheets/{ws_id}/approve", json={}).status_code == 409

    # Regenerate → v2, approve, share.
    assert client.post(f"/api/worksheets/{ws_id}/regenerate", json={"reason": "Q B-1 out of scope"}).status_code == 200
    with SessionLocal() as db:
        worker_tick(db)
        v2 = db.query(Worksheet).filter(Worksheet.class_id == cid, Worksheet.version == 2).one()
        assert v2.status == "awaiting-approval"
        assert db.get(Worksheet, ws_id).status == "superseded"
        v2_id = v2.id
    r = client.post(f"/api/worksheets/{v2_id}/approve", json={})
    assert r.status_code == 200 and r.json()["status"] == "released"
    with SessionLocal() as db:
        worker_tick(db)
        rows = db.query(Delivery).filter(Delivery.worksheet_id == v2_id).all()
        by = {(d.channel, d.status) for d in rows}
        assert len(rows) == 3  # Phase 1: email only
        assert sum(1 for d in rows if d.status == "sent") == 2
        assert ("email", "failed") in by  # invalid address, others unaffected
        share = db.query(Job).filter(Job.class_id == cid, Job.type == "SHARE_WORKSHEET").one()
        assert share.status == "completed"
        # Re-running the share cannot send twice.
        from app.agents.sharing_agent import share_worksheet
        share_worksheet(db, db.get(Worksheet, v2_id))
        assert db.query(Delivery).filter(Delivery.worksheet_id == v2_id).count() == 3

    mon = client.get(f"/api/worksheets/{v2_id}/deliveries").json()
    assert mon["summary"]["email"] == {"sent": 2, "failed": 1}
    assert client.get("/api/dashboard").json()["kpis"]["email_sent"] >= 2  # other tests' classes also send today
    assert client.get("/api/audit").status_code == 200


def test_schedule_change_cancels_pending(client):
    classes = client.get("/api/classes").json()
    cid = next(c["id"] for c in classes if c["name"] == "Class 9")
    with SessionLocal() as db:
        today = local_today(db)
    r = client.get(f"/api/classes/{cid}").json()
    sci = next(e for e in r["datesheet"]["exams"] if e["subject"] == "Science")
    # Science moves to two days from now → triggers today; then moves again → pending job cancelled.
    client.patch(f"/api/exams/{sci['id']}", json={"exam_date": (today + timedelta(days=2)).isoformat()})
    with SessionLocal() as db:
        assert daily_check(db, today=today)["created"] == 1
    r = client.get(f"/api/classes/{cid}").json()
    sci = next(e for e in r["datesheet"]["exams"] if e["subject"] == "Science")
    client.patch(f"/api/exams/{sci['id']}", json={"exam_date": (today + timedelta(days=9)).isoformat()})
    with SessionLocal() as db:
        job = db.query(Job).filter(Job.class_id == cid, Job.subject_name == "Science").one()
        assert job.status == "cancelled"
