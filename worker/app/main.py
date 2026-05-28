import logging
import os
import signal
import socket
import sys
import time

import redis
from openai import OpenAIError
from redis.exceptions import ResponseError

from . import circuit
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


def _retry_key(job_id: str) -> str:
    return f"job_retries:{job_id}"


def _update_status(r: redis.Redis, job_id: str, **fields) -> None:
    if not job_id:
        return
    key = _status_key(job_id)
    r.hset(key, mapping={k: str(v) for k, v in fields.items()})
    r.expire(key, settings.status_ttl)


def _handle_failure(
    r: redis.Redis,
    job_id: str,
    fields: dict,
    msg_id: str,
    error: BaseException,
) -> None:
    """Increment per-job retry counter; re-enqueue or dead-letter; always XACK."""
    attempts = int(r.incr(_retry_key(job_id))) if job_id else settings.max_deliveries
    if job_id:
        r.expire(_retry_key(job_id), settings.status_ttl)

    err_repr = repr(error)[:500]

    if attempts >= settings.max_deliveries:
        log.error(
            "job %s exceeded max deliveries (%d); dead-lettering to %s",
            job_id, attempts, settings.dead_stream,
        )
        r.xadd(
            settings.dead_stream,
            {**fields, "reason": err_repr, "attempts": str(attempts)},
        )
        _update_status(
            r, job_id,
            status="dead",
            attempts=attempts,
            error=err_repr,
            failed_at=int(time.time()),
        )
    else:
        log.warning(
            "job %s failed (attempt %d/%d); re-enqueueing",
            job_id, attempts, settings.max_deliveries,
        )
        r.xadd(settings.ingest_stream, fields)
        _update_status(
            r, job_id,
            status="retrying",
            attempts=attempts,
            error=err_repr,
        )

    r.xack(settings.ingest_stream, settings.consumer_group, msg_id)


def _requeue_for_breaker(r: redis.Redis, fields: dict, msg_id: str) -> None:
    """Circuit opened mid-batch: put message back on the queue, ack original."""
    r.xadd(settings.ingest_stream, fields)
    r.xack(settings.ingest_stream, settings.consumer_group, msg_id)


def run():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    r = redis.Redis.from_url(settings.valkey_url, decode_responses=True)
    ensure_group(r)
    log.info(
        "worker %s ready (stream=%s group=%s dead=%s)",
        CONSUMER_NAME,
        settings.ingest_stream,
        settings.consumer_group,
        settings.dead_stream,
    )

    while _running:
        # Guard rail: if the breaker is open, don't pull any new jobs.
        if circuit.is_open(r):
            remaining = circuit.seconds_until_close(r)
            sleep_s = 5 if remaining < 0 else min(max(remaining, 1), 10)
            log.info("circuit open; sleeping %ds before re-checking", sleep_s)
            time.sleep(sleep_s)
            continue

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

                # Re-check breaker between messages — long batches can span
                # the moment the breaker opens.
                if circuit.is_open(r):
                    log.info("circuit opened mid-batch; re-enqueueing %s", msg_id)
                    _requeue_for_breaker(r, fields, msg_id)
                    continue

                started = int(time.time())
                _update_status(
                    r, job_id,
                    status="processing",
                    consumer=CONSUMER_NAME,
                    started_at=started,
                )
                try:
                    summary = process_job(fields)
                except OpenAIError as e:
                    log.exception("openai error on %s; recording breaker failure", msg_id)
                    circuit.record_failure(
                        r,
                        threshold=settings.circuit_fail_threshold,
                        cooldown_s=settings.circuit_cooldown_s,
                    )
                    _handle_failure(r, job_id, fields, msg_id, e)
                    continue
                except Exception as e:
                    log.exception("non-openai error on %s; will retry/DLQ", msg_id)
                    _handle_failure(r, job_id, fields, msg_id, e)
                    continue

                # Success path
                circuit.record_success(r)
                if job_id:
                    r.delete(_retry_key(job_id))
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

    log.info("worker %s exiting", CONSUMER_NAME)


if __name__ == "__main__":
    try:
        run()
    except Exception:
        log.exception("fatal error")
        sys.exit(1)
