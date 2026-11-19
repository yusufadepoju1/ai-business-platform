"""SMTP email. Per-business settings (Integration kind=email) override the server-wide env config."""
import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Integration
from ..security import decrypt_json

log = logging.getLogger(__name__)


def get_smtp_config(db: Session, business_id: int) -> dict | None:
    integ = db.execute(select(Integration).where(Integration.business_id == business_id,
                                                  Integration.kind == "email")).scalar_one_or_none()
    if integ and integ.enabled:
        cfg = decrypt_json(integ.config_encrypted)
        if cfg.get("host"):
            return cfg
    if settings.smtp_host:
        return {"host": settings.smtp_host, "port": settings.smtp_port, "user": settings.smtp_user,
                "password": settings.smtp_password, "from_email": settings.smtp_from or settings.smtp_user,
                "use_tls": settings.smtp_use_tls}
    return None


def send_email(cfg: dict | None, to: str, subject: str, body: str) -> tuple[bool, str]:
    """Returns (sent, detail). Never raises; never pretends to send without config."""
    if not cfg:
        return False, "Email is not configured (no SMTP settings)."
    if not to:
        return False, "No recipient address."
    msg = EmailMessage()
    msg["From"] = cfg.get("from_email") or cfg.get("user")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        port = int(cfg.get("port", 587))
        if port == 465:
            with smtplib.SMTP_SSL(cfg["host"], port, timeout=15) as s:
                if cfg.get("user"):
                    s.login(cfg["user"], cfg.get("password", ""))
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg["host"], port, timeout=15) as s:
                if cfg.get("use_tls", True):
                    s.starttls()
                if cfg.get("user"):
                    s.login(cfg["user"], cfg.get("password", ""))
                s.send_message(msg)
        return True, "sent"
    except Exception as exc:
        log.warning("SMTP send failed: %s", exc)
        return False, f"SMTP error: {type(exc).__name__}: {exc}"[:300]
