from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import Conversation, Customer, Escalation, Lead, Message, User

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _daily(db: Session, col, where, days: int):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(select(col).where(*where, col >= since)).scalars().all()
    counts: dict[str, int] = defaultdict(int)
    for ts in rows:
        counts[ts.date().isoformat()] += 1
    return counts


@router.get("/overview")
def overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    bid = user.business_id
    real = Conversation.channel != "test"

    def count(model, *where):
        return db.execute(select(func.count()).select_from(model).where(*where)).scalar() or 0

    customers = count(Customer, Customer.business_id == bid)
    convs = count(Conversation, Conversation.business_id == bid, real)
    leads = count(Lead, Lead.business_id == bid)
    qualified = count(Lead, Lead.business_id == bid, Lead.status.in_(["qualified", "converted"]))
    converted = count(Lead, Lead.business_id == bid, Lead.status == "converted")
    ai_resolved = count(Conversation, Conversation.business_id == bid, real, Conversation.status == "resolved_ai")
    escalated = count(Escalation, Escalation.business_id == bid)
    open_esc = count(Escalation, Escalation.business_id == bid, Escalation.status == "open")
    messages = count(Message, Message.business_id == bid)
    pct = lambda a, b: round(100 * a / b, 1) if b else 0.0

    days = 14
    today = datetime.now(timezone.utc).date()
    labels = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    conv_d = _daily(db, Conversation.created_at, [Conversation.business_id == bid, real], days)
    lead_d = _daily(db, Lead.created_at, [Lead.business_id == bid], days)
    esc_d = _daily(db, Escalation.created_at, [Escalation.business_id == bid], days)

    weeks = 8
    wk_conv, wk_lead = defaultdict(int), defaultdict(int)
    since = datetime.now(timezone.utc) - timedelta(weeks=weeks)
    for ts in db.execute(select(Conversation.created_at).where(Conversation.business_id == bid, real, Conversation.created_at >= since)).scalars():
        wk_conv[(today - ts.date()).days // 7] += 1
    for ts in db.execute(select(Lead.created_at).where(Lead.business_id == bid, Lead.created_at >= since)).scalars():
        wk_lead[(today - ts.date()).days // 7] += 1
    wlabels = [f"{i}w ago" if i else "This week" for i in range(weeks - 1, -1, -1)]
    by_status = dict(db.execute(select(Lead.status, func.count()).where(Lead.business_id == bid).group_by(Lead.status)).all())
    by_channel = dict(db.execute(select(Conversation.channel, func.count()).where(Conversation.business_id == bid, real)
                                 .group_by(Conversation.channel)).all())
    return {
        "totals": {"customers": customers, "conversations": convs, "messages": messages, "leads": leads,
                   "qualified_leads": qualified, "converted_leads": converted, "ai_resolved": ai_resolved,
                   "human_escalations": escalated, "open_escalations": open_esc},
        "rates": {"lead_qualification_rate": pct(qualified, leads), "lead_conversion_rate": pct(converted, leads),
                  "ai_resolution_rate": pct(ai_resolved, convs), "escalation_rate": pct(escalated, convs)},
        "daily": {"labels": labels, "conversations": [conv_d.get(d, 0) for d in labels],
                  "leads": [lead_d.get(d, 0) for d in labels], "escalations": [esc_d.get(d, 0) for d in labels]},
        "weekly": {"labels": wlabels, "conversations": [wk_conv.get(i, 0) for i in range(weeks - 1, -1, -1)],
                   "leads": [wk_lead.get(i, 0) for i in range(weeks - 1, -1, -1)]},
        "leads_by_status": by_status, "conversations_by_channel": by_channel,
    }
