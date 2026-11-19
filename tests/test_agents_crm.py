import json

import httpx

from app.services import llm


def test_support_answers_from_knowledge(client, kb_tenant):
    h = kb_tenant["h"]
    r = client.post("/api/agents/test", headers=h, json={"message": "What is your refund policy?"}).json()
    assert r["reply"] == "Refunds are accepted within 30 days." and r["status"] == "resolved_ai" and r["ai_generated"]
    assert r["sources"] and r["intent"] == "support"


def test_conversation_memory(client, kb_tenant):
    h = kb_tenant["h"]
    first = client.post("/api/agents/test", headers=h, json={"message": "What is your refund policy?"}).json()
    client.post("/api/agents/test", headers=h, json={"message": "thanks", "session_id": first["session_id"]})
    detail = client.get(f"/api/conversations/{first['conversation_id']}", headers=h).json()
    assert [m["role"] for m in detail["messages"]][:3] == ["customer", "ai", "customer"]


def test_unresolved_escalates_and_ai_goes_silent(client, kb_tenant, monkeypatch):
    h = kb_tenant["h"]
    calls = []
    monkeypatch.setattr(httpx, "post", lambda url, **kw: calls.append((url, kw)) or httpx.Response(200, text="ok", request=httpx.Request("POST", url)))
    a = client.post("/api/automations", headers=h, json={"name": "Escalation hook", "event": "human_escalation", "target_url": "http://localhost:5678/webhook/esc", "auth_header": "X-Token: abc"})
    assert a.status_code == 201
    r = client.post("/api/agents/test", headers=h, json={"message": "My satellite dish is broken after the storm"}).json()
    assert r["status"] == "escalated" and "team" in r["reply"] and not r["ai_generated"]
    assert len(calls) == 1 and calls[0][0].endswith("/webhook/esc")
    assert calls[0][1]["headers"]["X-Token"] == "abc" and calls[0][1]["headers"]["X-Signature"].startswith("sha256=")
    body = json.loads(calls[0][1]["content"])
    assert body["event"] == "human_escalation" and "satellite" in body["data"]["last_customer_message"]
    # follow-up message: human owns it, AI does not answer
    r2 = client.post("/api/agents/test", headers=h, json={"message": "hello?", "session_id": r["session_id"]}).json()
    assert r2["status"] == "escalated" and r2["actions"] == ["conversation is with a human"]
    esc = client.get("/api/escalations", headers=h).json()
    assert len(esc) == 1
    assert client.post(f"/api/conversations/{r['conversation_id']}/reply", headers=h, json={"content": "We are on it"}).json()["ok"]
    assert client.post(f"/api/conversations/{r['conversation_id']}/resolve", headers=h).json()["status"] == "closed"
    assert client.get("/api/escalations", headers=h).json() == []
    logs = client.get("/api/automations/logs", headers=h).json()
    hook = [l for l in logs if l["target"].endswith("/webhook/esc")][0]
    assert hook["status"] == "success" and hook["http_status"] == 200
    mail = [l for l in logs if l["event"] == "email_notification"][0]
    assert mail["status"] == "skipped" and "not configured" in mail["detail"]  # honest: no SMTP set up


def test_human_request_handoff(client, kb_tenant):
    r = client.post("/api/agents/test", headers=kb_tenant["h"], json={"message": "I want to talk to a human manager"}).json()
    assert r["status"] == "escalated" and r["intent"] == "human_request"


def test_sales_agent_creates_lead_with_verified_price(client, kb_tenant, monkeypatch):
    h = kb_tenant["h"]
    calls = []
    monkeypatch.setattr(httpx, "post", lambda url, **kw: calls.append(json.loads(kw["content"])) or httpx.Response(200, text="ok", request=httpx.Request("POST", url)))
    for ev in ("new_lead", "lead_qualified"):
        client.post("/api/automations", headers=h, json={"name": ev, "event": ev, "target_url": "http://localhost:5678/webhook/" + ev})
    r1 = client.post("/api/agents/test", headers=h, json={"message": "I'm interested in the pro plan price"}).json()
    assert "$49" in r1["reply"]  # price comes from the uploaded document, not invented
    assert client.get("/api/leads", headers=h).json()["total"] == 0  # no contact yet -> no lead
    r2 = client.post("/api/agents/test", headers=h, json={"message": "I want to buy, reach me at ada@buyer.com", "session_id": r1["session_id"]}).json()
    leads = client.get("/api/leads", headers=h).json()
    assert leads["total"] == 1
    lead = leads["items"][0]
    assert lead["qualification"] == "hot" and lead["status"] == "qualified" and lead["customer_email"] == "ada@buyer.com"
    assert any("lead" in a for a in r2["actions"])
    assert sorted(c["event"] for c in calls) == ["lead_qualified", "new_lead"]
    fus = client.get("/api/follow-ups", headers=h).json()
    assert len(fus) == 1 and fus[0]["lead_id"] == lead["id"]
    cust = client.get(f"/api/customers/{lead['customer_id']}", headers=h).json()
    assert cust["leads"] and cust["conversations"]


def test_sales_without_pricing_data_does_not_invent(client, tenant):
    r = client.post("/api/agents/test", headers=tenant["h"], json={"message": "What's the price? I want to buy"}).json()
    assert "$" not in r["reply"] and "can't confirm" in r["reply"]


def test_llm_unavailable_is_graceful(client, kb_tenant):
    llm.set_llm_override(None)  # no GROQ_API_KEY in test env
    r = client.post("/api/agents/test", headers=kb_tenant["h"], json={"message": "refund?"}).json()
    assert r["ai_generated"] is False and r["error"] and "unavailable" in r["reply"].lower()
    q = client.post("/api/knowledge/ask", headers=kb_tenant["h"], json={"question": "refund policy"})
    assert q.status_code == 503
    assert client.get("/api/agents", headers=kb_tenant["h"]).json()["llm_configured"] is False


def test_disabled_support_agent_hands_off(client, kb_tenant):
    h = kb_tenant["h"]
    client.put("/api/agents/support", headers=h, json={"name": "Support", "enabled": False})
    r = client.post("/api/agents/test", headers=h, json={"message": "What is your refund policy?"}).json()
    assert r["status"] == "escalated"


def test_crm_crud_search_and_filters(client, tenant):
    h = tenant["h"]
    c1 = client.post("/api/customers", headers=h, json={"name": "Jane Roe", "email": "jane@roe.io", "company": "Roe Ltd"}).json()
    c2 = client.post("/api/customers", headers=h, json={"name": "John Doe", "phone": "+15551234"}).json()
    assert client.post("/api/customers", headers=h, json={}).status_code == 422
    assert client.get("/api/customers?q=roe", headers=h).json()["total"] == 1
    assert client.get("/api/customers?q=5551", headers=h).json()["total"] == 1
    l1 = client.post("/api/leads", headers=h, json={"customer_id": c1["id"], "interest": "Solar panels", "qualification": "warm"}).json()
    client.post("/api/leads", headers=h, json={"customer_id": c2["id"], "interest": "Batteries"})
    assert client.get("/api/leads?q=solar", headers=h).json()["total"] == 1
    p = client.patch(f"/api/leads/{l1['id']}", headers=h, json={"status": "converted"}).json()
    assert p["status"] == "converted"
    assert client.get("/api/leads?status=converted", headers=h).json()["total"] == 1
    assert client.patch(f"/api/leads/{l1['id']}", headers=h, json={"status": "bogus"}).status_code == 422
    fu = client.post("/api/follow-ups", headers=h, json={"lead_id": l1["id"], "action": "Call back", "due_at": "2030-01-01T10:00:00Z"}).json()
    assert client.post(f"/api/follow-ups/{fu['id']}/complete", headers=h).json()["status"] == "done"
    assert client.delete(f"/api/customers/{c2['id']}", headers=h).status_code == 200
    assert client.get("/api/leads", headers=h).json()["total"] == 1  # cascade removed John's lead


def test_automation_validation(client, tenant, monkeypatch):
    h = tenant["h"]
    assert client.post("/api/automations", headers=h, json={"name": "bad", "event": "nope", "target_url": "http://x.co"}).status_code == 422
    assert client.post("/api/automations", headers=h, json={"name": "bad", "event": "new_lead", "target_url": "ftp://x.co"}).status_code == 422
    from app.config import settings
    monkeypatch.setattr(settings, "allow_private_webhook_targets", False)
    assert client.post("/api/automations", headers=h, json={"name": "ssrf", "event": "new_lead", "target_url": "http://127.0.0.1:8000/x"}).status_code == 422


def test_failed_webhook_is_logged_not_crashing(client, tenant, monkeypatch):
    h = tenant["h"]
    def boom(url, **kw):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "post", boom)
    a = client.post("/api/automations", headers=h, json={"name": "Failing hook", "event": "new_lead", "target_url": "http://localhost:5678/w"}).json()
    res = client.post(f"/api/automations/{a['id']}/test", headers=h).json()
    assert res["status"] == "failed" and "ConnectError" in res["detail"]
