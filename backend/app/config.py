"""Runtime configuration. Every secret comes from the environment or backend/.env, never from source."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # Storage
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'psa.db').as_posix()}"
    data_dir: Path = BACKEND_DIR / "data"

    # Auth
    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_hours: int = 12
    admin_email: str = "admin@school.edu.in"
    admin_password: str = "changeme"

    # Institution defaults (editable later in the UI; these only seed the settings table)
    institution_name: str = "Practice Sheet Agent"
    timezone: str = "Asia/Kolkata"
    scheduler_time: str = "06:00"
    lead_days: int = 2

    # Worker
    worker_enabled: bool = True
    worker_poll_seconds: int = 10
    job_max_attempts: int = 3
    delivery_max_attempts: int = 3

    # LLM. provider = "anthropic" (Claude) | "gemini" (Google) | "offline". "offline" builds questions directly
    # from the retrieved PDF text without a model, for local development and tests.
    llm_provider: str = "anthropic"
    # Gemini (LLM_PROVIDER=gemini). LLM_EFFORT, LLM_CONTEXT_CHARS and the batch setting apply to both providers.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    # Tried in order when the main model is overloaded (503) or rate-limited (429).
    gemini_fallback_models: str = "gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash"
    # If every model is overloaded, wait and try the whole list again (wait grows each round).
    gemini_retry_rounds: int = 3
    gemini_retry_wait_seconds: int = 20
    # Cost-optimized defaults: Sonnet 5 at medium effort writes good school worksheets at a fraction of Opus'
    # price. Set LLM_MODEL=claude-opus-5 and LLM_EFFORT=high for the highest quality.
    llm_model: str = "claude-sonnet-5"
    llm_effort: str = "medium"
    llm_server_fallbacks: bool = True
    # How much textbook text is sent per worksheet (characters). Less text = lower cost; the most relevant
    # in-syllabus passages are chosen first.
    llm_context_chars: int = 40_000
    # Scheduled worksheets use the Batch API (50% cheaper, results within minutes to hours). If a batch has not
    # finished after this many hours, the worksheet is generated directly instead.
    llm_batch_timeout_hours: int = 6

    # Email (Phase 1). provider = "outbox" writes .eml files to data/outbox; "smtp" sends.
    email_provider: str = "outbox"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_from: str = "Practice Sheets <no-reply@school.edu.in>"

    # WhatsApp (Phase 2). provider = "outbox" | "cloud_api" (WhatsApp Business Platform).
    whatsapp_provider: str = "outbox"
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_api_version: str = "v21.0"
    whatsapp_default_country_code: str = "91"
    whatsapp_template_name: str = ""
    whatsapp_template_language: str = "en"
    whatsapp_webhook_verify_token: str = ""

    # Frontend build served by FastAPI in production
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def worksheets_dir(self) -> Path:
        return self.data_dir / "worksheets"

    @property
    def outbox_dir(self) -> Path:
        return self.data_dir / "outbox"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    for d in (s.data_dir, s.uploads_dir, s.worksheets_dir, s.outbox_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s
