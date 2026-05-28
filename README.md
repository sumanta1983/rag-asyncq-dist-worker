# rag-asyncq-dist-worker

Async distributed RAG with auth, admin-curated corpus, and a Next.js chat UI.

- **Admin** uploads PDFs through the web UI; ingest is queued on Valkey, workers
  chunk + **run ingestion quality checks** + embed (OpenAI `text-embedding-3-large`) + upsert to Qdrant.
- **Registered users** sign in with mobile + password and chat against the
  corpus using the Baymax prompt + gpt-5.
- Every query, job, **and ingestion quality report** is logged in SQLite, tied
  to a user / job.
- An OpenAI **circuit breaker** keeps the system from burning quota when the
  upstream is unhealthy.

```
Browser ─▶ Nginx :80 ─┬─▶ /api/*  ──▶ FastAPI x3 ──▶ Valkey stream ──▶ Worker x2 ──┬─▶ Qdrant (vectors)
                     │                       └─▶ SQLite (users, queries, jobs)    └─▶ SQLite (quality log)
                     └─▶ /        ──▶ Next.js (Login · Register · Chat · Admin)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full picture.
See [FullDoc.pdf](FullDoc.pdf) Explain Full Architecture in details.

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

| Role  | Can do                                                                            |
|-------|-----------------------------------------------------------------------------------|
| user  | `/register`, `/login`, `/chat`, `/history` (own queries)                          |
| admin | everything above + `/admin/ingest` + `/admin/ingestion-quality` + `/circuit` + jobs log |

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

POST   /api/ingest                          (admin)  multipart file=PDF
GET    /api/ingest/status/:id               (admin)
POST   /api/query                           MMR retrieval (no LLM)
POST   /api/chat                            MMR + Baymax + gpt-5
GET    /api/history/queries                 user's own past queries
GET    /api/history/jobs                    (admin)  every ingest job

GET    /api/admin/ingestion-quality         (admin)  paginated quality reports
GET    /api/admin/ingestion-quality/:job_id (admin)  reports for one job

GET    /api/circuit                         (admin)
POST   /api/circuit/disable                 (admin)
POST   /api/circuit/enable                  (admin)
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

## Ingestion quality checks

Before chunks are embedded and pushed to Qdrant, the worker runs each chunk
through a set of cheap text-quality checks ([worker/app/ingest_checks.py](worker/app/ingest_checks.py)):

- **Length**: too short (< 50 chars) or too long (> 1800 chars) → flagged.
- **Effectively empty after cleaning** (< 30 chars after whitespace collapse).
- **Lexical diversity**: only checked if ≥ 20 words. If unique-word ratio
  falls below 35 %, the chunk is flagged as low-diversity / repetitive.
- **Duplicate detection**: chunks with identical normalised text (md5 of
  whitespace-collapsed content) are dropped on the second occurrence.
- **Non-ASCII noise** (off by default — Bengali/Hindi PDFs would be wrongly
  rejected; flip `QUALITY_ENABLE_ASCII_NOISE_CHECK=true` to enable).

Per-job a report row is written to the `ingestion_quality_log` table:

| Column | Meaning |
|---|---|
| `job_id`, `filename` | Identifies the upload |
| `original_chunks` | What the splitter produced |
| `checked_chunks` | How many ran through the validator |
| `kept_chunks` | Survived into Qdrant |
| `rejected_chunks` | Failed quality (dropped if `QUALITY_DROP_BAD=true`) |
| `duplicate_chunks` | Identical-hash dupes within the same job |
| `quality_passed` | `True` when no rejects or duplicates |
| `issues_json` | Issue → count summary |
| `sample_issues_json` | First 5 problem chunks with page + preview |

Admins view this at **`/admin/ingestion-quality`** in the Next.js UI
(table with: Time · File · Job ID · Original · Kept · Rejected · Duplicates · Status)
or via the REST endpoints listed above.

Tunable via worker env vars:

```
QUALITY_MIN_LEN=50                         # min chars per chunk
QUALITY_DROP_BAD=true                      # drop rejects vs. keep & flag
QUALITY_DEDUPE=true                        # dedupe by content hash
QUALITY_ENABLE_ASCII_NOISE_CHECK=false     # enable for English-only corpora
```

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
- SQLite (users, query_log, job_log, **ingestion_quality_log**) shared across api & worker
- Admin-only ingest + per-user query history + admin-only job history
- **Per-chunk ingestion quality validation + per-job quality report stored in SQLite**
- Next.js UI: login, register, chat, admin/ingest, **admin/ingestion-quality**, history
- MMR retrieval + Baymax + gpt-5
- At-least-once delivery, per-job retry, dead-letter queue
- OpenAI circuit breaker + manual kill switch

Not yet:
- PEL-claim loop for messages stranded by a permanently dead worker
- SSE streaming for `/chat`
- Refresh tokens (current JWT lives 7 days)
- Tests
