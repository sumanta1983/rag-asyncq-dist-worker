import logging
import os
import signal
import socket
import sys
import time

import redis
from redis.exceptions import ResponseError

from .config import settings
from .pipeline import process_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("worker")

CONSUMER_NAME = f"{socket.gethostname()}-{os.getpid()}"

_running = True


def _stop(*_):
    global _running
    _running = False
    log.info("shutdown signal received; finishing current batch")


def ensure_group(r: redis.Redis):
    try:
        r.xgroup_create(
            name=settings.ingest_stream,
            groupname=settings.consumer_group,
            id="$",
            mkstream=True,
        )
        log.info(
            "created consumer group %s on %s",
            settings.consumer_group,
            settings.ingest_stream,
        )
    except ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def _status_key(job_id: str) -> str:
    return f"job:{job_id}"


def _update_status(r: redis.Redis, job_id: str, **fields) -> None:
    if not job_id:
        return
    key = _status_key(job_id)
    r.hset(key, mapping={k: str(v) for k, v in fields.items()})
    r.expire(key, settings.status_ttl)


def run():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    r = redis.Redis.from_url(settings.valkey_url, decode_responses=True)
    ensure_group(r)
    log.info(
        "worker %s ready (stream=%s group=%s)",
        CONSUMER_NAME,
        settings.ingest_stream,
        settings.consumer_group,
    )

    while _running:
        try:
            resp = r.xreadgroup(
                groupname=settings.consumer_group,
                consumername=CONSUMER_NAME,
                streams={settings.ingest_stream: ">"},
                count=settings.read_batch,
                block=settings.block_ms,
            )
        except Exception:
            log.exception("xreadgroup failed; backing off")
            time.sleep(2)
            continue

        if not resp:
            continue

        for _stream, messages in resp:
            for msg_id, fields in messages:
                job_id = fields.get("job_id", "")
                started = int(time.time())
                _update_status(
                    r, job_id,
                    status="processing",
                    consumer=CONSUMER_NAME,
                    started_at=started,
                )
                try:
                    summary = process_job(fields)
                    finished = int(time.time())
                    _update_status(
                        r, job_id,
                        status="done",
                        chunks=summary.get("chunks", 0),
                        finished_at=finished,
                        duration_s=finished - started,
                    )
                    log.info("processed %s: %s", msg_id, summary)
                    r.xack(settings.ingest_stream, settings.consumer_group, msg_id)
                except Exception as e:
                    log.exception("job %s failed; leaving unacked for retry", msg_id)
                    _update_status(
                        r, job_id,
                        status="failed",
                        error=repr(e)[:500],
                        failed_at=int(time.time()),
                    )

    log.info("worker %s exiting", CONSUMER_NAME)


if __name__ == "__main__":
    try:
        run()
    except Exception:
        log.exception("fatal error")
        sys.exit(1)
