from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import admin_user, current_business, current_user, get_owned
from ..models import Automation, AutomationLog, Business, User
from ..services import automation as svc

router = APIRouter(prefix="/api/automations", tags=["automations"])

EVENT_INFO = {
    "new_lead": "A new lead is created by an AI agent, the API or the CRM.",
    "lead_qualified": "A lead becomes qualified (AI hot lead or status changed).",
    "human_escalation": "A conversation is handed to a human.",
    "follow_up_due": "Sent by n8n polling /api/webhooks/n8n/due-follow-ups (informational).",
    "email_notification": "Generic email notification trigger for your own flows.",
}


class AutoIn(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    event: str
    target_url: str = Field(max_length=600)
    auth_header: str | None = Field(default=None, max_length=500)
    enabled: bool = True


def out(a: Automation) -> dict:
    return {"id": a.id, "name": a.name, "event": a.event, "target_url": a.target_url, "enabled": a.enabled,
            "has_auth_header": bool(a.auth_header_encrypted), "last_status": a.last_status,
            "last_triggered_at": a.last_triggered_at}


def _check(body: AutoIn):
    if body.event not in svc.EVENTS:
        raise HTTPException(422, f"Event must be one of: {', '.join(svc.EVENTS)}")
    try:
        svc.validate_target_url(body.target_url)
        return svc.store_auth_header(body.auth_header)
    except svc.TargetError as exc:
        raise HTTPException(422, str(exc))


@router.get("/events")
def events(_: User = Depends(current_user)):
    return EVENT_INFO


@router.get("")
def list_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [out(a) for a in db.execute(select(Automation).where(Automation.business_id == user.business_id)
                                       .order_by(Automation.id.desc())).scalars()]


@router.post("", status_code=201)
def create(body: AutoIn, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    enc = _check(body)
    a = Automation(business_id=user.business_id, name=body.name, event=body.event, target_url=body.target_url,
                   auth_header_encrypted=enc, enabled=body.enabled)
    db.add(a)
    db.commit()
    return out(a)


@router.put("/{aid}")
def update(aid: int, body: AutoIn, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    a = get_owned(db, Automation, aid, user.business_id)
    enc = _check(body)
    a.name, a.event, a.target_url, a.enabled = body.name, body.event, body.target_url, body.enabled
    if body.auth_header is not None:
        a.auth_header_encrypted = enc
    db.commit()
    return out(a)


@router.delete("/{aid}")
def delete(aid: int, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    db.delete(get_owned(db, Automation, aid, user.business_id))
    db.commit()
    return {"ok": True}


@router.post("/{aid}/test")
def test(aid: int, user: User = Depends(admin_user), biz: Business = Depends(current_business), db: Session = Depends(get_db)):
    a = get_owned(db, Automation, aid, user.business_id)
    sample = {"test": True, "note": "Test delivery from the dashboard - not real business data."}
    return svc.deliver(db, a, biz, a.event, sample)


@router.get("/logs")
def logs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(AutomationLog).where(AutomationLog.business_id == user.business_id)
                      .order_by(AutomationLog.id.desc()).limit(100)).scalars()
    return [{"id": r.id, "event": r.event, "target": r.target, "status": r.status, "http_status": r.http_status,
             "detail": r.detail, "created_at": r.created_at} for r in rows]
