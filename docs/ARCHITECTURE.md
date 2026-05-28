# From sync RAG → async distributed RAG

A walk-through of how your existing synchronous RAG system at
`/home/sumanta/new-workdrive/agentic_ai/rag_system/` maps onto the
async/queue/worker architecture in this repo, and what changes in *behaviour*
when we make that jump.

---

## 1. The sync system you have today

Two scripts, one Qdrant container, no queue:

```
index_pdf.py   ─┐
                ├── reads node.pdf
                ├── splits with RecursiveCharacterTextSplitter (1500 / 300)
                ├── embeds with OpenAIEmbeddings("text-embedding-3-large")
                └── writes to Qdrant collection "learning_langchain"

chat_pdf.py    ─┐
                ├── reads input() from terminal
                ├── MMR search (k=6, fetch_k=20) on the same collection
                ├── builds a context string with page numbers + source
                └── calls OpenAI gpt-5 via open_ai_connect.get_response()
```

**Why this is "sync":** everything happens inline. When you run `index_pdf.py`
the process is blocked until OpenAI returns every embedding and Qdrant
acknowledges every upsert. If the PDF is 500 pages, your terminal sits idle
the whole time. There is exactly one of each thing — one indexer, one chatter,
one DB.

**What's good about it (and worth preserving):**

| Piece | Why we keep it |
|---|---|
| `PyMuPDFLoader` | Good text extraction, preserves `page` and `source` metadata |
| `RecursiveCharacterTextSplitter(1500, 300, separators=["\n## ", ...])` | Tuned for your PDFs; honors Markdown headings |
| `OpenAIEmbeddings("text-embedding-3-large")` | 3072-dim, matches collection on Qdrant side |
| `add_start_index=True` | Keeps the character offset in metadata — useful for citations |
| MMR retrieval (`max_marginal_relevance_search`, k=6, fetch_k=20) | Diversifies results; better than raw cosine top-k |
| The Baymax system prompt | Behaviour-defining; should not change in the migration |
| `gpt-5` for the final answer | Model choice is independent of the storage architecture |

These are **business logic**. The async migration must not change any of them.
Everything below is purely about *where* each step runs.

---

## 2. The async architecture in this repo

Same building blocks, redistributed across processes and replicas, with a
queue in the middle and a load balancer in front.

```
                  Local network (192.168.x.x)
                            │
                            ▼
                  ┌──────────────────┐
                  │ Nginx :80        │   Container 3
                  │ reverse proxy    │   round-robins to FastAPI replicas
                  └────────┬─────────┘
                           │ proxy_pass http://api:8000
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   ┌─────────┐        ┌─────────┐        ┌─────────┐
   │ FastAPI │        │ FastAPI │        │ FastAPI │   api × 3 replicas
   │  api 1  │        │  api 2  │        │  api 3  │   /ingest /query /embed
   └────┬────┘        └────┬────┘        └────┬────┘
        │                  │                  │
        │ XADD             │ XADD             │ XADD ingest_jobs (job_id, path, …)
        ▼                  ▼                  ▼
              ┌────────────────────────┐
              │ Valkey :6379           │   Container 2
              │ stream "ingest_jobs"   │   consumer group "ingest_workers"
              │ + cache + pub/sub      │
              └────────┬───────────────┘
                       │ XREADGROUP
            ┌──────────┴──────────┐
            ▼                     ▼
       ┌─────────┐           ┌─────────┐
       │ worker  │           │ worker  │   worker × 2 replicas
       │   A     │           │   B     │   chunk · embed · upsert
       └────┬────┘           └────┬────┘
            │ upsert points       │
            ▼                     ▼
              ┌────────────────────────┐
              │ Qdrant :6333           │   Container 1
              │ collection "documents" │   HNSW · cosine · 3072 dims
              └────────────────────────┘
                       ▲
                       │ similarity search (direct, no queue)
                       └────────── FastAPI api (on /query) ─┘
```

All containers sit on a Docker bridge network called **`rag-net`**, so they
address each other by service name (`api`, `valkey`, `qdrant`).

### What each container does

| Container | Image | Role |
|---|---|---|
| **Container 1 — Qdrant** | `qdrant/qdrant:v1.12.4` | Vector store. HNSW index, cosine distance, 3072 dims (matches `text-embedding-3-large`). |
| **Container 2 — Valkey** | `valkey/valkey:8.0-alpine` | Job queue (Streams), cache, pub/sub. Open-source Redis fork; same protocol. |
| **Container 3 — Nginx** | `nginx:1.27-alpine` | Reverse proxy + load balancer. Round-robins requests across the API replicas. |
| **FastAPI api (×3)** | built from `./api` | Stateless HTTP layer. Handles `/ingest`, `/query`, `/embed`. Owns nothing; can be killed any time. |
| **Background worker (×2)** | built from `./worker` | Long-running consumer. Pops jobs from the Valkey stream, does the heavy work (chunk → embed → upsert). |

### Why split api and worker?

This is the single biggest difference from your sync system, so it's worth
spelling out:

- **HTTP requests should never block on slow work.** Embedding a 500-page PDF
  via OpenAI can take minutes. If the user's HTTP client times out, the work
  is wasted. So `/ingest` does **only** the cheap, fast part: save the file,
  push a job onto the queue, return a `job_id`. Total time: milliseconds.
- **Slow work needs its own pool.** Workers are sized independently — if
  ingestion backs up, you `--scale worker=8` without touching the API tier.
- **At-least-once delivery.** If a worker crashes mid-job, Valkey Streams
  remembers the message (it stays in the Pending Entries List until ack'd).
  Another worker picks it up. Your sync `index_pdf.py` had no such safety net
  — a crash meant restart from scratch.

---

## 3. Mapping the sync code onto async components

This is the literal "where does each line of your existing code end up" table.

| Sync code (in `rag_system/`) | Async equivalent (in this repo) |
|---|---|
| `PyMuPDFLoader(file_path=pdf_path).load()` | [worker/app/chunker.py](../worker/app/chunker.py) — runs **inside the worker**, after the PDF arrives via the shared volume |
| `RecursiveCharacterTextSplitter(...)` | Same file, same call — moved into the worker |
| `OpenAIEmbeddings("text-embedding-3-large")` for indexing | [worker/app/pipeline.py](../worker/app/pipeline.py) `_embedder()` |
| `OpenAIEmbeddings(...)` for query | [api/app/deps.py](../api/app/deps.py) `get_embedder()` — embedding a single query is fast, no need to queue it |
| `QdrantVectorStore.from_documents(...)` (the indexer write) | [worker/app/pipeline.py](../worker/app/pipeline.py) `process_job()` — now an explicit `qdrant.upsert(PointStruct, …)` so we control IDs and payload shape |
| `QdrantVectorStore.from_existing_collection(...)` (the chatter read) | [api/app/routers/query.py](../api/app/routers/query.py) — direct `qdrant.search(...)` for the same reason: explicit control |
| `vector_db.max_marginal_relevance_search(query, k=6, fetch_k=20)` | **Not yet ported** — currently `/query` does plain cosine top-k. Easy upgrade (see §6). |
| `chat_pdf.py` building context + calling `gpt-5` | **Not yet ported** — `/query` returns hits only. Adding the LLM step is one of the next iterations (see §6). |
| `index_pdf.py` running once on `node.pdf` | Replaced by `POST /ingest` accepting any PDF over HTTP, enqueuing a job per file. The worker loop runs forever. |
| `terminal input()` (chat) | Replaced by `POST /query` JSON body. Same prompt, just over HTTP. |
| `docker-compose.yml` (one service: vector-db) | [docker-compose.yml](../docker-compose.yml) — five services, one network, three named volumes. |

**Bottom line:** every piece of *logic* in your sync code has a home in the
async system. The migration is **redistribution, not rewrite**.

---

## 4. End-to-end walk-throughs

### 4a. Ingest path — what happens when a user uploads a PDF

```
1. Browser ── POST /ingest (multipart, file=doc.pdf) ──▶ Nginx :80
2. Nginx round-robins to one of api1/api2/api3.
3. The chosen FastAPI replica:
     a. validates it's a .pdf
     b. generates job_id = uuid4().hex
     c. streams the upload to /data/ingest/<job_id>.pdf
        (this path lives on the shared `ingest_data` Docker volume,
         mounted into BOTH api and worker containers)
     d. XADD ingest_jobs { job_id, path, filename, metadata }
     e. returns 200 { job_id, stream_id } in milliseconds
4. One of the workers (A or B) is blocked on XREADGROUP. Valkey hands
   the message to ONE of them (consumer group guarantees exclusivity).
5. The chosen worker:
     a. PyMuPDFLoader.load()          ← same as your index_pdf.py
     b. RecursiveCharacterTextSplitter.split_documents()
     c. OpenAIEmbeddings.embed_documents(chunks)  ← one API call, batched
     d. qdrant.upsert(PointStruct(id, vector, payload))
     e. XACK ingest_jobs ingest_workers <stream_id>
6. If step 5 raised: the message stays in the Pending Entries List.
   On restart (or via XCLAIM), another worker retries.
```

**Why this is better than the sync version:**

- The HTTP client gets a response in milliseconds, not minutes.
- Two PDFs uploaded back-to-back get processed *in parallel* (one per worker).
- Killing a worker mid-job loses no data — the message is still pending.
- Scaling is a CLI flag away: `docker compose up -d --scale worker=8`.

### 4b. Query path — what happens when a user asks a question

```
1. Browser ── POST /query {query: "what is X?", top_k: 6} ──▶ Nginx :80
2. Nginx round-robins to a FastAPI replica.
3. That replica:
     a. embedder.embed_query(text)            ← one OpenAI call, ~50–200 ms
     b. qdrant.search(collection, vector, top_k)   ← few ms
     c. returns hits (id, score, payload)
```

Query is **synchronous on purpose** — it's already fast (sub-second), and the
user is literally waiting on the HTTP response. There's no benefit to
queuing it, and a queue would only add latency.

The dashed line in your diagram ("FastAPI Worker 3 → Qdrant: vector search")
is exactly this — the API tier talks to Qdrant directly, bypassing Valkey.

---

## 5. Component glossary

### Valkey Streams (the queue)

Streams are an append-only log inside Valkey/Redis. We use three features:

- `XADD <stream> <fields>` — append a job. Returns a stream ID like
  `1709654321000-0`. This is what `/ingest` does.
- `XREADGROUP GROUP <group> <consumer> COUNT n BLOCK ms STREAMS <stream> >` —
  blocking read. Multiple consumers in the same group share work; each
  message goes to exactly one consumer.
- `XACK <stream> <group> <id>` — mark a message processed. Until ack'd, it
  sits in the Pending Entries List (PEL) and can be reclaimed by another
  consumer via `XCLAIM`.

This is why Streams are a better fit than plain Lists (`RPUSH`/`BLPOP`) for
ingestion: List entries vanish the moment they're popped, so a crash between
pop and "actually finished" loses data silently.

### The shared `ingest_data` volume

The PDF bytes themselves don't travel through Valkey — only the *path* does.
Both `api` and `worker` containers mount the same named volume at
`/data/ingest`. The API writes the file there; the worker reads it from the
same place. This keeps the queue messages tiny.

(Alternative architectures store the bytes in object storage like S3/MinIO
and pass an S3 URL — that's the cloud-native version. The shared volume is
the equivalent for a single-host Docker deployment.)

### Qdrant collection layout

```
name:    documents      (configurable via QDRANT_COLLECTION)
vectors: size=3072, distance=Cosine
payload: {
  job_id:   "abc123",
  source:   "doc.pdf",
  text:     "<chunk text>",
  page:     7,
  start_index: 1842,
  ... any extra metadata the caller passed
}
```

The collection is **auto-created on first API boot** by the lifespan hook in
[api/app/main.py](../api/app/main.py). Your sync system used the name
`learning_langchain`; the async system uses `documents` by default — change
`QDRANT_COLLECTION` in the env if you want to keep the old name and re-use
existing data.

### Why three FastAPI replicas?

- Embarrassingly stateless: every request is independent, so horizontal
  scaling is free.
- Connection pooling and OpenAI client init are amortised per-replica.
- A crashed replica only kills its in-flight requests; the others keep
  serving. Compose restarts it.

Three is just the diagram's number — you can run any count.

---

## 6. What's NOT done yet (and what was easy vs. hard)

The async scaffold has the **storage architecture** in place but stops short
of two pieces of your sync system. These are the next-iteration items:

### Easy ports (1–2 hours each)

1. **MMR retrieval** — your sync chat uses
   `max_marginal_relevance_search(k=6, fetch_k=20)`. The async `/query`
   currently uses plain cosine. Swap `qdrant_client.search()` for
   `qdrant_client.query_points(..., search_params=qmodels.SearchParams(...))`
   plus client-side MMR, or use the `langchain_qdrant.QdrantVectorStore`
   wrapper for parity.
2. **Splitter parity** — your sync splitter uses
   `chunk_size=1500, chunk_overlap=300, separators=["\n## ", "\n### ", ...], add_start_index=True`.
   The scaffold defaults to 1000/150 with generic separators. One-line fix in
   [worker/app/chunker.py](../worker/app/chunker.py) and
   [worker/app/config.py](../worker/app/config.py).
3. **Baymax `/chat` endpoint** — `chat_pdf.py`'s system prompt + `gpt-5` call
   becomes a new FastAPI route that calls `/query` internally, builds the
   context string, and forwards to `open_ai_connect.get_response`. This is
   the same code, just wrapped in an HTTP handler.

### Medium effort

4. **Job status tracking** — `/ingest/status/{job_id}` is currently a stub.
   Workers should `HSET job:<job_id> status=processing chunks=<n>` and update
   to `done` / `failed`. The API reads that hash.
5. **PEL claim loop** — a worker dying mid-job leaves the message pending
   forever unless someone calls `XCLAIM`. Add a periodic task that claims
   messages older than N seconds.

### Larger

6. **Auth on the API** — currently open. Add an API key header check in a
   FastAPI dependency.
7. **Streaming chat responses** — gpt-5 supports streaming; wire SSE through
   FastAPI → Nginx (Nginx needs `proxy_buffering off` for that location).

---

## 7. Quick reference — files in this repo

```
rag-asyncq-dist-worker/
├── docker-compose.yml            # 5 services, 1 network, 3 volumes
├── .env.example                  # OPENAI_API_KEY=...
├── README.md
├── docs/
│   └── ARCHITECTURE.md           # ← you are here
├── nginx/
│   └── nginx.conf                # reverse proxy + DNS-based upstream
├── api/                          # FastAPI image, runs as 3 replicas
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py               # FastAPI + lifespan (creates Qdrant collection)
│       ├── config.py             # env-driven settings
│       ├── deps.py               # cached redis / qdrant / embedder clients
│       └── routers/
│           ├── ingest.py         # POST /ingest      → save file + XADD
│           ├── query.py          # POST /query       → embed + qdrant.search
│           └── embed.py          # POST /embed       → utility passthrough
└── worker/                       # Worker image, runs as 2 replicas
    ├── Dockerfile
    ├── requirements.txt
    └── app/
        ├── main.py               # XREADGROUP loop, ack on success
        ├── config.py
        ├── chunker.py            # PyMuPDFLoader + RecursiveCharacterTextSplitter
        └── pipeline.py           # chunk → embed → qdrant.upsert
```

---

## 8. Summary in one paragraph

Your sync RAG is a *function call chain*: load → split → embed → store, all
inline. The async version cuts that chain in half: the **API tier** owns the
fast steps (accept upload, embed a query) and the **worker tier** owns the
slow steps (chunk a whole PDF, embed N chunks, upsert). A **Valkey stream**
is the hand-off between them, providing buffering, parallelism, and
at-least-once delivery. **Qdrant** stays exactly where it was — the same
collection, the same vectors. The only thing that fundamentally changed is
*who runs which line of code, and when*.
