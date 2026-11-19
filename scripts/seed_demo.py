"""Create a clearly-labelled DEMO workspace (is_demo=True) so the dashboard has something to show.

    python scripts/seed_demo.py            # create (skips if it exists)
    python scripts/seed_demo.py --reset    # delete and recreate the demo workspace

Login: demo@example.com / DemoPass123!   Demo messages are sample data, not real AI output.
"""
import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import (Business, Conversation, Customer, Escalation, FollowUp, Lead, Message, User, utcnow)  # noqa: E402
from app.security import hash_password, new_public_key, new_webhook_secret  # noqa: E402
from app.services import rag  # noqa: E402
from app.services.conversation import ensure_agents  # noqa: E402
from app.services.vectorstore import VectorStore  # noqa: E402

DEMO_EMAIL = "demo@example.com"
KB = """Sunrise Solar - Company Overview
Sunrise Solar designs and installs residential and small-business solar systems. We are open Monday to Friday, 8am to 6pm.

Pricing (sample data)
The Home 5kW system costs $9,500 installed. The Home 8kW system costs $13,900 installed. Battery storage (10kWh) is an additional $6,200.
Financing is available over 5, 10 or 15 years. Maintenance plans cost $15 per month.

Warranty and returns (sample data)
Panels carry a 25-year performance warranty. Inverters carry a 10-year warranty. Installation workmanship is covered for 5 years.
Quotes are free and valid for 30 days. Deposits are refundable within 14 days of signing."""


def main(reset: bool):
    if not settings.database_url.startswith("sqlite") or settings.auto_create_tables:
        pass
    with SessionLocal() as db:
        existing = db.execute(select(User).where(User.email == DEMO_EMAIL)).scalar_one_or_none()
        if existing and not reset:
            print("Demo workspace already exists. Use --reset to recreate. Login:", DEMO_EMAIL, "/ DemoPass123!")
            return
        if existing:
            VectorStore(existing.business_id).delete_files()
            db.delete(db.get(Business, existing.business_id))
            db.commit()
        biz = Business(name="Sunrise Solar (DEMO DATA)", industry="Solar energy", is_demo=True,
                       description="Sample workspace with demo records. Not real business data.",
                       email=DEMO_EMAIL, notification_email=DEMO_EMAIL, phone="+1 555 0100",
                       public_key=new_public_key(), webhook_secret=new_webhook_secret())
        db.add(biz)
        db.flush()
        db.add(User(business_id=biz.id, email=DEMO_EMAIL, full_name="Demo Owner", role="owner",
                    hashed_password=hash_password("DemoPass123!")))
        db.commit()
        ensure_agents(db, biz.id)
        rag.ingest_text(db, biz.id, "sunrise_solar_sample.txt", "txt", len(KB), KB)

        rnd = random.Random(7)
        names = [("Maya Chen", "maya@example.org"), ("Luis Ortega", "luis@example.org"), ("Priya Nair", "priya@example.org"),
                 ("Tom Becker", "tom@example.org"), ("Amara Okafor", "amara@example.org"), ("Sven Larsen", "sven@example.org"),
                 ("Chloe Martin", "chloe@example.org"), ("Dev Patel", "dev@example.org")]
        statuses = ["new", "contacted", "qualified", "qualified", "converted", "lost", "new", "converted"]
        quals = ["warm", "warm", "hot", "hot", "hot", "cold", "cold", "hot"]
        now = utcnow()
        for i, ((n, e), st, q) in enumerate(zip(names, statuses, quals)):
            when = now - timedelta(days=rnd.randint(0, 13), hours=rnd.randint(0, 20))
            c = Customer(business_id=biz.id, name=n, email=e, source="web", created_at=when)
            db.add(c)
            db.flush()
            lead = Lead(business_id=biz.id, customer_id=c.id, title=rnd.choice(["Home 5kW system", "Home 8kW + battery", "Business rooftop"]),
                        status=st, qualification=q, score={"hot": 85, "warm": 60, "cold": 25}[q], interest="Solar installation",
                        requirements="Sample requirement", source="web", created_at=when)
            db.add(lead)
            db.flush()
            if st in ("new", "contacted", "qualified"):
                db.add(FollowUp(business_id=biz.id, lead_id=lead.id, customer_id=c.id, action="Send quote and book site visit",
                                due_at=now + timedelta(hours=rnd.randint(-6, 48))))
            for k in range(rnd.randint(1, 2)):
                cv = Conversation(business_id=biz.id, customer_id=c.id, channel=rnd.choice(["web", "whatsapp"]), session_id=f"demo-{i}-{k}",
                                  status="resolved_ai" if k == 0 else "closed", intent="sales", created_at=when, updated_at=when)
                db.add(cv)
                db.flush()
                db.add(Message(conversation_id=cv.id, business_id=biz.id, role="customer", content="[demo] How much is a 5kW system?", meta={"demo": True}, created_at=when))
                db.add(Message(conversation_id=cv.id, business_id=biz.id, role="ai", content="[demo sample] The Home 5kW system costs $9,500 installed.", meta={"demo": True}, created_at=when))
        for k in range(3):
            when = now - timedelta(days=rnd.randint(0, 10))
            cv = Conversation(business_id=biz.id, channel="web", session_id=f"demo-esc-{k}", status="escalated" if k == 0 else "closed",
                              intent="support", unresolved=True, created_at=when, updated_at=when)
            db.add(cv)
            db.flush()
            db.add(Message(conversation_id=cv.id, business_id=biz.id, role="customer", content="[demo] My inverter shows an error code", meta={"demo": True}, created_at=when))
            db.add(Escalation(business_id=biz.id, conversation_id=cv.id, reason="Demo: no answer in knowledge base",
                              status="open" if k == 0 else "resolved", created_at=when))
        for k in range(6):
            when = now - timedelta(days=rnd.randint(0, 13))
            db.add(Conversation(business_id=biz.id, channel="web", session_id=f"demo-faq-{k}", status="resolved_ai", intent="faq",
                                created_at=when, updated_at=when))
        db.commit()
    print("Demo workspace created. Login:", DEMO_EMAIL, "/ DemoPass123!  (all records are sample data)")


if __name__ == "__main__":
    if settings.auto_create_tables:
        Base.metadata.create_all(engine)
    main("--reset" in sys.argv)
