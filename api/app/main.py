import logging
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import select

from .auth.security import hash_password
from .config import settings
from .db import engine, session_scope
from .deps import ensure_collection
from .models import Base, User
from .routers import auth, chat, history, ingest, ops, query, admin_quality

log = logging.getLogger("api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


def _bootstrap_db() -> None:
    """Create SQLite directory + tables + initial admin if configured."""
    if settings.db_url.startswith("sqlite:///"):
        db_path = settings.db_url.replace("sqlite:///", "", 1)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(engine)

    if not settings.admin_mobile or not settings.admin_password:
        log.info("ADMIN_MOBILE/ADMIN_PASSWORD not set; skipping admin bootstrap")
        return

    with session_scope() as db:
        any_admin = db.scalar(select(User).where(User.role == "admin"))
        if any_admin:
            log.info("admin already present (id=%s); skipping bootstrap", any_admin.id)
            return

        from .auth.security import normalize_mobile
        mobile = normalize_mobile(settings.admin_mobile)
        existing = db.scalar(select(User).where(User.mobile == mobile))
        if existing:
            existing.role = "admin"
            log.info("promoted existing user %s to admin", mobile)
        else:
            db.add(User(
                mobile=mobile,
                name=settings.admin_name or "Admin",
                password_hash=hash_password(settings.admin_password),
                role="admin",
            ))
            log.info("created admin user %s", mobile)


@asynccontextmanager
async def lifespan(_: FastAPI):
    _bootstrap_db()
    ensure_collection()
    yield


app = FastAPI(title="rag-asyncq api", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(ingest.router)
app.include_router(query.router)
app.include_router(chat.router)
app.include_router(history.router)
app.include_router(ops.router)
app.include_router(admin_quality.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "worker": socket.gethostname(), "pid": os.getpid()}
