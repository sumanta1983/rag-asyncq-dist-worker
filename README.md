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
worker finishes upsert + XACK             → status: done   (chunks=N, duration_s=…)
worker raises an exception                → status: failed (error=…, NOT XACK'd → retryable)
```

Status hashes live at `job:<job_id>` in Valkey with a 24h TTL.

## Status

Implemented:
- All endpoints (`/ingest`, `/ingest/status`, `/query`, `/chat`, `/embed`, `/healthz`)
- MMR retrieval, Baymax + gpt-5
- At-least-once delivery via Valkey consumer groups
- Per-job status tracking

Not yet:
- PEL-claim loop for messages stranded by a permanently dead worker
- Auth on the API
- SSE streaming for `/chat`
- Tests
