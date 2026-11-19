"""CRM / support tools used by the agents (and the REST API)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Conversation, Customer, Escalation, FollowUp, Lead, Message
from . import automation

SCORE = {"hot": 85, "warm": 60, "cold": 25, "unknown": 0}


def upsert_customer(db: Session, business_id: int, name="", email="", phone="", company="", source="web") -> Customer | None:
    name, email, phone, company = (name or "").strip(), (email or "").strip().lower(), (phone or "").strip(), (company or "").strip()
    if not (email or phone or name):
        return None
    cust = None
    if email:
        cust = db.execute(select(Customer).where(Customer.business_id == business_id, Customer.email == email)).scalars().first()
    if not cust and phone:
        cust = db.execute(select(Customer).where(Customer.business_id == business_id, Customer.phone == phone)).scalars().first()
    if cust:
        for attr, val in (("name", name), ("email", email), ("phone", phone), ("company", company)):
            if val and not getattr(cust, attr):
                setattr(cust, attr, val)
    else:
        cust = Customer(business_id=business_id, name=name, email=email, phone=phone, company=company, source=source)
        db.add(cust)
    db.flush()
    return cust


def schedule_follow_up(db: Session, business_id: int, lead: Lead | None, customer_id: int | None, action: str,
                       hours: int = 24, channel: str = "email") -> FollowUp:
    fu = FollowUp(business_id=business_id, lead_id=lead.id if lead else None, customer_id=customer_id,
                  action=action[:500], channel=channel, due_at=datetime.now(timezone.utc) + timedelta(hours=hours))
    db.add(fu)
    db.flush()
    return fu


def lead_payload(lead: Lead, customer: Customer | None) -> dict:
    return {"lead_id": lead.id, "status": lead.status, "qualification": lead.qualification, "score": lead.score,
            "title": lead.title, "requirements": lead.requirements, "budget": lead.budget, "interest": lead.interest,
            "recommended_action": lead.recommended_action,
            "customer_name": customer.name if customer else "", "customer_email": customer.email if customer else "",
            "customer_phone": customer.phone if customer else "", "customer_company": customer.company if customer else ""}


def create_or_update_lead(db: Session, business_id: int, customer: Customer, *, requirements="", budget="",
                          interest="", qualification="unknown", action="", source="web",
                          conversation_id: int | None = None) -> tuple[Lead, bool]:
    qualification = qualification if qualification in SCORE else "unknown"
    lead = db.execute(select(Lead).where(Lead.business_id == business_id, Lead.customer_id == customer.id,
                                         Lead.status.in_(["new", "contacted", "qualified"]))
                      .order_by(Lead.id.desc())).scalars().first()
    created = lead is None
    if created:
        lead = Lead(business_id=business_id, customer_id=customer.id, source=source, conversation_id=conversation_id, status="new",
                    title=(interest or requirements or "New enquiry")[:200])
        db.add(lead)
    prev_status = lead.status
    if requirements:
        lead.requirements = requirements
    if budget:
        lead.budget = budget[:100]
    if interest:
        lead.interest = interest[:300]
    if action:
        lead.recommended_action = action[:300]
    if qualification != "unknown":
        lead.qualification, lead.score = qualification, SCORE[qualification]
        if qualification == "hot" and lead.status in ("new", "contacted"):
            lead.status = "qualified"
    db.flush()
    if created:
        schedule_follow_up(db, business_id, lead, customer.id, action or "Reach out to confirm requirements",
                           hours=2 if lead.qualification == "hot" else 24)
    db.commit()
    if created:
        automation.fire_event(business_id, "new_lead", lead_payload(lead, customer))
    if lead.status == "qualified" and prev_status != "qualified":
        automation.fire_event(business_id, "lead_qualified", lead_payload(lead, customer))
    return lead, created


def escalate(db: Session, business_id: int, conv: Conversation, reason: str) -> Escalation:
    existing = db.execute(select(Escalation).where(Escalation.conversation_id == conv.id,
                                                    Escalation.status == "open")).scalars().first()
    if existing:
        return existing
    esc = Escalation(business_id=business_id, conversation_id=conv.id, reason=reason[:500])
    db.add(esc)
    conv.status, conv.unresolved = "escalated", True
    db.commit()
    last = db.execute(select(Message).where(Message.conversation_id == conv.id, Message.role == "customer")
                      .order_by(Message.id.desc())).scalars().first()
    cust = db.get(Customer, conv.customer_id) if conv.customer_id else None
    automation.fire_event(business_id, "human_escalation", {
        "conversation_id": conv.id, "channel": conv.channel, "reason": reason,
        "last_customer_message": last.content if last else "",
        "customer_name": cust.name if cust else "", "customer_email": cust.email if cust else "",
        "customer_phone": cust.phone if cust else ""})
    return esc
