import os
import shutil
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="psa-test-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{(_tmp / 'test.db').as_posix()}",
    "DATA_DIR": str(_tmp / "data"),
    "LLM_PROVIDER": "offline",
    "EMAIL_PROVIDER": "outbox",
    "WHATSAPP_PROVIDER": "outbox",
    "WORKER_ENABLED": "false",
    "ADMIN_EMAIL": "admin@test.school",
    "ADMIN_PASSWORD": "test-password",
    "JWT_SECRET": "test-secret-test-secret-test-secret",
    "FRONTEND_DIST": str(_tmp / "no-dist"),
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"email": "admin@test.school", "password": "test-password"})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c
    shutil.rmtree(_tmp, ignore_errors=True)


def make_pdf(paragraphs: list[str]) -> bytes:
    path = _tmp / f"src_{abs(hash(paragraphs[0]))}.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for para in paragraphs:
        words, line = para.split(), ""
        for w in words:
            if len(line) + len(w) > 90:
                c.drawString(40, y, line)
                y -= 14
                line = ""
            line += w + " "
        c.drawString(40, y, line)
        y -= 28
        if y < 80:
            c.showPage()
            y = 800
    c.save()
    return path.read_bytes()
