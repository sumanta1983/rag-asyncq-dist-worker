# rag-asyncq-dist-worker

Async distributed RAG. Behaves like
[`agentic_ai/rag_system`](file:///home/sumanta/new-workdrive/agentic_ai/rag_system)
(PyMuPDF · `text-embedding-3-large` · MMR retrieval · Baymax prompt · gpt-5),
but split across a load-balanced API tier and a queued worker tier so
ingestion is non-blocking and horizontally scalable.

```
Browser ─▶ Nginx :80 ─▶ FastAPI x3 ─▶ Valkey stream ─▶ Worker x2 ─▶ Qdrant
                                  └────── /query, /chat: direct Qdrant ─┘
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

## Layout

```
api/        FastAPI app — runs as 3 replicas behind Nginx
worker/     Background consumer — runs as 2 replicas, pulls from Valkey stream
nginx/      Reverse proxy + load balancer
docs/       Architecture doc
docker-compose.yml
```

## Bring it up

```bash
cp .env.example .env       # put your real OPENAI_API_KEY in here
docker compose up --build -d
docker compose ps
```

Exposed host ports:
- `80`  — Nginx (entrypoint)
- `6333` / `6334` — Qdrant REST / gRPC (inspection)
- `6379` — Valkey (inspection)

## Endpoints (via Nginx)

```bash
# Health
curl http://localhost/healthz

# Ingest a PDF (returns immediately with a job_id)
curl -F "file=@/path/to/doc.pdf" http://localhost/ingest

# Check ingest progress
curl http://localhost/ingest/status/<job_id>

# Retrieve chunks (MMR, k=6 fetch_k=20 by default — matches sync chat_pdf.py)
curl -X POST http://localhost/query \
     -H 'Content-Type: application/json' \
     -d '{"query":"what does the document say about X?"}'

# Full Baymax chat (MMR retrieval → gpt-5 with the sync system's prompt)
curl -X POST http://localhost/chat \
     -H 'Content-Type: application/json' \
     -d '{"query":"summarise section 3"}'

# Embed utility
curl -X POST http://localhost/embed \
     -H 'Content-Type: application/json' \
     -d '{"texts":["hello world"]}'
```

## Scaling

```bash
docker compose up -d --scale api=5 --scale worker=4
```

Nginx resolves `api` via Docker's embedded DNS, so new replicas join the
upstream pool automatically. Workers join the `ingest_workers` consumer group
on the `ingest_jobs` stream — at-least-once delivery with per-message ack.

## Parity with the sync system

| Sync (`rag_system/`) | Async (this repo) |
|---|---|
| `PyMuPDFLoader` | [worker/app/chunker.py](worker/app/chunker.py) |
| `RecursiveCharacterTextSplitter(1500, 300, sep=…, add_start_index=True)` | same, in [worker/app/chunker.py](worker/app/chunker.py) |
| `OpenAIEmbeddings("text-embedding-3-large")` | both [api/app/deps.py](api/app/deps.py) and [worker/app/pipeline.py](worker/app/pipeline.py) |
| `QdrantVectorStore.from_documents(...)` | [worker/app/pipeline.py](worker/app/pipeline.py) `add_documents()` |
| Collection `learning_langchain` | same (configurable via `QDRANT_COLLECTION`) |
| `max_marginal_relevance_search(k=6, fetch_k=20)` | [api/app/routers/query.py](api/app/routers/query.py) and [api/app/routers/chat.py](api/app/routers/chat.py) |
| Baymax system prompt + `gpt-5` | [api/app/routers/chat.py](api/app/routers/chat.py) |
| Terminal `input()` | `POST /chat` JSON body |
| Single `index_pdf.py` invocation on `node.pdf` | `POST /ingest` + background worker |

## Job lifecycle

```
POST /ingest                              → status: queued
worker picks message off the stream       → status: processing
worker finishes upsert + XACK             → status: done     (chunks=N, duration_s=…)
worker raises, attempt < max_deliveries   → status: retrying (re-enqueued)
worker raises, attempt ≥ max_deliveries   → status: dead     (moved to ingest_jobs_dead)
```

Status hashes live at `job:<job_id>` in Valkey with a 24h TTL.
Retry counters live at `job_retries:<job_id>` (same TTL).

## Guard rails

### OpenAI circuit breaker
After **5 consecutive OpenAI failures**, the breaker opens for **60 seconds**.
While open:
- `/query` and `/chat` return `503 Service Unavailable` with a `Retry-After` header.
- Workers stop pulling new jobs from `ingest_jobs` (existing jobs stay durably
  queued — no data loss). Any message already pulled when the breaker opens
  is re-enqueued and ack'd so another worker can pick it up post-recovery.
- A single successful call resets the failure counter.

Tunable in env: `CIRCUIT_FAIL_THRESHOLD`, `CIRCUIT_COOLDOWN_S`.

### Dead-letter queue
A job that fails **3 times** moves to the `ingest_jobs_dead` stream and its
status becomes `dead`. One poison PDF can't keep tripping the breaker.

Tunable in env: `MAX_DELIVERIES`, `DEAD_STREAM`.

### Ops endpoints
```bash
curl http://localhost/circuit                # show breaker state
curl -X POST http://localhost/circuit/disable  # force open (maintenance)
curl -X POST http://localhost/circuit/enable   # clear override + reset counters
```

You can also poke Valkey directly:
```bash
docker compose exec valkey valkey-cli SET openai:disabled 1     # kill switch
docker compose exec valkey valkey-cli DEL openai:disabled openai:circuit_open_until openai:fail_count
docker compose exec valkey valkey-cli XLEN ingest_jobs_dead     # how many poison jobs
```

## Status

Implemented:
- All endpoints (`/ingest`, `/ingest/status`, `/query`, `/chat`, `/circuit`, `/healthz`)
- MMR retrieval, Baymax + gpt-5
- At-least-once delivery via Valkey consumer groups
- Per-job status + retry tracking
- OpenAI circuit breaker + manual kill switch
- Dead-letter queue for poison messages

Not yet:
- PEL-claim loop for messages stranded by a permanently dead worker (currently
  retry-by-re-enqueue handles ordinary failures; PEL claim would handle workers
  that crash mid-job without raising an exception we can catch)
- Auth on the API
- SSE streaming for `/chat`
- Tests
