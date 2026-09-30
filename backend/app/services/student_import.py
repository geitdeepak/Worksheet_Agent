"""Bulk student import: one class, or the whole school in one file (rows routed by their Class column).

The same plan is used for the preview and for the real import, so the admin confirms exactly
what will change."""
from ..models import SchoolClass, Student
from .common import mask_email, mask_phone
from .tabular import grade_of, parse_student_rows, read_table
from .templates import build_xlsx

FIELDS = ("name", "section", "email", "whatsapp", "active")


def plan_class(c: SchoolClass, rows: list[dict], replace: bool) -> list[dict]:
    """Compare validated rows with the class's current students."""
    existing = {s.student_code: s for s in c.students}
    plan = []
    for r in rows:
        s = existing.get(r["student_code"])
        if s is None:
            change = "new"
        else:
            changed = [f for f in FIELDS if getattr(s, f) != r[f]]
            change = "updated" if changed else "unchanged"
        plan.append({**r, "class_id": c.id, "class": c.name, "change": change})
    if replace:
        codes = {r["student_code"] for r in rows}
        for code, s in existing.items():
            if code not in codes and s.active:
                plan.append({"student_code": code, "name": s.name, "section": s.section, "email": s.email,
                             "whatsapp": s.whatsapp, "active": False, "class_id": c.id, "class": c.name,
                             "change": "deactivated"})
    return plan


def apply_plan(db, c: SchoolClass, plan: list[dict]) -> None:
    existing = {s.student_code: s for s in c.students}
    for p in plan:
        if p["change"] == "unchanged":
            continue
        s = existing.get(p["student_code"])
        if p["change"] == "new":
            c.students.append(Student(student_code=p["student_code"], **{f: p[f] for f in FIELDS}))
        elif p["change"] == "updated":
            for f in FIELDS:
                setattr(s, f, p[f])
        elif p["change"] == "deactivated":
            s.active = False


def summarize(plan: list[dict], issues: list[dict]) -> dict:
    counts = {k: sum(1 for p in plan if p["change"] == k) for k in ("new", "updated", "unchanged", "deactivated")}
    return {**counts, "errors": sum(1 for i in issues if not i.get("warning")),
            "warnings": sum(1 for i in issues if i.get("warning")), "issues": issues,
            "rows": [{"student_code": p["student_code"], "name": p["name"], "section": p["section"], "class": p["class"],
                      "email": mask_email(p["email"]), "whatsapp": mask_phone(p["whatsapp"]), "active": p["active"],
                      "change": p["change"]} for p in plan if p["change"] != "unchanged"]}


def split_by_class(rows: list[dict], classes: list[SchoolClass]) -> tuple[dict[int, list[dict]], list[dict]]:
    """Route rows of a school-wide file to classes by the Class column (+ Section when two classes share a grade)."""
    by_grade: dict[str, list[SchoolClass]] = {}
    for c in classes:
        by_grade.setdefault(str(c.grade), []).append(c)
    routed: dict[int, list[dict]] = {}
    issues = []
    for r in rows:
        code = str(r.get("student_code") or "").strip().upper()
        if code == "EXAMPLE" or code.startswith("EXAMPLE-"):
            continue
        raw = r.get("class")
        if raw in (None, ""):
            issues.append({"row": r["_row"], "message": f"Row {r['_row']} · the Class column is empty"})
            continue
        g = grade_of(raw)
        matches = by_grade.get(g, [])
        if len(matches) > 1:  # e.g. separate 'Class 9 Science' and 'Class 9 Commerce' workspaces
            sec = str(r.get("section") or "").strip().upper()
            matches = [c for c in matches if sec in c.section_list()] or matches
        if not matches:
            issues.append({"row": r["_row"], "message": f"Row {r['_row']} · there is no Class {g} workspace. Create it first."})
            continue
        routed.setdefault(matches[0].id, []).append(r)
    return routed, issues


def build_school_plan(filename: str, data: bytes, classes: list[SchoolClass], replace: bool,
                      default_cc: str) -> tuple[dict[int, list[dict]], list[dict], list[dict]]:
    """Returns (plan per class id, all plan rows, issues)."""
    rows = read_table(filename, data)
    routed, issues = split_by_class(rows, classes)
    cls = {c.id: c for c in classes}
    per_class, all_rows = {}, []
    for cid, crs in routed.items():
        c = cls[cid]
        students, cls_issues = parse_student_rows(crs, c.grade, c.section_list(), default_cc)
        issues += [{**i, "message": i["message"].replace("Row ", f"{c.name} · Row ", 1)} for i in cls_issues]
        per_class[cid] = plan_class(c, students, replace)
        all_rows += per_class[cid]
    issues.sort(key=lambda i: i["row"])
    return per_class, all_rows, issues


def template_xlsx(school_class: SchoolClass | None = None) -> bytes:
    grade = school_class.grade if school_class else "9"
    sec = school_class.section_list()[0] if school_class else "A"
    return build_xlsx(
        "Students", ["Student ID", "Name", "Class", "Section", "Email", "WhatsApp", "Active"],
        [["EXAMPLE-1", "Rahul Sharma (example row, ignored)", grade, sec, "rahul@example.com", "9876543210", "Yes"]],
        ["How to fill the student list", "",
         "• One row per student. Keep the header row as it is.",
         "• Student ID: the admission or roll number. Uploading the same ID again updates that student.",
         "• Class: the class number (9, 10, IX…). One file can hold students of every class.",
         "• Section: one of the class's sections, e.g. A or B.",
         "• Email: the worksheet is emailed here.",
         "• WhatsApp: a 10-digit mobile number (Phase 2). Leave blank if not available.",
         "• Active: Yes or No. Blank means Yes. Students marked No receive nothing.",
         "• The grey EXAMPLE row is ignored — you can leave it or delete it.",
         "", "After uploading you will see exactly who is added or changed, and confirm it."],
        [14, 34, 9, 10, 32, 18, 9], text_cols=(1, 6), example_rows=1, lists={7: ["Yes", "No"]})
