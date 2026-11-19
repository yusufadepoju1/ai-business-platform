from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user, get_owned
from ..models import Conversation, Customer, FollowUp, Lead, User
from ..services import automation, tools

router = APIRouter(prefix="/api", tags=["crm"])
LEAD_STATUSES = ("new", "contacted", "qualified", "converted", "lost")


def cust_out(c: Customer) -> dict:
    return {"id": c.id, "name": c.name, "email": c.email, "phone": c.phone, "company": c.company, "source": c.source,
            "notes": c.notes, "created_at": c.created_at}


def lead_out(l: Lead, c: Customer | None = None) -> dict:
    c = c or l.customer
    return {"id": l.id, "customer_id": l.customer_id, "customer_name": c.name if c else "", "customer_email": c.email if c else "",
            "customer_phone": c.phone if c else "", "title": l.title, "status": l.status, "qualification": l.qualification,
            "score": l.score, "requirements": l.requirements, "budget": l.budget, "interest": l.interest,
            "recommended_action": l.recommended_action, "notes": l.notes, "source": l.source,
            "conversation_id": l.conversation_id, "created_at": l.created_at, "updated_at": l.updated_at}


def fu_out(f: FollowUp, db: Session) -> dict:
    cust = db.get(Customer, f.customer_id) if f.customer_id else None
    return {"id": f.id, "lead_id": f.lead_id, "customer_id": f.customer_id, "customer_name": cust.name if cust else "",
            "customer_email": cust.email if cust else "", "action": f.action, "channel": f.channel, "due_at": f.due_at,
            "status": f.status, "completed_at": f.completed_at}


# ---------- customers ----------
class CustomerIn(BaseModel):
    name: str = Field(default="", max_length=200)
    email: EmailStr | None = None
    phone: str = Field(default="", max_length=50)
    company: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=4000)


@router.get("/customers")
def list_customers(q: str = "", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Customer).where(Customer.business_id == user.business_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Customer.name).like(like), func.lower(Customer.email).like(like),
                              Customer.phone.like(f"%{q}%"), func.lower(Customer.company).like(like)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(stmt.order_by(Customer.id.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"total": total, "items": [cust_out(c) for c in rows]}


@router.post("/customers", status_code=201)
def create_customer(body: CustomerIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not (body.name or body.email or body.phone):
        raise HTTPException(422, "Provide at least a name, email or phone number.")
    c = tools.upsert_customer(db, user.business_id, body.name, body.email or "", body.phone, body.company, "manual")
    c.notes = body.notes
    db.commit()
    return cust_out(c)


@router.get("/customers/{cid}")
def customer_detail(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_owned(db, Customer, cid, user.business_id)
    convs = db.execute(select(Conversation).where(Conversation.customer_id == c.id, Conversation.business_id == user.business_id)
                       .order_by(Conversation.id.desc())).scalars().all()
    out = cust_out(c)
    out["leads"] = [lead_out(l, c) for l in sorted(c.leads, key=lambda x: -x.id)]
    out["conversations"] = [{"id": v.id, "channel": v.channel, "status": v.status, "updated_at": v.updated_at} for v in convs]
    return out


@router.put("/customers/{cid}")
def update_customer(cid: int, body: CustomerIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_owned(db, Customer, cid, user.business_id)
    c.name, c.email, c.phone, c.company, c.notes = body.name, (body.email or "").lower(), body.phone, body.company, body.notes
    db.commit()
    return cust_out(c)


@router.delete("/customers/{cid}")
def delete_customer(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(get_owned(db, Customer, cid, user.business_id))
    db.commit()
    return {"ok": True}


# ---------- leads ----------
class LeadIn(BaseModel):
    customer_id: int
    title: str = Field(default="", max_length=300)
    requirements: str = Field(default="", max_length=4000)
    budget: str = Field(default="", max_length=100)
    interest: str = Field(default="", max_length=300)
    qualification: str = Field(default="unknown", pattern="^(hot|warm|cold|unknown)$")
    source: str = Field(default="manual", max_length=30)


class LeadPatch(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    status: str | None = Field(default=None, pattern="^(new|contacted|qualified|converted|lost)$")
    qualification: str | None = Field(default=None, pattern="^(hot|warm|cold|unknown)$")
    requirements: str | None = Field(default=None, max_length=4000)
    budget: str | None = Field(default=None, max_length=100)
    interest: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=4000)
    recommended_action: str | None = Field(default=None, max_length=300)


def apply_lead_patch(db: Session, lead: Lead, body: LeadPatch):
    prev = lead.status
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(lead, k, v)
    if body.qualification:
        lead.score = tools.SCORE[body.qualification]
    db.commit()
    if lead.status == "qualified" and prev != "qualified":
        automation.fire_event(lead.business_id, "lead_qualified", tools.lead_payload(lead, lead.customer))


@router.get("/leads")
def list_leads(q: str = "", status: str = "", qualification: str = "", page: int = Query(1, ge=1),
               page_size: int = Query(25, ge=1, le=100), user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Lead, Customer).join(Customer, Customer.id == Lead.customer_id).where(Lead.business_id == user.business_id)
    if status:
        stmt = stmt.where(Lead.status == status)
    if qualification:
        stmt = stmt.where(Lead.qualification == qualification)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Lead.title).like(like), func.lower(Customer.name).like(like),
                              func.lower(Customer.email).like(like), func.lower(Lead.interest).like(like)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(stmt.order_by(Lead.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "items": [lead_out(l, c) for l, c in rows]}


@router.post("/leads", status_code=201)
def create_lead(body: LeadIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_owned(db, Customer, body.customer_id, user.business_id)
    lead = Lead(business_id=user.business_id, customer_id=c.id, title=body.title or body.interest or "New lead",
                requirements=body.requirements, budget=body.budget, interest=body.interest, source=body.source,
                qualification=body.qualification, score=tools.SCORE[body.qualification])
    if body.qualification == "hot":
        lead.status = "qualified"
    db.add(lead)
    db.commit()
    automation.fire_event(user.business_id, "new_lead", tools.lead_payload(lead, c))
    return lead_out(lead, c)


@router.get("/leads/{lid}")
def lead_detail(lid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lead = get_owned(db, Lead, lid, user.business_id)
    out = lead_out(lead)
    fus = db.execute(select(FollowUp).where(FollowUp.lead_id == lid, FollowUp.business_id == user.business_id)
                     .order_by(FollowUp.due_at)).scalars().all()
    out["follow_ups"] = [fu_out(f, db) for f in fus]
    return out


@router.patch("/leads/{lid}")
def patch_lead(lid: int, body: LeadPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lead = get_owned(db, Lead, lid, user.business_id)
    apply_lead_patch(db, lead, body)
    return lead_out(lead)


@router.delete("/leads/{lid}")
def delete_lead(lid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(get_owned(db, Lead, lid, user.business_id))
    db.commit()
    return {"ok": True}


# ---------- follow-ups ----------
class FollowUpIn(BaseModel):
    lead_id: int | None = None
    customer_id: int | None = None
    action: str = Field(min_length=2, max_length=500)
    channel: str = Field(default="email", pattern="^(email|whatsapp|call|other)$")
    due_at: datetime


@router.get("/follow-ups")
def list_follow_ups(status: str = "pending", user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(FollowUp).where(FollowUp.business_id == user.business_id)
    if status:
        stmt = stmt.where(FollowUp.status == status)
    return [fu_out(f, db) for f in db.execute(stmt.order_by(FollowUp.due_at).limit(200)).scalars()]


@router.post("/follow-ups", status_code=201)
def create_follow_up(body: FollowUpIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cid = body.customer_id
    if body.lead_id:
        cid = get_owned(db, Lead, body.lead_id, user.business_id).customer_id
    elif cid:
        get_owned(db, Customer, cid, user.business_id)
    due = body.due_at if body.due_at.tzinfo else body.due_at.replace(tzinfo=timezone.utc)
    f = FollowUp(business_id=user.business_id, lead_id=body.lead_id, customer_id=cid, action=body.action,
                 channel=body.channel, due_at=due)
    db.add(f)
    db.commit()
    return fu_out(f, db)


@router.post("/follow-ups/{fid}/complete")
def complete_follow_up(fid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = get_owned(db, FollowUp, fid, user.business_id)
    f.status, f.completed_at = "done", datetime.now(timezone.utc)
    db.commit()
    return fu_out(f, db)
