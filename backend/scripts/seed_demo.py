"""Seed a demo class through the real API so every upload goes through the same parsing and checks.

    cd backend
    .venv\\Scripts\\python -m scripts.seed_demo

Creates Class 9 (sections A, B) with a date sheet whose Mathematics exam is two days from today,
an exam syllabus limited to chapters 1, 2 and 7, chapter PDFs (including an out-of-scope
chapter 6), and five students — one with an invalid email and one without WhatsApp."""
import io
import os
import sys
from datetime import timedelta

os.environ.setdefault("WORKER_ENABLED", "false")

from fastapi.testclient import TestClient  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.common import local_today  # noqa: E402

CHAPTERS = {
    "Chapter-01.pdf": ("Chapter 1 · Number Systems", [
        "A number r is called a rational number if it can be written in the form p/q, where p and q are integers and q is not equal to zero.",
        "Every rational number has a decimal expansion that either terminates or is non-terminating and recurring. For example, 1/4 = 0.25 terminates while 1/3 = 0.333... recurs.",
        "A number whose decimal expansion is non-terminating and non-recurring is irrational. The square root of 2, the square root of 3 and pi are irrational numbers.",
        "The collection of all rational and irrational numbers together is called the set of real numbers. Every real number corresponds to a unique point on the number line.",
        "Between any two given rational numbers there are infinitely many rational numbers. To find a rational number between a and b, take their average (a + b)/2.",
        "Laws of exponents for real numbers: a^m × a^n = a^(m+n), (a^m)^n = a^(mn), a^m / a^n = a^(m−n) and a^m × b^m = (ab)^m, where a and b are positive real numbers.",
        "To rationalise the denominator of 1/(a + √b), multiply the numerator and the denominator by a − √b, using the identity (a + √b)(a − √b) = a² − b."]),
    "Chapter-02.pdf": ("Chapter 2 · Polynomials", [
        "A polynomial in one variable x is an algebraic expression of the form a_n x^n + ... + a_1 x + a_0, where the coefficients are real numbers and the powers of x are whole numbers.",
        "The highest power of the variable in a polynomial is called its degree. A polynomial of degree one is linear, of degree two is quadratic and of degree three is cubic.",
        "A real number a is a zero of the polynomial p(x) if p(a) = 0. A linear polynomial ax + b, with a not zero, has exactly one zero, namely −b/a.",
        "Remainder Theorem: if p(x) is a polynomial of degree one or more and it is divided by the linear polynomial x − a, then the remainder is p(a).",
        "Factor Theorem: x − a is a factor of the polynomial p(x) if p(a) = 0, and conversely if x − a is a factor of p(x) then p(a) = 0.",
        "Algebraic identities: (x + y)² = x² + 2xy + y², (x − y)² = x² − 2xy + y², and x² − y² = (x + y)(x − y). They help factorise quadratic polynomials.",
        "A quadratic polynomial x² + bx + c can be factorised by splitting the middle term: find two numbers whose sum is b and whose product is c."]),
    "Chapter-06.pdf": ("Chapter 6 · Lines and Angles", [
        "If two lines intersect each other, then the vertically opposite angles are equal.",
        "If a transversal intersects two parallel lines, then each pair of corresponding angles is equal and each pair of alternate interior angles is equal.",
        "The sum of the angles of a triangle is 180 degrees. An exterior angle of a triangle equals the sum of the two interior opposite angles."]),
    "Chapter-07.pdf": ("Chapter 7 · Triangles", [
        "Two figures are congruent if they are of the same shape and the same size. Congruent triangles have corresponding sides and corresponding angles equal.",
        "SAS congruence rule: two triangles are congruent if two sides and the included angle of one triangle are equal to two sides and the included angle of the other.",
        "ASA congruence rule: two triangles are congruent if two angles and the included side of one are equal to two angles and the included side of the other.",
        "Angles opposite to equal sides of an isosceles triangle are equal. Conversely, the sides opposite to equal angles of a triangle are equal.",
        "SSS congruence rule: if three sides of one triangle are equal to the three sides of another triangle, then the two triangles are congruent.",
        "RHS congruence rule: in two right triangles, if the hypotenuse and one side of one triangle are equal to the hypotenuse and one side of the other, the triangles are congruent."]),
}
SCIENCE = ("Chapter 1 · Motion", [
    "An object is said to be in motion when its position changes with time. Distance is the total path length covered, while displacement is the shortest distance from the initial to the final position.",
    "Speed is the distance travelled per unit time. Velocity is speed in a given direction. The SI unit of both speed and velocity is metre per second.",
    "Acceleration is the rate of change of velocity with time: a = (v − u)/t. Its SI unit is metre per second squared.",
    "For uniformly accelerated motion: v = u + at, s = ut + ½at², and v² − u² = 2as, where u is initial velocity and s is displacement.",
    "When an object moves in a circular path with uniform speed, its motion is called uniform circular motion. The velocity changes because the direction changes."])


def pdf(title: str, paras: list[str]) -> bytes:
    buf = io.BytesIO()
    st = getSampleStyleSheet()
    story = [Paragraph(title, st["Title"])]
    for p in paras:
        story += [Paragraph(p, st["BodyText"]), Spacer(1, 8)]
    SimpleDocTemplate(buf, pagesize=A4).build(story)
    return buf.getvalue()


def check(r, what):
    if r.status_code >= 400:
        sys.exit(f"{what} failed: {r.status_code} {r.text}")
    return r.json()


def main():
    s = get_settings()
    with TestClient(app) as c:
        tok = check(c.post("/api/auth/login", json={"email": s.admin_email, "password": s.admin_password}), "Login")["token"]
        c.headers["Authorization"] = f"Bearer {tok}"
        if any(x["name"] == "Class 9" for x in check(c.get("/api/classes"), "List classes")):
            sys.exit("Class 9 already exists. Delete backend/data to start over.")
        with SessionLocal() as db:
            today = local_today(db)
        d = lambda n: (today + timedelta(days=n)).strftime("%d-%b-%Y")  # noqa: E731

        cid = check(c.post("/api/classes", json={"name": "Class 9", "sections": "A, B"}), "Create class")["id"]
        ds = (f"Class,Section,Subject,Exam Date,Exam Time,Exam ID\n"
              f"9,A,Mathematics,{d(2)},09:00 AM,EX9-MATH-001\n9,\"A, B\",Science,{d(5)},09:00 AM,EX9-SCI-001\n").encode()
        check(c.post(f"/api/classes/{cid}/datesheet", files={"file": ("Class_9_DateSheet.csv", ds, "text/csv")}), "Date sheet")
        check(c.post(f"/api/classes/{cid}/datesheet/confirm"), "Confirm date sheet")

        syllabus = (b"Half-yearly examination 2026-27 \xe2\x80\x94 Class 9 syllabus\n\n"
                    b"Mathematics: Chapter 1 Number Systems, Chapter 2 Polynomials, Chapter 7 Triangles\n"
                    b"(Chapter 6 Lines and Angles is NOT included)\n\n"
                    b"Science: Chapter 1 Motion\n")
        check(c.post(f"/api/classes/{cid}/syllabus", files={"file": ("Class_9_Syllabus.txt", syllabus, "text/plain")}), "Syllabus")
        check(c.post(f"/api/classes/{cid}/syllabus/confirm"), "Confirm syllabus")

        maths = check(c.post(f"/api/classes/{cid}/subjects", json={"name": "Mathematics"}), "Subject")
        check(c.post(f"/api/subjects/{maths['id']}/documents",
                     files=[("files", (n, pdf(t, p), "application/pdf")) for n, (t, p) in CHAPTERS.items()]), "Maths PDFs")
        sci = check(c.post(f"/api/classes/{cid}/subjects", json={"name": "Science"}), "Subject")
        check(c.post(f"/api/subjects/{sci['id']}/documents",
                     files=[("files", ("Chapter-01-Motion.pdf", pdf(*SCIENCE), "application/pdf"))]), "Science PDF")

        students = (b"Student ID,Name,Class,Section,Email,WhatsApp\n"
                    b"ST001,Rahul Sharma,9,A,rahul@example.com,9876500001\nST002,Priya Singh,9,A,priya@example.com,9876500002\n"
                    b"ST003,Aman Verma,9,A,aman@exmaple.con,\nST004,Neha Gupta,9,B,neha@example.com,9876500004\n"
                    b"ST005,Kabir Khan,9,B,kabir@example.com,9876500005\n")
        check(c.post(f"/api/classes/{cid}/students/upload", files={"file": ("students.csv", students, "text/csv")}), "Students")
        check(c.post(f"/api/classes/{cid}/automation", json={"action": "activate"}), "Activate")
    print(f"Seeded Class 9. Mathematics exam {d(2)} triggers today; Science {d(5)}.")
    print("Open the dashboard and click 'Run check now' to generate the Mathematics worksheet.")


if __name__ == "__main__":
    main()
