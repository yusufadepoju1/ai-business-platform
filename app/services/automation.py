"""Event dispatch: outbound webhooks (n8n or any REST endpoint) and email notifications."""
import ipaddress
import json
import logging
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import Automation, AutomationLog, Business
from ..security import decrypt_json, encrypt_json, sign_payload
from .emailer import get_smtp_config, send_email

log = logging.getLogger(__name__)
EVENTS = ["new_lead", "lead_qualified", "human_escalation", "follow_up_due", "email_notification"]
_pool = ThreadPoolExecutor(max_workers=4)


class TargetError(ValueError):
    pass


def validate_target_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise TargetError("Target URL must start with http:// or https://")
    if not settings.allow_private_webhook_targets:
        try:
            infos = socket.getaddrinfo(p.hostname, p.port or 80)
        except socket.gaierror:
            raise TargetError("Target host could not be resolved.")
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise TargetError("Private or local network targets are not allowed on this server.")
    return url


def store_auth_header(header: str | None) -> str:
    if not header:
        return ""
    if ":" not in header:
        raise TargetError("Auth header must look like 'Header-Name: value'.")
    name, value = header.split(":", 1)
    return encrypt_json({"name": name.strip(), "value": value.strip()})


def deliver(db: Session, automation: Automation, business: Business, event: str, payload: dict) -> dict:
    body_obj = {"event": event, "business_id": business.id, "business_name": business.name,
                "timestamp": datetime.now(timezone.utc).isoformat(), "data": payload}
    body = json.dumps(body_obj, default=str).encode()
    headers = {"Content-Type": "application/json", "X-Event": event,
               "X-Signature": sign_payload(business.webhook_secret, body)}
    auth = decrypt_json(automation.auth_header_encrypted)
    if auth.get("name"):
        headers[auth["name"]] = auth["value"]
    status, http_status, detail = "failed", None, ""
    try:
        validate_target_url(automation.target_url)
        r = httpx.post(automation.target_url, content=body, headers=headers, timeout=10)
        http_status = r.status_code
        status = "success" if r.status_code < 400 else "failed"
        detail = r.text[:300]
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"[:300]
    automation.last_status, automation.last_triggered_at = status, datetime.now(timezone.utc)
    db.add(AutomationLog(business_id=business.id, automation_id=automation.id, event=event,
                         target=automation.target_url[:600], status=status, http_status=http_status, detail=detail))
    db.commit()
    return {"status": status, "http_status": http_status, "detail": detail}


def _notify_email_text(event: str, payload: dict) -> tuple[str, str]:
    titles = {"new_lead": "New lead captured", "lead_qualified": "Lead qualified",
              "human_escalation": "Conversation needs a human", "follow_up_due": "Follow-up due"}
    lines = [f"{k}: {v}" for k, v in payload.items() if v not in (None, "")]
    return titles.get(event, event), "\n".join(lines)


def _run_event(business_id: int, event: str, payload: dict):
    db = SessionLocal()
    try:
        business = db.get(Business, business_id)
        if not business:
            return
        autos = db.execute(select(Automation).where(Automation.business_id == business_id,
                                                     Automation.event == event, Automation.enabled.is_(True))).scalars().all()
        for a in autos:
            deliver(db, a, business, event, payload)
        if business.notification_email and event != "follow_up_due":
            subject, body = _notify_email_text(event, payload)
            ok, detail = send_email(get_smtp_config(db, business_id), business.notification_email,
                                    f"[{business.name}] {subject}", body)
            db.add(AutomationLog(business_id=business_id, event="email_notification",
                                 target=business.notification_email, status="success" if ok else "skipped",
                                 detail=detail))
            db.commit()
    except Exception:
        log.exception("Event dispatch failed")
    finally:
        db.close()


def fire_event(business_id: int, event: str, payload: dict):
    """Fire-and-forget (background thread) unless ASYNC_DISPATCH is false (tests)."""
    if settings.async_dispatch:
        _pool.submit(_run_event, business_id, event, payload)
    else:
        _run_event(business_id, event, payload)
