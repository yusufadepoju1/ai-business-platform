from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, get_owned
from ..models import Conversation, Customer, Escalation, Message, User
from ..services import whatsapp

router = APIRouter(prefix="/api", tags=["conversations"])


def conv_out(c: Conversation, db: Session, last: str = "") -> dict:
    cust = db.get(Customer, c.customer_id) if c.customer_id else None
    return {"id": c.id, "channel": c.channel, "status": c.status, "intent": c.intent, "unresolved": c.unresolved,
            "customer_id": c.customer_id, "customer_name": (cust.name or cust.email or cust.phone) if cust else "Anonymous visitor",
            "session_id": c.session_id, "created_at": c.created_at, "updated_at": c.updated_at, "last_message": last}


@router.get("/conversations")
def list_conversations(status: str = "", channel: str = "", q: str = "", include_test: bool = False,
                       page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Conversation).where(Conversation.business_id == user.business_id)
    if not include_test and channel != "test":
        stmt = stmt.where(Conversation.channel != "test")
    if status:
        stmt = stmt.where(Conversation.status == status)
    if channel:
        stmt = stmt.where(Conversation.channel == channel)
    if q:
        ids = select(Message.conversation_id).where(Message.business_id == user.business_id,
                                                    func.lower(Message.content).like(f"%{q.lower()}%"))
        stmt = stmt.where(Conversation.id.in_(ids))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(stmt.order_by(Conversation.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    items = []
    for c in rows:
        m = db.execute(select(Message.content).where(Message.conversation_id == c.id).order_by(Message.id.desc()).limit(1)).scalar()
        items.append(conv_out(c, db, (m or "")[:120]))
    return {"total": total, "items": items}


@router.get("/conversations/{cid}")
def conversation_detail(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_owned(db, Conversation, cid, user.business_id)
    out = conv_out(c, db)
    out["messages"] = [{"id": m.id, "role": m.role, "content": m.content, "meta": m.meta, "created_at": m.created_at}
                       for m in c.messages]
    return out


class ReplyIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


@router.post("/conversations/{cid}/reply")
def human_reply(cid: int, body: ReplyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_owned(db, Conversation, cid, user.business_id)
    delivery = "stored (web chat visitors see it on their next poll)"
    if c.channel == "whatsapp":
        ok, detail = whatsapp.send_text(whatsapp.get_config(db, c.business_id), c.session_id, body.content)
        delivery = "delivered via WhatsApp" if ok else f"saved, but WhatsApp delivery failed: {detail}"
    db.add(Message(conversation_id=c.id, business_id=c.business_id, role="human", content=body.content,
                   meta={"user_id": user.id, "user": user.full_name}))
    if c.status != "escalated":
        c.status = "escalated"  # human took over; AI stays out
    c.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "delivery": delivery}


@router.post("/conversations/{cid}/resolve")
def resolve(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_owned(db, Conversation, cid, user.business_id)
    c.status = "closed"
    now = datetime.now(timezone.utc)
    for e in db.execute(select(Escalation).where(Escalation.conversation_id == c.id, Escalation.status == "open")).scalars():
        e.status, e.resolved_at = "resolved", now
    db.commit()
    return conv_out(c, db)


@router.get("/escalations")
def escalations(status: str = "open", user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Escalation).where(Escalation.business_id == user.business_id)
    if status:
        stmt = stmt.where(Escalation.status == status)
    out = []
    for e in db.execute(stmt.order_by(Escalation.id.desc()).limit(100)).scalars():
        c = db.get(Conversation, e.conversation_id)
        out.append({"id": e.id, "conversation_id": e.conversation_id, "reason": e.reason, "status": e.status,
                    "created_at": e.created_at, "customer_name": conv_out(c, db)["customer_name"] if c else ""})
    return out
