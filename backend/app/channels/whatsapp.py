"""Phase 2 delivery channel: WhatsApp Business Platform (Cloud API), or an outbox for development.

Business-initiated WhatsApp messages outside a 24-hour customer window must use an approved
template. Set WHATSAPP_TEMPLATE_NAME to a template with a DOCUMENT header and three body
parameters (subject, class, exam date). Without a template, a plain document message is sent,
which only reaches students who messaged the school number in the last 24 hours."""
import json
import uuid
from pathlib import Path

import httpx

from ..config import get_settings
from . import PermanentError, TransientError


def _graph(path: str) -> str:
    s = get_settings()
    return f"https://graph.facebook.com/{s.whatsapp_api_version}/{path}"


def send_document(to_digits: str, pdf: Path, caption: str, template_params: list[str]) -> tuple[str, str]:
    s = get_settings()
    if s.whatsapp_provider == "outbox":
        path = s.outbox_dir / "whatsapp" / f"{uuid.uuid4().hex}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"to": to_digits, "document": pdf.name, "caption": caption}, indent=2), encoding="utf-8")
        return f"outbox-{path.stem}", f"written to {path.name}"

    if s.whatsapp_provider != "cloud_api" or not (s.whatsapp_phone_number_id and s.whatsapp_access_token):
        raise PermanentError("WhatsApp is not configured. Set WHATSAPP_PROVIDER=cloud_api, "
                             "WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN.")
    headers = {"Authorization": f"Bearer {s.whatsapp_access_token}"}
    try:
        with httpx.Client(timeout=60) as client:
            up = client.post(_graph(f"{s.whatsapp_phone_number_id}/media"), headers=headers,
                             data={"messaging_product": "whatsapp", "type": "application/pdf"},
                             files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")})
            _raise_for(up)
            media_id = up.json()["id"]
            document = {"id": media_id, "filename": pdf.name}
            if s.whatsapp_template_name:
                body = {"messaging_product": "whatsapp", "to": to_digits, "type": "template", "template": {
                    "name": s.whatsapp_template_name, "language": {"code": s.whatsapp_template_language},
                    "components": [
                        {"type": "header", "parameters": [{"type": "document", "document": document}]},
                        {"type": "body", "parameters": [{"type": "text", "text": p} for p in template_params]},
                    ]}}
            else:
                body = {"messaging_product": "whatsapp", "to": to_digits, "type": "document",
                        "document": {**document, "caption": caption}}
            r = client.post(_graph(f"{s.whatsapp_phone_number_id}/messages"), headers=headers, json=body)
            _raise_for(r)
            data = r.json()
            return data["messages"][0]["id"], json.dumps(data)[:500]
    except httpx.TransportError as e:
        raise TransientError(f"WhatsApp API unreachable: {e}")


def _raise_for(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    try:
        err = r.json().get("error", {})
        msg = f"{err.get('code')}: {err.get('message')}"
    except ValueError:
        msg = r.text[:300]
    if r.status_code == 429 or r.status_code >= 500:
        raise TransientError(f"WhatsApp API {r.status_code} · {msg}")
    raise PermanentError(f"WhatsApp API {r.status_code} · {msg}")
