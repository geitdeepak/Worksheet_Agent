import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .api import admin, classes, parent, worksheets
from .config import get_settings
from .db import Base, SessionLocal, engine
from .models import User
from .security import hash_password
from .worker import worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s · %(message)s")
log = logging.getLogger("psa")


def upgrade_schema() -> None:
    """Add columns introduced by newer versions to an existing database (new tables come from create_all).
    Only additive changes: nothing is dropped or rewritten, so existing data is safe."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl_type = col.type.compile(dialect=engine.dialect)
                default = ""
                if not col.nullable and col.default is not None and not callable(col.default.arg):
                    arg = col.default.arg
                    default = f" DEFAULT {int(arg) if isinstance(arg, bool) else repr(arg)}"
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl_type}{default}'))
                log.info("Database upgraded: added %s.%s", table.name, col.name)


def init_db() -> None:
    Base.metadata.create_all(engine)
    upgrade_schema()
    s = get_settings()
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is None:
            db.add(User(email=s.admin_email, name="Administrator", role="admin", password_hash=hash_password(s.admin_password)))
            db.commit()
            log.info("Created the first administrator: %s", s.admin_email)
            if s.admin_password == "changeme":
                log.warning("The administrator password is the default. Set ADMIN_PASSWORD or change it after signing in.")
    if s.jwt_secret == "dev-only-change-me":
        log.warning("JWT_SECRET is the development default. Set a long random value in production.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    s = get_settings()
    log.info("LLM provider: %s%s · email: %s · WhatsApp: %s", s.llm_provider,
             f" ({s.llm_model})" if s.llm_provider == "anthropic" else "", s.email_provider, s.whatsapp_provider)
    if s.worker_enabled:
        worker.start()
    yield
    worker.stop()


app = FastAPI(title="Practice Sheet Agent", lifespan=lifespan)
app.include_router(admin.router)
app.include_router(classes.router)
app.include_router(worksheets.router)
app.include_router(parent.router)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server. The error was logged."})


@app.get("/api/health")
def health():
    return {"ok": True}


# Serve the built admin UI (frontend/dist) with client-side routing fallback.
_dist = get_settings().frontend_dist
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.middleware("http")
    async def asset_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/assets/"):  # hashed file names: safe to cache for a year
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = _dist / path
        if path and f.is_file() and _dist in f.resolve().parents:
            return FileResponse(f)
        # index.html must never be cached, or browsers keep showing an old version of the app after an update.
        # (The JS/CSS files it points to have content hashes in their names, so they can be cached safely.)
        return FileResponse(_dist / "index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
