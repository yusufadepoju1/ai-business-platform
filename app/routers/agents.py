import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import admin_user, current_business, current_user
from ..models import Business, User
from ..ratelimit import rate_limit
from ..services import conversation as conv_svc
from ..services.llm import llm_configured

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    tone: str = Field(default="friendly and professional", max_length=50)
    instructions: str = Field(default="", max_length=4000)
    temperature: float = Field(default=0.2, ge=0, le=1)
    auto_escalate: bool = True
    greeting: str = Field(default="", max_length=300)


def agent_out(a) -> dict:
    return {"agent_type": a.agent_type, "name": a.name, "enabled": a.enabled, "tone": a.tone, "instructions": a.instructions,
            "temperature": a.temperature, "auto_escalate": a.auto_escalate, "greeting": a.greeting,
            "description": conv_svc.DEFAULTS[a.agent_type][1]}


@router.get("")
def list_agents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"agents": [agent_out(a) for a in conv_svc.ensure_agents(db, user.business_id).values()],
            "llm_configured": llm_configured()}


@router.put("/{agent_type}")
def update_agent(agent_type: str, body: AgentIn, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    agents = conv_svc.ensure_agents(db, user.business_id)
    a = agents.get(agent_type)
    if not a:
        raise HTTPException(404, "Unknown agent type")
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    db.commit()
    return agent_out(a)


class TestIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


@router.post("/test", dependencies=[Depends(rate_limit("agent-test", 30, 60))])
def test_agent(body: TestIn, user: User = Depends(current_user), biz: Business = Depends(current_business),
               db: Session = Depends(get_db)):
    """Runs the full LangGraph workflow (real CRM/escalation side effects, channel='test')."""
    sid = body.session_id or f"test-{user.id}-{uuid.uuid4().hex[:8]}"
    res = conv_svc.handle_customer_message(db, biz, "test", sid, body.message)
    res["session_id"] = sid
    return res
