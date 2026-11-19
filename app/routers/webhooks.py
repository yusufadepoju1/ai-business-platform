"""Inbound webhooks: WhatsApp Cloud API and n8n callbacks."""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Business, Customer, FollowUp, Lead, Message
from ..security import decrypt_json
from ..services import conversation as conv_svc
from ..services import tools, whatsapp
from ..models import Integration

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
log = logging.getLogger(__name__)
_seen: list[str] = []  # recent WhatsApp message ids (per-process de-duplication)


def _wa_integration(db: Session, key: str):
    biz = db.execute(select(Business).where(Business.public_key == key)).scalar_one_or_none()
    if not biz:
        raise HTTPException(404, "Unknown business")
    integ = db.execute(select(Integration).where(Integration.business_id == biz.id, Integration.kind == "whatsapp")).scalar_one_or_none()
    cfg = decrypt_json(integ.config_encrypted) if integ and integ.enabled else {}
    return biz, cfg


@router.get("/whatsapp/{key}", response_class=PlainTextResponse)
def whatsapp_verify(key: str, hub_mode: str = Query("", alias="hub.mode"), hub_token: str = Query("", alias="hub.verify_token"),
                    hub_challenge: str = Query("", alias="hub.challenge"), db: Session = Depends(get_db)):
    _, cfg = _wa_integration(db, key)
    if hub_mode == "subscribe" and cfg.get("verify_token") and hub_token == cfg["verify_token"]:
        return hub_challenge
    raise HTTPException(403, "Verification failed")


@router.post("/whatsapp/{key}")
async def whatsapp_receive(key: str, request: Request, db: Session = Depends(get_db)):
    biz, cfg = _wa_integration(db, key)
    if not cfg.get("access_token"):
        raise HTTPException(409, "WhatsApp is not configured for this business.")
    raw = await request.body()
    if not whatsapp.verify_signature(cfg.get("app_secret", ""), raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(403, "Invalid signature")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "Invalid JSON")
    handled = 0
    for m in whatsapp.parse_incoming(payload):
        if m["id"] in _seen:
            continue
        _seen.append(m["id"])
        del _seen[:-500]
        cust = tools.upsert_customer(db, biz.id, m["name"], "", m["from"], "", "whatsapp")
        res = conv_svc.handle_customer_message(db, biz, "whatsapp", m["from"], m["text"], cust)
        if res["actions"] != ["conversation is with a human"]:  # a human owns it: stay silent
            ok, detail = whatsapp.send_text(cfg, m["from"], res["reply"])
            if not ok:
                log.warning("WhatsApp reply failed: %s", detail)
        handled += 1
    return {"status": "ok", "handled": handled}  # always 200 so Meta does not retry


# ---------------- n8n callbacks (header X-Webhook-Secret) ----------------
def n8n_business(db: Session = Depends(get_db), x_webhook_secret: str | None = Header(default=None)) -> Business:
    b = db.execute(select(Business).where(Business.webhook_secret == x_webhook_secret)).scalar_one_or_none() if x_webhook_secret else None
    if not b:
        raise HTTPException(401, "Invalid or missing X-Webhook-Secret header")
    return b


class LeadUpdateIn(BaseModel):
    lead_id: int
    status: str | None = Field(default=None, pattern="^(new|contacted|qualified|converted|lost)$")
    qualification: str | None = Field(default=None, pattern="^(hot|warm|cold|unknown)$")
    score: int | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=4000)


@router.post("/n8n/lead-update")
def n8n_lead_update(body: LeadUpdateIn, biz: Business = Depends(n8n_business), db: Session = Depends(get_db)):
    lead = db.get(Lead, body.lead_id)
    if not lead or lead.business_id != biz.id:
        raise HTTPException(404, "Lead not found")
    from .crm import LeadPatch, apply_lead_patch
    apply_lead_patch(db, lead, LeadPatch(status=body.status, qualification=body.qualification, notes=body.notes))
    if body.score is not None:
        lead.score = body.score
        db.commit()
    return {"ok": True, "lead_id": lead.id, "status": lead.status, "score": lead.score}


@router.get("/n8n/due-follow-ups")
def n8n_due(biz: Business = Depends(n8n_business), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    rows = db.execute(select(FollowUp).where(FollowUp.business_id == biz.id, FollowUp.status == "pending", FollowUp.due_at <= now)
                      .order_by(FollowUp.due_at).limit(50)).scalars().all()
    out = []
    for f in rows:
        c = db.get(Customer, f.customer_id) if f.customer_id else None
        out.append({"follow_up_id": f.id, "lead_id": f.lead_id, "action": f.action, "channel": f.channel, "due_at": f.due_at,
                    "customer_name": c.name if c else "", "customer_email": c.email if c else "", "customer_phone": c.phone if c else ""})
    return {"business": biz.name, "items": out}


class FollowUpDoneIn(BaseModel):
    follow_up_id: int
    note: str = Field(default="", max_length=1000)


@router.post("/n8n/follow-up-complete")
def n8n_followup_done(body: FollowUpDoneIn, biz: Business = Depends(n8n_business), db: Session = Depends(get_db)):
    f = db.get(FollowUp, body.follow_up_id)
    if not f or f.business_id != biz.id:
        raise HTTPException(404, "Follow-up not found")
    f.status, f.completed_at = "done", datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}
