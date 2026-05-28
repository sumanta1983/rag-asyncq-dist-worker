# rag-asyncq-dist-worker

Async distributed RAG with auth, admin-curated corpus, and a Next.js chat UI.

- **Admin** uploads PDFs through the web UI; ingest is queued on Valkey, workers
  chunk + embed (OpenAI `text-embedding-3-large`) + upsert to Qdrant.
- **Registered users** sign in with mobile + password and chat against the
  corpus using the Baymax prompt + gpt-5.
- Every query and job is logged in SQLite, tied to a user.
- An OpenAI **circuit breaker** keeps the system from burning quota when the
  upstream is unhealthy.

```
Browser ─▶ Nginx :80 ─┬─▶ /api/*  ──▶ FastAPI x3 ──▶ Valkey stream ──▶ Worker x2 ──▶ Qdrant
                     │                       └─▶ SQLite (users, queries, jobs)
                     └─▶ /        ──▶ Next.js (Login · Register · Chat · Admin)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full picture.

## Layout

```
api/        FastAPI app + auth + SQLite (3 replicas)
worker/     Background ingest consumer (2 replicas)
web/        Next.js 15 app (login, register, chat, /admin/ingest, /history)
nginx/      Reverse proxy: /api/* → FastAPI, everything else → Next.js
docs/       Architecture doc
docker-compose.yml
```

## Bring it up

```bash
cp .env.example .env
# In .env, set at minimum:
#   OPENAI_API_KEY
#   JWT_SECRET           (a long random string)
#   ADMIN_MOBILE         (e.g. +919999999999 — used for first-boot admin)
#   ADMIN_PASSWORD       (the admin password, min 8 chars)

docker compose up --build -d
docker compose ps
```

Open [http://localhost](http://localhost) — the home page redirects to `/login`.
The admin you set in `.env` can sign in immediately. New users can self-register
at `/register`.

## Roles

| Role  | Can do                                                    |
|-------|-----------------------------------------------------------|
| user  | `/register`, `/login`, `/chat`, `/history` (own queries)  |
| admin | everything above + `/admin/ingest` + `/circuit` + jobs log |

The first admin is created from `ADMIN_MOBILE` / `ADMIN_PASSWORD` on first boot
(idempotent — safe to keep these set across restarts; nothing happens if an
admin already exists).

## Endpoints

All API endpoints are mounted behind Nginx at `/api/*`. Auth is via
`Authorization: Bearer <token>` after `/auth/login` or `/auth/register`.

```
POST   /api/auth/register     {name, mobile, password, confirm_password}
POST   /api/auth/login        {mobile, password}
GET    /api/auth/me           current user

POST   /api/ingest            (admin)  multipart file=PDF
GET    /api/ingest/status/:id (admin)
POST   /api/query             MMR retrieval (no LLM)
POST   /api/chat              MMR + Baymax + gpt-5
GET    /api/history/queries   user's own past queries
GET    /api/history/jobs      (admin)  every ingest job

GET    /api/circuit           (admin)
POST   /api/circuit/disable   (admin)
POST   /api/circuit/enable    (admin)
GET    /healthz
```

## How upload works

**Admin uses the UI** at `/admin/ingest`: drag/select a PDF → click upload. The
page polls `/api/ingest/status/<job_id>` and shows the chunk count when the
worker finishes.

**Or via CLI** (admin token required):

```bash
TOKEN=$(curl -s -X POST http://localhost/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"mobile":"+919999999999","password":"…"}' | jq -r .access_token)

curl -F "file=@doc.pdf" -H "Authorization: Bearer $TOKEN" http://localhost/api/ingest
```

Regular users **cannot** call `/ingest` — they get `403 admin role required`.

## Guard rails (unchanged from previous iteration)

- **Circuit breaker**: 5 OpenAI failures → 60s open. Workers stop pulling jobs;
  `/chat` and `/query` return 503 with `Retry-After`. A single success resets.
- **Dead-letter queue**: after 3 failed attempts a job moves to
  `ingest_jobs_dead` and its SQLite/Valkey status becomes `dead`.
- **Manual kill switch**: `POST /api/circuit/disable` (admin) or
  `valkey-cli SET openai:disabled 1`.

## Scaling

```bash
docker compose up -d --scale api=5 --scale worker=4
```

Nginx resolves `api` and `web` via Docker's embedded DNS. SQLite is on a shared
volume in WAL mode — fine for this scale; swap to Postgres if you start seeing
write contention.

## Status

Implemented:
- Auth (register / login / JWT) + bcrypt password hashing
- SQLite (users, query_log, job_log) shared across api replicas
- Admin-only ingest + per-user query history + admin-only job history
- Next.js UI: login, register, chat, admin/ingest, history
- MMR retrieval + Baymax + gpt-5
- At-least-once delivery, per-job retry, dead-letter queue
- OpenAI circuit breaker + manual kill switch

Not yet:
- PEL-claim loop for messages stranded by a permanently dead worker
- SSE streaming for `/chat`
- Refresh tokens (current JWT lives 7 days)
- Tests
