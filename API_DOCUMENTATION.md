# API documentation
Interactive docs (Swagger): `/api/docs`. All dashboard endpoints require `Authorization: Bearer <JWT>` from `/api/auth/login`. Every record is scoped to the caller's business; other businesses' IDs return `404`. Validation errors return `422`; rate limits return `429`.

## Auth & team
| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/register` | `{business_name, industry, full_name, email, password>=8}` -> token + user (creates business, owner, default agents) |
| POST | `/api/auth/login` | `{email, password}` -> token |
| GET/PUT | `/api/auth/me` | profile |
| POST | `/api/auth/change-password` | |
| GET/POST | `/api/team` | list / add member (owner, admin) |
| PATCH | `/api/team/{id}` | role / is_active (owner, admin) |

## Business
`GET /api/business`, `PUT /api/business` (owner/admin).

## Knowledge base
| Method | Path | Notes |
|---|---|---|
| GET | `/api/knowledge/documents` | |
| POST | `/api/knowledge/documents` | multipart `file` (PDF/TXT/DOCX, <=10 MB), owner/admin |
| GET/DELETE | `/api/knowledge/documents/{id}` | delete removes vectors |
| POST | `/api/knowledge/search` | `{query, k}` semantic search |
| POST | `/api/knowledge/ask` | `{question}` RAG answer + sources; `503` if no LLM key |

## Agents
`GET /api/agents`, `PUT /api/agents/{support|sales}` (owner/admin), `POST /api/agents/test` `{message, session_id?}` runs the full LangGraph workflow on channel `test`. Response: `reply, status, intent, actions[], sources[], ai_generated, error?, session_id`.

## CRM
| Path | Methods |
|---|---|
| `/api/customers` | GET (`q, page, page_size`), POST |
| `/api/customers/{id}` | GET (with leads & conversations), PUT, DELETE |
| `/api/leads` | GET (`q, status, qualification, page`), POST |
| `/api/leads/{id}` | GET, PATCH (`status, qualification, notes, ...`), DELETE |
| `/api/follow-ups` | GET (`status`), POST; `POST /api/follow-ups/{id}/complete` |

Lead statuses: `new, contacted, qualified, converted, lost`. Qualification: `hot, warm, cold, unknown`.

## Conversations
`GET /api/conversations` (`status, channel, q, include_test`), `GET /api/conversations/{id}`, `POST /api/conversations/{id}/reply` (human reply; delivered via WhatsApp for that channel), `POST /api/conversations/{id}/resolve`, `GET /api/escalations`.

## Automations
`GET/POST /api/automations`, `PUT/DELETE /api/automations/{id}`, `POST /api/automations/{id}/test`, `GET /api/automations/logs`, `GET /api/automations/events`.
Events: `new_lead, lead_qualified, human_escalation, follow_up_due, email_notification`.

Outbound request: `POST <target_url>`, JSON body
```json
{"event":"new_lead","business_id":1,"business_name":"...","timestamp":"...","data":{...}}
```
Headers: `X-Event`, `X-Signature: sha256=<HMAC-SHA256(body, business webhook secret)>`, plus your optional auth header.

## Integrations
`GET /api/integrations` (masked status), `PUT /api/integrations/whatsapp`, `PUT /api/integrations/email`, `DELETE /api/integrations/{whatsapp|email}`, `POST /api/integrations/email/test`, `POST /api/integrations/api-key` (key shown once, stored hashed), `POST /api/integrations/webhook-secret/rotate`.

## Analytics
`GET /api/analytics/overview` -> `totals, rates, daily (14d), weekly (8w), leads_by_status, conversations_by_channel`. Test-channel conversations are excluded.

## Public endpoints
| Path | Auth | Notes |
|---|---|---|
| `GET /api/public/widget-config?key=` | public key | name + greeting |
| `POST /api/public/chat` | public key in body | `{key, session_id, message, name?, email?}` |
| `GET /api/public/chat/poll` | public key | human replies for a session |
| `POST /api/public/v1/chat` | `X-API-Key` | `{session_id, message}` |
| `POST /api/public/v1/leads` | `X-API-Key` | `{name?, email?, phone?, company?, interest?, requirements?, budget?}` |

## Inbound webhooks
- WhatsApp: `GET/POST /api/webhooks/whatsapp/{public_key}` (verification + messages; `X-Hub-Signature-256` checked when an app secret is saved).
- n8n (header `X-Webhook-Secret`): `GET /api/webhooks/n8n/due-follow-ups`, `POST /api/webhooks/n8n/lead-update` `{lead_id, status?, qualification?, score?, notes?}`, `POST /api/webhooks/n8n/follow-up-complete` `{follow_up_id}`.

## System
`GET /health` -> `{status, database, ai_configured}` (503 when the database is unreachable).
