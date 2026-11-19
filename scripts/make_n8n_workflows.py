"""Generates the importable n8n workflow JSON files in n8n_workflows/."""
import json
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "n8n_workflows"
OUT.mkdir(exist_ok=True)
APP = "https://YOUR-APP-URL"          # replace after import
SECRET = "YOUR_WEBHOOK_SECRET"       # Integrations page -> n8n / Automations page
_n = lambda: str(uuid.uuid4())


def webhook(name, path, pos):
    return {"parameters": {"httpMethod": "POST", "path": path, "responseMode": "onReceived", "options": {}},
            "id": _n(), "name": name, "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": pos, "webhookId": _n()}


def email(name, subject, text, pos, to="team@example.com"):
    return {"parameters": {"fromEmail": "notifications@example.com", "toEmail": to, "subject": subject, "emailFormat": "text", "text": text, "options": {}},
            "id": _n(), "name": name, "type": "n8n-nodes-base.emailSend", "typeVersion": 2.1, "position": pos,
            "notesInFlow": True, "notes": "Select your SMTP credential and edit the addresses."}


def http(name, method, url, pos, body=None):
    p = {"method": method, "url": url, "sendHeaders": True,
         "headerParameters": {"parameters": [{"name": "X-Webhook-Secret", "value": SECRET}]}, "options": {}}
    if body is not None:
        p.update({"sendBody": True, "specifyBody": "json", "jsonBody": body})
    return {"parameters": p, "id": _n(), "name": name, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": pos}


def wf(name, nodes, links):
    conns = {}
    for a, b, *idx in links:
        conns.setdefault(a, {"main": []})
        out = idx[0] if idx else 0
        while len(conns[a]["main"]) <= out:
            conns[a]["main"].append([])
        conns[a]["main"][out].append({"node": b, "type": "main", "index": 0})
    return {"name": name, "nodes": nodes, "connections": conns, "active": False, "settings": {"executionOrder": "v1"}, "tags": [], "meta": {"templateCredsSetupCompleted": False}}


flows = {}

flows["01_new_lead_notification.json"] = wf("AI Platform - New lead notification", [
    webhook("New lead webhook", "ai-new-lead", [0, 0]),
    email("Email sales team", "=New lead: {{ $json.body.data.title }}",
          "=A new lead was captured.\n\nName: {{ $json.body.data.customer_name }}\nEmail: {{ $json.body.data.customer_email }}\nPhone: {{ $json.body.data.customer_phone }}\nInterest: {{ $json.body.data.interest }}\nRequirements: {{ $json.body.data.requirements }}\nBudget: {{ $json.body.data.budget }}\nQualification: {{ $json.body.data.qualification }} (score {{ $json.body.data.score }})\nSuggested next step: {{ $json.body.data.recommended_action }}", [300, 0])],
    [("New lead webhook", "Email sales team")])

flows["02_automated_customer_followups.json"] = wf("AI Platform - Automated customer follow-ups", [
    {"parameters": {"rule": {"interval": [{"field": "minutes", "minutesInterval": 15}]}}, "id": _n(), "name": "Every 15 minutes", "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [0, 0]},
    http("Get due follow-ups", "GET", f"{APP}/api/webhooks/n8n/due-follow-ups", [260, 0]),
    {"parameters": {"fieldToSplitOut": "items", "options": {}}, "id": _n(), "name": "One item per follow-up", "type": "n8n-nodes-base.splitOut", "typeVersion": 1, "position": [520, 0]},
    {"parameters": {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"}, "conditions": [{"id": _n(), "leftValue": "={{ $json.customer_email }}", "rightValue": "", "operator": {"type": "string", "operation": "notEmpty", "singleValue": True}}], "combinator": "and"}, "options": {}},
     "id": _n(), "name": "Has email?", "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [780, 0]},
    email("Email the customer", "=Following up on your enquiry",
          "=Hi {{ $json.customer_name || 'there' }},\n\n{{ $json.action }}\n\nReply to this email if you have any questions.", [1040, -80], to="={{ $json.customer_email }}"),
    http("Mark follow-up done", "POST", f"{APP}/api/webhooks/n8n/follow-up-complete", [1300, -80], '={{ JSON.stringify({ follow_up_id: $("One item per follow-up").item.json.follow_up_id, note: "Email sent by n8n" }) }}')],
    [("Every 15 minutes", "Get due follow-ups"), ("Get due follow-ups", "One item per follow-up"), ("One item per follow-up", "Has email?"),
     ("Has email?", "Email the customer", 0), ("Email the customer", "Mark follow-up done")])

flows["03_lead_qualification.json"] = wf("AI Platform - Lead qualification", [
    webhook("Lead webhook", "ai-lead-qualification", [0, 0]),
    {"parameters": {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"}, "conditions": [{"id": _n(), "leftValue": "={{ $json.body.data.score }}", "rightValue": 70, "operator": {"type": "number", "operation": "gte"}}], "combinator": "and"}, "options": {}},
     "id": _n(), "name": "Score >= 70?", "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [260, 0]},
    http("Mark lead qualified", "POST", f"{APP}/api/webhooks/n8n/lead-update", [540, -80], '={{ JSON.stringify({ lead_id: $json.body.data.lead_id, status: "qualified", notes: "Auto-qualified by n8n: score " + $json.body.data.score }) }}'),
    {"parameters": {}, "id": _n(), "name": "Leave as is", "type": "n8n-nodes-base.noOp", "typeVersion": 1, "position": [540, 100]}],
    [("Lead webhook", "Score >= 70?"), ("Score >= 70?", "Mark lead qualified", 0), ("Score >= 70?", "Leave as is", 1)])

flows["04_human_escalation.json"] = wf("AI Platform - Human escalation alert", [
    webhook("Escalation webhook", "ai-human-escalation", [0, 0]),
    email("Email support team", "=URGENT: conversation #{{ $json.body.data.conversation_id }} needs a human",
          "=Reason: {{ $json.body.data.reason }}\nChannel: {{ $json.body.data.channel }}\nCustomer: {{ $json.body.data.customer_name }} {{ $json.body.data.customer_email }} {{ $json.body.data.customer_phone }}\n\nLast message:\n{{ $json.body.data.last_customer_message }}\n\nReply from the dashboard: Conversations.", [300, 0])],
    [("Escalation webhook", "Email support team")])

flows["05_email_notifications.json"] = wf("AI Platform - Generic email notifications", [
    webhook("Event webhook", "ai-email-notification", [0, 0]),
    email("Send notification", "=[{{ $json.body.business_name }}] {{ $json.body.event }}", "={{ JSON.stringify($json.body.data, null, 2) }}", [300, 0])],
    [("Event webhook", "Send notification")])

for fname, flow in flows.items():
    (OUT / fname).write_text(json.dumps(flow, indent=2))
print("wrote", len(flows), "workflows")
