# Environment variables
Loaded from the process environment or `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `production` enforces a non-default `SECRET_KEY` |
| `SECRET_KEY` | dev value | Signs JWTs and derives the key that encrypts stored integration secrets. Rotating it invalidates sessions and stored WhatsApp/SMTP/auth-header secrets |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | JWT lifetime |
| `DATABASE_URL` | `sqlite:///./dev.db` | PostgreSQL URL (`postgres://` and `postgresql://` are accepted) |
| `AUTO_CREATE_TABLES` | `false` | Creates tables on startup (tests only). Use Alembic otherwise |
| `GROQ_API_KEY` | empty | Enables the AI agents and RAG answers |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model name |
| `EMBEDDING_PROVIDER` | `auto` | `auto`, `sentence-transformers`, or `hashing` (no ML dependency) |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Model name |
| `VECTOR_DIR` | `./data/vectors` | FAISS index files (needs a persistent disk in production) |
| `MAX_UPLOAD_MB` | `10` | Upload size cap |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `800` / `120` | Chunking (characters) |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Used for widget snippet and webhook URLs shown in the UI |
| `CORS_ORIGINS` | empty | Comma-separated origins if the frontend is hosted separately. `/api/public/*` is always open for the widget |
| `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASSWORD` `SMTP_FROM` `SMTP_USE_TLS` | empty/587/true | Server-wide email (per-business SMTP overrides it) |
| `ALLOW_PRIVATE_WEBHOOK_TARGETS` | `true` | Set `false` on public hosting to block SSRF to private IPs (this also blocks a local n8n) |
| `ASYNC_DISPATCH` | `true` | Deliver webhooks/emails in background threads |
| `RATE_LIMIT_ENABLED` | `true` | In-memory per-IP limits (per process) |
| `LOG_LEVEL` | `INFO` | Logging level |
