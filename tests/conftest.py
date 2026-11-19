import os
import re
import tempfile
import json

_tmp = tempfile.mkdtemp(prefix="aibiz_test_")
os.environ.update({
    "APP_ENV": "test", "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db"), "AUTO_CREATE_TABLES": "true",
    "VECTOR_DIR": f"{_tmp}/vectors", "ASYNC_DISPATCH": "false", "RATE_LIMIT_ENABLED": "false",
    "EMBEDDING_PROVIDER": "hashing", "GROQ_API_KEY": "", "SECRET_KEY": "test-secret-key-for-pytest-only-123456",
})

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import llm


class FakeLLM:
    """Deterministic stand-in for Groq. It follows the prompt contract (JSON replies) so the LangGraph
    routing, retrieval, CRM tools and escalation logic are exercised for real."""

    class _R:
        def __init__(self, content):
            self.content = content

    def invoke(self, messages):
        system, user = messages[0].content, messages[-1].content
        low = user.lower()
        if "Classify the customer's latest message" in system:
            if "human" in low or "manager" in low:
                intent = "human_request"
            elif any(w in low for w in ("price", "buy", "quote", "pro plan", "interested")):
                intent = "sales"
            else:
                intent = "support"
            return self._R(json.dumps({"intent": intent}))
        if "AI customer support assistant" in system:
            ctx = system.split("VERIFIED CONTEXT:")[1]
            if "refund" in low and "refund" in ctx.lower():
                return self._R(json.dumps({"reply": "Refunds are accepted within 30 days.", "resolved": True, "reason_if_unresolved": ""}))
            return self._R(json.dumps({"reply": "", "resolved": False, "reason_if_unresolved": "No answer in knowledge base"}))
        if "AI sales assistant" in system:
            email = re.search(r"[\w.]+@[\w.]+\.\w+", user)
            ctx = system.split("VERIFIED CONTEXT:")[1]
            price = "49" if "$49" in ctx else None
            return self._R(json.dumps({
                "reply": f"The Pro plan costs ${price} per month." if price else "I can't confirm pricing right now.",
                "customer": {"name": "Ada Buyer" if email else "", "email": email.group(0) if email else "", "phone": "", "company": ""},
                "requirements": "Needs a plan for a 10 person team", "budget": "$500", "interest": "Pro plan",
                "qualification": "hot" if email else "warm", "follow_up_action": "Send onboarding details"}))
        return self._R("{}")


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def fake_llm():
    llm.set_llm_override(FakeLLM())
    yield
    llm.set_llm_override(None)


def register(client, name="Acme", email=None):
    import uuid
    email = email or f"{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/register", json={"business_name": name, "industry": "retail", "full_name": "Owner Person",
                                                "email": email, "password": "StrongPass123"})
    assert r.status_code == 201, r.text
    d = r.json()
    return {"Authorization": f"Bearer {d['access_token']}"}, d["user"], email


@pytest.fixture()
def tenant(client):
    h, user, email = register(client)
    return {"h": h, "user": user, "email": email}


@pytest.fixture()
def tenant2(client):
    h, user, email = register(client, "Other Co")
    return {"h": h, "user": user, "email": email}


KB = (b"Refund policy: customers may request a refund within 30 days of purchase.\n\n"
      b"Pricing: The Pro plan costs $49 per month and includes 10 seats. The Starter plan costs $19 per month.\n\n"
      b"Opening hours: Monday to Friday, 9am to 5pm.")


@pytest.fixture()
def kb_tenant(client, tenant):
    r = client.post("/api/knowledge/documents", headers=tenant["h"], files={"file": ("policies.txt", KB, "text/plain")})
    assert r.status_code == 201, r.text
    return tenant
