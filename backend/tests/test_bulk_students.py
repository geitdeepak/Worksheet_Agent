"""Bulk student upload: preview saves nothing, confirm applies exactly the preview, and one school-wide
file is routed to the right classes by its Class column."""
import io

from openpyxl import load_workbook


def _class(client, name, sections):
    existing = {c["name"]: c["id"] for c in client.get("/api/classes").json()}
    if name in existing:
        return existing[name]
    return client.post("/api/classes", json={"name": name, "sections": sections}).json()["id"]


def test_class_upload_preview_then_confirm(client):
    cid = _class(client, "Class 7", "A, B")
    csv = (b"Student ID,Name,Class,Section,Email,WhatsApp\nS701,Asha Rao,7,A,asha@example.com,9876500701\n"
           b"S702,Dev Nair,7,B,dev@example,\nS703,Bad Section,7,Z,x@example.com,\n")
    files = {"file": ("s.csv", csv, "text/csv")}
    r = client.post(f"/api/classes/{cid}/students/upload", files=files, data={"dry_run": "true"}).json()
    assert r["preview"] is True
    imp = r["import"]
    assert (imp["new"], imp["errors"], imp["warnings"]) == (2, 1, 1)  # bad section skipped, bad email warned
    assert client.get(f"/api/classes/{cid}/students").json()["students"] == []  # nothing saved

    r = client.post(f"/api/classes/{cid}/students/upload", files=files).json()
    assert r["import"]["added"] == 2 and len(r["students"]) == 2

    # Re-upload with a change and replace mode: one updated, one deactivated.
    csv2 = b"Student ID,Name,Class,Section,Email,WhatsApp\nS701,Asha Rao,7,A,asha.rao@example.com,9876500701\n"
    r = client.post(f"/api/classes/{cid}/students/upload", files={"file": ("s.csv", csv2, "text/csv")},
                    data={"replace": "true", "dry_run": "true"}).json()["import"]
    assert (r["new"], r["updated"], r["deactivated"]) == (0, 1, 1)


def test_school_wide_upload_routes_by_class(client):
    c6 = _class(client, "Class 6", "A")
    c8 = _class(client, "Class 8", "A, B")
    csv = (b"Student ID,Name,Class,Section,Email,WhatsApp\n"
           b"EXAMPLE-1,Sample,6,A,a@example.com,\n"
           b"S601,Isha Jain,6,A,isha@example.com,9876500601\n"
           b"S801,Om Patel,Class 8,B,om@example.com,9876500801\n"
           b"S802,Ria Das,VIII,A,ria@example.com,\n"
           b"S1101,No Class,11,A,n@example.com,\n")
    files = {"file": ("school.csv", csv, "text/csv")}
    prev = client.post("/api/students/upload", files=files, data={"dry_run": "true"}).json()["import"]
    assert prev["new"] == 3 and prev["errors"] == 1
    assert "no Class 11 workspace" in prev["issues"][0]["message"]
    assert {c["name"]: c["new"] for c in prev["classes"]} == {"Class 6": 1, "Class 8": 2}

    client.post("/api/students/upload", files=files)
    s6 = client.get(f"/api/classes/{c6}/students").json()["students"]
    s8 = client.get(f"/api/classes/{c8}/students").json()["students"]
    assert [s["student_code"] for s in s6] == ["S601"]
    assert sorted(s["student_code"] for s in s8) == ["S801", "S802"]


def test_template_downloads_and_round_trips(client):
    r = client.get("/api/students/template.xlsx")
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    assert [c.value for c in wb["Students"][1]] == ["Student ID", "Name", "Class", "Section", "Email", "WhatsApp", "Active"]
    # The untouched template imports cleanly: its example row is ignored.
    cid = _class(client, "Class 5", "A, B")
    prev = client.post(f"/api/classes/{cid}/students/upload", files={"file": ("t.xlsx", r.content, "application/octet-stream")},
                       data={"dry_run": "true"}).json()["import"]
    assert prev["new"] == 0 and prev["errors"] == 0
