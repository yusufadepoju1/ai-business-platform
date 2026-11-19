"""Entry point used by web chat, WhatsApp, API and the agent test console."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AgentConfig, Business, Conversation, Customer, Message
from . import tools
from .agent_graph import build_graph

log = logging.getLogger(__name__)
HISTORY_LIMIT = 12
DEFAULTS = {
    "support": ("Support Assistant", "Answers customer questions from your documents and escalates what it cannot answer."),
    "sales": ("Sales Assistant", "Understands needs, recommends offerings using verified data, captures and qualifies leads."),
}


def ensure_agents(db: Session, business_id: int) -> dict[str, AgentConfig]:
    rows = {a.agent_type: a for a in db.execute(select(AgentConfig).where(AgentConfig.business_id == business_id)).scalars()}
    for t, (name, _) in DEFAULTS.items():
        if t not in rows:
            rows[t] = AgentConfig(business_id=business_id, agent_type=t, name=name)
            db.add(rows[t])
    db.commit()
    return rows


def get_or_create_conversation(db: Session, business_id: int, channel: str, session_id: str,
                               customer: Customer | None = None) -> Conversation:
    conv = db.execute(select(Conversation).where(
        Conversation.business_id == business_id, Conversation.channel == channel, Conversation.session_id == session_id,
        Conversation.status.in_(["open", "escalated", "resolved_ai"])).order_by(Conversation.id.desc())).scalars().first()
    if not conv:
        conv = Conversation(business_id=business_id, channel=channel, session_id=session_id,
                            customer_id=customer.id if customer else None)
        db.add(conv)
        db.flush()
    elif customer and not conv.customer_id:
        conv.customer_id = customer.id
    return conv


def handle_customer_message(db: Session, business: Business, channel: str, session_id: str, text: str,
                            customer: Customer | None = None) -> dict:
    text = text.strip()[:2000]
    conv = get_or_create_conversation(db, business.id, channel, session_id, customer)
    history = [{"role": m.role, "content": m.content} for m in
               db.execute(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id.desc())
                          .limit(HISTORY_LIMIT)).scalars()][::-1]
    db.add(Message(conversation_id=conv.id, business_id=business.id, role="customer", content=text))
    db.commit()

    if conv.status == "escalated":  # a human owns this conversation; the AI stays silent
        return {"conversation_id": conv.id, "reply": "Thanks - your message has been added and a team member will reply soon.",
                "status": "escalated", "intent": conv.intent, "actions": ["conversation is with a human"], "sources": [],
                "ai_generated": False}

    cfgs = ensure_agents(db, business.id)
    state = build_graph(db, business, conv, cfgs).invoke({"message": text, "history": history})
    reply, error = state.get("reply", ""), state.get("error")
    if error:
        conv.unresolved = True
        reply = ("Sorry, our assistant is temporarily unavailable. Your message was saved and our team will follow up.")
        meta = {"error": error}
        ai_generated = False
    else:
        meta = {"intent": state.get("intent"), "agent": state.get("agent"), "actions": state.get("actions", []),
                "sources": [{"filename": c["filename"], "score": c["score"]} for c in state.get("context", [])][:5]}
        ai_generated = state.get("agent") != "human_handoff"
    conv.intent = state.get("intent", conv.intent) or conv.intent
    if not error and state.get("agent") in ("support", "sales") and state.get("resolved") and conv.status == "open":
        conv.status = "resolved_ai"
    elif not error and conv.status == "resolved_ai" and state.get("escalate"):
        conv.status = "escalated"
    db.add(Message(conversation_id=conv.id, business_id=business.id, role="ai" if ai_generated or not error else "system",
                   content=reply, meta=meta))
    db.commit()
    db.refresh(conv)
    return {"conversation_id": conv.id, "reply": reply, "status": conv.status, "intent": conv.intent,
            "actions": meta.get("actions", []), "sources": meta.get("sources", []), "ai_generated": ai_generated and not error,
            "error": error}
