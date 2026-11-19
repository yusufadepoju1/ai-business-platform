"""LangGraph orchestration:

classify -> (handoff | retrieve) -> (sales_agent -> crm_tools | support_agent -> support_tools -> [handoff]) -> finalize
Conversation memory = recent stored messages passed in as `history`.
"""
import logging
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from ..models import AgentConfig, Business, Conversation, Customer
from . import rag, tools
from .llm import LLMUnavailable, invoke_json

log = logging.getLogger(__name__)

INTENTS = ["faq", "support", "sales", "human_request", "greeting", "other"]


class AgentState(TypedDict, total=False):
    message: str
    history: list
    intent: str
    context: list
    reply: str
    resolved: bool
    escalate: bool
    escalation_reason: str
    actions: list
    error: str
    agent: str
    lead_id: Optional[int]
    sales: dict


def _persona(business: Business, cfg: AgentConfig | None, role: str) -> str:
    name = cfg.name if cfg else ("Sales Assistant" if role == "sales" else "Support Assistant")
    tone = cfg.tone if cfg else "friendly and professional"
    extra = f"\nAdditional instructions from the business owner:\n{cfg.instructions}" if cfg and cfg.instructions else ""
    return (f"You are {name}, the AI {role} assistant for {business.name} ({business.industry}). "
            f"Business description: {business.description or 'n/a'}. Tone: {tone}. "
            f"Contact: phone {business.phone or 'n/a'}, email {business.email or 'n/a'}.{extra}")


def build_graph(db: Session, business: Business, conv: Conversation, cfgs: dict[str, AgentConfig]):
    sales_on = not cfgs.get("sales") or cfgs["sales"].enabled
    support_on = not cfgs.get("support") or cfgs["support"].enabled

    def classify(s: AgentState) -> AgentState:
        try:
            r = invoke_json(
                "Classify the customer's latest message. Intents: faq (general question about the business), "
                "support (problem/complaint/order issue), sales (interest in buying, pricing, products, quotes), "
                "human_request (explicitly asks for a person/agent/manager), greeting, other. "
                'Return {"intent": "<one intent>"}.', s["message"], s.get("history"))
            intent = r.get("intent", "other")
            return {"intent": intent if intent in INTENTS else "other", "actions": []}
        except LLMUnavailable as exc:
            return {"error": str(exc), "intent": "other", "actions": []}

    def route_after_classify(s: AgentState) -> str:
        if s.get("error"):
            return "finalize"
        if s["intent"] == "human_request":
            return "handoff"
        return "retrieve"

    def retrieve(s: AgentState) -> AgentState:
        query = s["message"]
        if len(query) < 25 and s.get("history"):  # short follow-ups: add the last customer turn for context
            prev = [m["content"] for m in s["history"] if m["role"] == "customer"][-1:]
            query = " ".join(prev + [query])
        results = rag.search(db, business.id, query, k=5)
        return {"context": results, "actions": s.get("actions", []) + [f"retrieved {len(results)} passages"]}

    def route_after_retrieve(s: AgentState) -> str:
        if s["intent"] == "sales" and sales_on:
            return "sales_agent"
        if not support_on:
            return "handoff"
        return "support_agent"

    def support_agent(s: AgentState) -> AgentState:
        cfg = cfgs.get("support")
        ctx = rag.format_context(s.get("context", [])) or "(no relevant business documents found)"
        system = (_persona(business, cfg, "customer support") + "\nAnswer ONLY from the verified context below. "
                  "If the context does not contain the answer, do not guess: set resolved=false. "
                  "Be concise. If the customer is just greeting you, greet back and offer help (resolved=true).\n"
                  f"VERIFIED CONTEXT:\n{ctx}\n"
                  'Return {"reply": str, "resolved": bool, "reason_if_unresolved": str}.')
        try:
            r = invoke_json(system, s["message"], s.get("history"), cfg.temperature if cfg else 0.2)
        except LLMUnavailable as exc:
            return {"error": str(exc)}
        return {"reply": str(r.get("reply", "")).strip(), "resolved": bool(r.get("resolved", False)),
                "escalation_reason": str(r.get("reason_if_unresolved", "")) or "AI could not answer from business knowledge",
                "agent": "support"}

    def support_tools(s: AgentState) -> AgentState:
        if s.get("error"):
            return {}
        if not s.get("resolved") or not s.get("reply"):
            conv.unresolved = True
            auto = cfgs.get("support").auto_escalate if cfgs.get("support") else True
            return {"escalate": auto, "actions": s["actions"] + ["marked unresolved"]}
        return {"actions": s["actions"] + ["answered from knowledge base" if s.get("context") else "answered"]}

    def route_after_support(s: AgentState) -> str:
        return "handoff" if s.get("escalate") else "finalize"

    def sales_agent(s: AgentState) -> AgentState:
        cfg = cfgs.get("sales")
        ctx = rag.format_context(s.get("context", [])) or "(no verified product/pricing data found)"
        known = db.get(Customer, conv.customer_id) if conv.customer_id else None
        known_txt = (f"Known customer: name={known.name!r}, email={known.email!r}, phone={known.phone!r}"
                     if known else "Customer details not yet known.")
        system = (_persona(business, cfg, "sales") + "\nHelp the customer find the right product/service. "
                  "Quote prices ONLY if they appear in the verified context; otherwise say you can't confirm pricing and "
                  "offer a human follow-up. Never invent products, prices, discounts or availability. "
                  "Ask naturally for missing contact details (name, email or phone) and requirements/budget. "
                  "Qualification: hot = clear need + budget/timeline + contact; warm = interested but missing details; "
                  f"cold = browsing; unknown = not enough info.\n{known_txt}\nVERIFIED CONTEXT:\n{ctx}\n"
                  'Return {"reply": str, "customer": {"name": str, "email": str, "phone": str, "company": str}, '
                  '"requirements": str, "budget": str, "interest": str, "qualification": "hot|warm|cold|unknown", '
                  '"follow_up_action": str}. Use empty strings for anything the customer has not stated.')
        try:
            r = invoke_json(system, s["message"], s.get("history"), cfg.temperature if cfg else 0.3)
        except LLMUnavailable as exc:
            return {"error": str(exc)}
        return {"reply": str(r.get("reply", "")).strip(), "resolved": True, "agent": "sales", "sales": r}

    def crm_tools(s: AgentState) -> AgentState:
        r = s.get("sales") or {}
        actions = list(s.get("actions", []))
        c = r.get("customer") or {}
        cust = tools.upsert_customer(db, business.id, c.get("name"), c.get("email"), c.get("phone"), c.get("company"),
                                     source=conv.channel)
        if not cust and conv.customer_id:
            cust = db.get(Customer, conv.customer_id)
        lead_id = None
        if cust:
            conv.customer_id = cust.id
            has_contact = bool(cust.email or cust.phone)
            has_info = any(r.get(k) for k in ("requirements", "interest", "budget"))
            if has_contact and has_info:
                lead, created = tools.create_or_update_lead(
                    db, business.id, cust, requirements=r.get("requirements", ""), budget=r.get("budget", ""),
                    interest=r.get("interest", ""), qualification=r.get("qualification", "unknown"),
                    action=r.get("follow_up_action", ""), source=conv.channel, conversation_id=conv.id)
                lead_id = lead.id
                actions.append(f"{'created' if created else 'updated'} lead #{lead.id} ({lead.qualification})")
            else:
                actions.append("captured customer details" if has_contact else "customer saved (no contact yet)")
        db.commit()
        return {"actions": actions, "lead_id": lead_id}

    def handoff(s: AgentState) -> AgentState:
        reason = s.get("escalation_reason") or ("Customer asked for a human" if s.get("intent") == "human_request"
                                                else "Support agent unavailable")
        tools.escalate(db, business.id, conv, reason)
        reply = ("I'm passing this conversation to a member of our team who will follow up with you shortly. "
                 "Thank you for your patience.")
        return {"reply": reply, "escalate": True, "resolved": False, "agent": "human_handoff",
                "actions": s.get("actions", []) + [f"escalated to human: {reason}"]}

    def finalize(s: AgentState) -> AgentState:
        return {}

    g = StateGraph(AgentState)
    for name, fn in [("classify", classify), ("retrieve", retrieve), ("support_agent", support_agent),
                     ("support_tools", support_tools), ("sales_agent", sales_agent), ("crm_tools", crm_tools),
                     ("handoff", handoff), ("finalize", finalize)]:
        g.add_node(name, fn)
    g.set_entry_point("classify")
    g.add_conditional_edges("classify", route_after_classify, {"finalize": "finalize", "handoff": "handoff", "retrieve": "retrieve"})
    g.add_conditional_edges("retrieve", route_after_retrieve, {"sales_agent": "sales_agent", "support_agent": "support_agent", "handoff": "handoff"})
    g.add_conditional_edges("support_agent", lambda s: "finalize" if s.get("error") else "support_tools",
                            {"finalize": "finalize", "support_tools": "support_tools"})
    g.add_conditional_edges("support_tools", route_after_support, {"handoff": "handoff", "finalize": "finalize"})
    g.add_conditional_edges("sales_agent", lambda s: "finalize" if s.get("error") else "crm_tools",
                            {"finalize": "finalize", "crm_tools": "crm_tools"})
    g.add_edge("crm_tools", "finalize")
    g.add_edge("handoff", "finalize")
    g.add_edge("finalize", END)
    return g.compile()
