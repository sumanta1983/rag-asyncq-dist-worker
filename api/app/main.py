import os
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .deps import ensure_collection
from .routers import chat, ingest, query
# from .routers import chat, embed, ingest, query


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_collection()
    yield


app = FastAPI(title="rag-asyncq api", lifespan=lifespan)

app.include_router(ingest.router)
app.include_router(query.router)
app.include_router(chat.router)
# app.include_router(embed.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "worker": socket.gethostname(), "pid": os.getpid()}
