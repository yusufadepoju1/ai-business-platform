"""Public endpoints: embeddable chat widget (public key) and server-to-server API (API key)."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Business, Message
from ..ratelimit import rate_limit
from ..security import hash_api_key
from ..services import automation, tools
from ..services import conversation as conv_svc

router = APIRouter(prefix="/api/public", tags=["public"])


def biz_by_key(db: Session, key: str) -> Business:
    b = db.execute(select(Business).where(Business.public_key == key)).scalar_one_or_none() if key else None
    if not b:
        raise HTTPException(404, "Unknown widget key")
    return b


def biz_by_api_key(db: Session, key: str | None) -> Business:
    b = db.execute(select(Business).where(Business.api_key_hash == hash_api_key(key))).scalar_one_or_none() if key else None
    if not b:
        raise HTTPException(401, "Invalid or missing API key (send it in the X-API-Key header)")
    return b


class ChatIn(BaseModel):
    key: str
    session_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_\-]+$")
    message: str = Field(min_length=1, max_length=2000)
    name: str = Field(default="", max_length=200)
    email: EmailStr | None = None


@router.get("/widget-config")
def widget_config(key: str, db: Session = Depends(get_db)):
    b = biz_by_key(db, key)
    agents = conv_svc.ensure_agents(db, b.id)
    greet = (agents["support"].greeting or f"Hi! Welcome to {b.name}. How can I help you today?")
    return {"business_name": b.name, "greeting": greet}


@router.post("/chat", dependencies=[Depends(rate_limit("public-chat", 40, 60))])
def chat(body: ChatIn, db: Session = Depends(get_db)):
    b = biz_by_key(db, body.key)
    cust = tools.upsert_customer(db, b.id, body.name, body.email or "", "", "", "web") if (body.name or body.email) else None
    res = conv_svc.handle_customer_message(db, b, "web", body.session_id, body.message, cust)
    return {"reply": res["reply"], "status": res["status"], "conversation_id": res["conversation_id"], "last_message_id": _last_id(db, res["conversation_id"])}


def _last_id(db: Session, conv_id: int) -> int:
    m = db.execute(select(Message.id).where(Message.conversation_id == conv_id).order_by(Message.id.desc()).limit(1)).scalar()
    return m or 0


@router.get("/chat/poll", dependencies=[Depends(rate_limit("public-poll", 120, 60))])
def poll(key: str, session_id: str, after_id: int = Query(0, ge=0), db: Session = Depends(get_db)):
    """Lets the widget show replies typed by a human team member."""
    b = biz_by_key(db, key)
    from ..models import Conversation
    conv = db.execute(select(Conversation).where(Conversation.business_id == b.id, Conversation.channel == "web",
                                                  Conversation.session_id == session_id).order_by(Conversation.id.desc())).scalars().first()
    if not conv:
        return {"messages": []}
    rows = db.execute(select(Message).where(Message.conversation_id == conv.id, Message.id > after_id, Message.role == "human")
                      .order_by(Message.id)).scalars()
    return {"messages": [{"id": m.id, "content": m.content} for m in rows]}


# ---- server-to-server API (X-API-Key) ----
class ApiChatIn(BaseModel):
    session_id: str = Field(min_length=3, max_length=100)
    message: str = Field(min_length=1, max_length=2000)


@router.post("/v1/chat", dependencies=[Depends(rate_limit("api-chat", 60, 60))])
def api_chat(body: ApiChatIn, x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    b = biz_by_api_key(db, x_api_key)
    res = conv_svc.handle_customer_message(db, b, "api", body.session_id, body.message)
    return {"reply": res["reply"], "status": res["status"], "conversation_id": res["conversation_id"]}


class ApiLeadIn(BaseModel):
    name: str = Field(default="", max_length=200)
    email: EmailStr | None = None
    phone: str = Field(default="", max_length=50)
    company: str = Field(default="", max_length=200)
    interest: str = Field(default="", max_length=300)
    requirements: str = Field(default="", max_length=4000)
    budget: str = Field(default="", max_length=100)
    source: str = Field(default="api", max_length=30)


@router.post("/v1/leads", status_code=201, dependencies=[Depends(rate_limit("api-leads", 60, 60))])
def api_create_lead(body: ApiLeadIn, x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    b = biz_by_api_key(db, x_api_key)
    cust = tools.upsert_customer(db, b.id, body.name, body.email or "", body.phone, body.company, body.source)
    if not cust:
        raise HTTPException(422, "Provide at least a name, email or phone number.")
    lead, created = tools.create_or_update_lead(db, b.id, cust, requirements=body.requirements, budget=body.budget,
                                                interest=body.interest, source=body.source)
    return {"lead_id": lead.id, "customer_id": cust.id, "created": created}
