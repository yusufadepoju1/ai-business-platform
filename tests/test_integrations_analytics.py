import hashlib
import hmac
import json

import httpx

from app.services import whatsapp


def test_integration_status_never_fakes_connection(client, tenant):
    s = client.get("/api/integrations", headers=tenant["h"]).json()
    assert s["whatsapp"]["configured"] is False and s["email"]["configured"] is False
    assert s["groq"]["configured"] is True or s["groq"]["configured"] is False  # reflects env/override
    assert s["web_widget"]["public_key"].startswith("pk_") and "widget.js" in s["web_widget"]["snippet"]
    r = client.post("/api/integrations/email/test", headers=tenant["h"]).json()
    assert r["sent"] is False and "not configured" in r["detail"]


def test_secrets_are_encrypted_and_masked(client, tenant):
    h = tenant["h"]
    assert client.put("/api/integrations/whatsapp", headers=h, json={"phone_number_id": "12345", "access_token": "EAAGsupersecrettoken", "verify_token": "verify-me-123"}).status_code == 200
    s = client.get("/api/integrations", headers=h).json()["whatsapp"]
    assert s["configured"] and "supersecret" not in json.dumps(s) and s["access_token"].endswith("oken")
    from app.database import SessionLocal
    from app.models import Integration
    with SessionLocal() as db:
        raw = db.query(Integration).filter(Integration.kind == "whatsapp").order_by(Integration.id.desc()).first().config_encrypted
        assert "supersecret" not in raw


def test_whatsapp_verify_and_receive(client, kb_tenant, monkeypatch):
    h = kb_tenant["h"]
    key = client.get("/api/business", headers=h).json()["public_key"]
    url = f"/api/webhooks/whatsapp/{key}"
    assert client.get(url, params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"}).status_code == 403  # not configured
    client.put("/api/integrations/whatsapp", headers=h, json={"phone_number_id": "999", "access_token": "tok-123456", "verify_token": "verify-me-123", "app_secret": "appsecret"})
    ok = client.get(url, params={"hub.mode": "subscribe", "hub.verify_token": "verify-me-123", "hub.challenge": "CHALLENGE42"})
    assert ok.status_code == 200 and ok.text == "CHALLENGE42"
    assert client.get(url, params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"}).status_code == 403
    sent = []
    monkeypatch.setattr(httpx, "post", lambda u, **kw: sent.append((u, kw["json"])) or httpx.Response(200, json={}, request=httpx.Request("POST", u)))
    payload = {"entry": [{"changes": [{"value": {"contacts": [{"wa_id": "2348012345678", "profile": {"name": "Tunde"}}],
               "messages": [{"from": "2348012345678", "id": "wamid.A1", "type": "text", "text": {"body": "What is your refund policy?"}}]}}]}]}
    raw = json.dumps(payload).encode()
    assert client.post(url, content=raw, headers={"X-Hub-Signature-256": "sha256=bad"}).status_code == 403
    sig = "sha256=" + hmac.new(b"appsecret", raw, hashlib.sha256).hexdigest()
    r = client.post(url, content=raw, headers={"X-Hub-Signature-256": sig})
    assert r.status_code == 200 and r.json()["handled"] == 1
    assert sent and sent[0][0].endswith("/999/messages") and sent[0][1]["to"] == "2348012345678" and "30 days" in sent[0][1]["text"]["body"]
    # duplicate delivery of same message id is ignored
    assert client.post(url, content=raw, headers={"X-Hub-Signature-256": sig}).json()["handled"] == 0
    assert client.get("/api/customers?q=Tunde", headers=h).json()["total"] == 1
    convs = client.get("/api/conversations?channel=whatsapp", headers=h).json()
    assert convs["total"] == 1


def test_whatsapp_unconfigured_receive_rejected(client, tenant):
    key = client.get("/api/business", headers=tenant["h"]).json()["public_key"]
    assert client.post(f"/api/webhooks/whatsapp/{key}", json={}).status_code == 409
    assert client.post("/api/webhooks/whatsapp/pk_unknown", json={}).status_code == 404


def test_public_widget_chat_and_human_poll(client, kb_tenant):
    h = kb_tenant["h"]
    key = client.get("/api/business", headers=h).json()["public_key"]
    cfg = client.get("/api/public/widget-config", params={"key": key}).json()
    assert "Welcome" in cfg["greeting"] or cfg["greeting"]
    sid = "visitor-session-0001"
    r = client.post("/api/public/chat", json={"key": key, "session_id": sid, "message": "What is your refund policy?"})
    assert r.status_code == 200 and "30 days" in r.json()["reply"]
    assert client.post("/api/public/chat", json={"key": "pk_bad", "session_id": sid, "message": "hi"}).status_code == 404
    assert client.post("/api/public/chat", json={"key": key, "session_id": "bad id!", "message": "hi"}).status_code == 422
    cid = r.json()["conversation_id"]
    client.post(f"/api/conversations/{cid}/reply", headers=h, json={"content": "Hi, a human here"})
    polled = client.get("/api/public/chat/poll", params={"key": key, "session_id": sid, "after_id": 0}).json()
    assert polled["messages"][0]["content"] == "Hi, a human here"
    assert client.options("/api/public/chat").headers["access-control-allow-origin"] == "*"


def test_api_key_lead_creation_and_n8n_callbacks(client, tenant):
    h = tenant["h"]
    assert client.post("/api/public/v1/leads", json={"name": "A B"}).status_code == 401
    key = client.post("/api/integrations/api-key", headers=h).json()["api_key"]
    r = client.post("/api/public/v1/leads", headers={"X-API-Key": key}, json={"name": "Api Lead", "email": "api@lead.io", "interest": "Consulting"})
    assert r.status_code == 201 and r.json()["created"]
    lead_id = r.json()["lead_id"]
    assert client.get("/api/integrations", headers=h).json()["api"]["has_api_key"]
    secret = client.get("/api/integrations", headers=h).json()["n8n"]["webhook_secret"]
    sh = {"X-Webhook-Secret": secret}
    assert client.get("/api/webhooks/n8n/due-follow-ups").status_code == 401
    assert client.get("/api/webhooks/n8n/due-follow-ups", headers={"X-Webhook-Secret": "nope"}).status_code == 401
    due = client.get("/api/webhooks/n8n/due-follow-ups", headers=sh).json()
    assert due["items"] == []  # lead follow-up is due in 24h
    fid = client.get("/api/follow-ups", headers=h).json()[0]["id"]
    assert client.post("/api/webhooks/n8n/follow-up-complete", headers=sh, json={"follow_up_id": fid}).json()["ok"]
    u = client.post("/api/webhooks/n8n/lead-update", headers=sh, json={"lead_id": lead_id, "status": "qualified", "score": 77}).json()
    assert u["status"] == "qualified" and u["score"] == 77
    # another tenant's secret cannot touch this lead
    other = client.post("/api/auth/register", json={"business_name": "Zed Co", "full_name": "Zed Z", "email": "zed@zed.io", "password": "StrongPass123"}).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    osecret = client.get("/api/integrations", headers=oh).json()["n8n"]["webhook_secret"]
    assert client.post("/api/webhooks/n8n/lead-update", headers={"X-Webhook-Secret": osecret}, json={"lead_id": lead_id, "status": "lost"}).status_code == 404


def test_analytics_matches_database(client, kb_tenant):
    h = kb_tenant["h"]
    for i in range(3):
        c = client.post("/api/customers", headers=h, json={"name": f"C{i}", "email": f"c{i}@x.io"}).json()
        client.post("/api/leads", headers=h, json={"customer_id": c["id"], "qualification": "hot" if i == 0 else "cold"})
    lid = client.get("/api/leads?qualification=hot", headers=h).json()["items"][0]["id"]
    client.patch(f"/api/leads/{lid}", headers=h, json={"status": "converted"})
    key = client.get("/api/business", headers=h).json()["public_key"]
    client.post("/api/public/chat", json={"key": key, "session_id": "analytics-sess-1", "message": "What is your refund policy?"})
    client.post("/api/public/chat", json={"key": key, "session_id": "analytics-sess-2", "message": "My dish is broken"})
    client.post("/api/agents/test", headers=h, json={"message": "refund?"})  # test channel: must not count
    a = client.get("/api/analytics/overview", headers=h).json()
    t = a["totals"]
    assert t["customers"] == 3 and t["leads"] == 3 and t["qualified_leads"] == 1 and t["converted_leads"] == 1
    assert t["conversations"] == 2 and t["ai_resolved"] == 1 and t["human_escalations"] == 1
    assert a["rates"]["lead_conversion_rate"] == 33.3 and a["rates"]["ai_resolution_rate"] == 50.0
    assert sum(a["daily"]["conversations"]) == 2 and sum(a["daily"]["leads"]) == 3 and len(a["daily"]["labels"]) == 14
    assert sum(a["weekly"]["leads"]) == 3
