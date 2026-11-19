# Deployment

## GitHub upload
```powershell
cd AI_Business_Automation_Platform
git init
git add .
git status                      # confirm .env and *.db are NOT listed
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USER/ai-business-platform.git
git push -u origin main
```
`.gitignore` already excludes `.env`, databases, vector data and virtualenvs.

## Render
1. Push to GitHub. In Render choose **New -> Blueprint** and select the repo (uses `render.yaml`: web service + PostgreSQL + 1 GB disk for FAISS at `/var/data`).
2. When prompted set `GROQ_API_KEY` and `PUBLIC_BASE_URL` (e.g. `https://ai-business-platform.onrender.com`). `SECRET_KEY` is generated. SMTP variables are optional.
3. Build: `pip install -r requirements.txt`. Start: `alembic upgrade head && gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 1 ...`. Health check: `/health`.
4. Persistent disks need a paid instance. If the FAISS files are lost (e.g. free instance redeploy), each business's index is rebuilt automatically from the chunks stored in PostgreSQL on its next search or upload (covered by a test); re-embedding large knowledge bases takes a moment.
5. Memory: loading PyTorch needs roughly 1 GB RAM. On small instances set `EMBEDDING_PROVIDER=hashing`.
6. The frontend is served by the same service at `/`. To host it separately, copy `frontend/` to a static host, change `fetch("/api...")` in `js/api.js` to your API origin and set `CORS_ORIGINS`.
7. Set `ALLOW_PRIVATE_WEBHOOK_TARGETS=false` (already in `render.yaml`); your n8n must then be reachable at a public URL.

## <a name="n8n"></a>n8n
1. In n8n: Workflows -> Import from file -> each file in `n8n_workflows/`.
2. In each workflow replace `https://YOUR-APP-URL` and `YOUR_WEBHOOK_SECRET` (dashboard -> Automations shows the secret) and choose your SMTP credential / addresses in the email nodes.
3. Activate the workflow and copy its **production** webhook URL (`.../webhook/ai-new-lead`, `ai-lead-qualification`, `ai-human-escalation`, `ai-email-notification`).
4. Dashboard -> Automations -> New automation: pick the matching event and paste the URL. Use **Send test** to verify delivery (the log shows the HTTP status).
5. `02_automated_customer_followups` polls `/api/webhooks/n8n/due-follow-ups` every 15 minutes, emails customers, and marks follow-ups done.
Local n8n (`http://localhost:5678`) works when `ALLOW_PRIVATE_WEBHOOK_TARGETS=true`.

## <a name="whatsapp"></a>WhatsApp Business Cloud API
1. Create a Meta developer app with the WhatsApp product; note the **Phone number ID** and a permanent **access token**.
2. Dashboard -> Integrations -> WhatsApp: enter phone number ID, token, a verify token of your choice, and (recommended) the app secret.
3. In Meta -> WhatsApp -> Configuration, set the callback URL shown on the Integrations page and the same verify token; subscribe to `messages`.
4. Message the number. Customers and conversations appear in the dashboard; human replies from Conversations are sent via WhatsApp. Messages outside Meta's 24-hour window require approved templates (not implemented).

## Email
Integrations -> Email (SMTP) or server-wide `SMTP_*` variables. Use **Send test email**. Notification emails go to the business's *Notification email* (Business settings).

## Website chat widget
Copy the snippet from Integrations into your site. It needs the app's public URL in `PUBLIC_BASE_URL`.
