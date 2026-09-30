"""Phase 1 delivery channel. 'outbox' writes .eml files (development); 'smtp' sends for real."""
import smtplib
import socket
import ssl
import uuid
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from ..config import get_settings
from . import PermanentError, TransientError


def _build(to: str, subject: str, text: str, html: str, attachment: Path | None) -> EmailMessage:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=s.email_from.split("@")[-1].strip("> ") or "localhost")
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    if attachment and attachment.exists():
        msg.add_attachment(attachment.read_bytes(), maintype="application", subtype="pdf", filename=attachment.name)
    return msg


def send_email(to: str, subject: str, text: str, html: str, attachment: Path | None) -> tuple[str, str]:
    """Returns (provider message id, provider response)."""
    s = get_settings()
    msg = _build(to, subject, text, html, attachment)
    if s.email_provider == "outbox":
        path = s.outbox_dir / "email" / f"{uuid.uuid4().hex}.eml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(msg))
        return msg["Message-ID"], f"written to {path.name}"

    if s.email_provider != "smtp" or not s.smtp_host:
        raise PermanentError("Email is not configured. Set EMAIL_PROVIDER=smtp and SMTP_HOST.")
    try:
        if s.smtp_port == 465:
            server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=30, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30)
            if s.smtp_use_tls:
                server.starttls(context=ssl.create_default_context())
        with server:
            if s.smtp_username:
                server.login(s.smtp_username, s.smtp_password)
            refused = server.send_message(msg)
        if refused:
            raise PermanentError(f"Recipient refused: {list(refused.values())[0]}")
        return msg["Message-ID"], "250 accepted"
    except smtplib.SMTPRecipientsRefused as e:
        code, reason = list(e.recipients.values())[0]
        raise PermanentError(f"Recipient refused ({code}): {reason.decode(errors='replace') if isinstance(reason, bytes) else reason}")
    except smtplib.SMTPAuthenticationError as e:
        raise PermanentError(f"SMTP login failed ({e.smtp_code}). Check SMTP_USERNAME and SMTP_PASSWORD.")
    except smtplib.SMTPResponseException as e:
        if 400 <= e.smtp_code < 500:
            raise TransientError(f"SMTP temporary failure ({e.smtp_code})")
        raise PermanentError(f"SMTP rejected the message ({e.smtp_code})")
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, socket.timeout, ConnectionError, OSError) as e:
        raise TransientError(f"SMTP server unreachable: {e}")
