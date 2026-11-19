"""WhatsApp Business Cloud API (Meta Graph API) helpers."""
import hashlib
import hmac
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Integration
from ..security import decrypt_json

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v20.0"


def get_config(db: Session, business_id: int) -> dict | None:
    integ = db.execute(select(Integration).where(Integration.business_id == business_id,
                                                  Integration.kind == "whatsapp")).scalar_one_or_none()
    if not integ or not integ.enabled:
        return None
    cfg = decrypt_json(integ.config_encrypted)
    return cfg if cfg.get("access_token") and cfg.get("phone_number_id") else None


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not app_secret:
        return True  # signature check is optional until an app secret is configured
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def send_text(cfg: dict | None, to: str, text: str) -> tuple[bool, str]:
    if not cfg:
        return False, "WhatsApp is not configured."
    try:
        r = httpx.post(f"{GRAPH}/{cfg['phone_number_id']}/messages",
                       headers={"Authorization": f"Bearer {cfg['access_token']}"},
                       json={"messaging_product": "whatsapp", "to": to, "type": "text",
                             "text": {"body": text[:4000]}}, timeout=15)
        if r.status_code >= 400:
            return False, f"WhatsApp API error {r.status_code}: {r.text[:200]}"
        return True, "sent"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:300]


def parse_incoming(payload: dict) -> list[dict]:
    """Extract text messages from a Cloud API webhook payload."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                if m.get("type") == "text":
                    out.append({"from": m["from"], "text": m["text"]["body"], "id": m.get("id"),
                                "name": names.get(m["from"], "")})
    return out
