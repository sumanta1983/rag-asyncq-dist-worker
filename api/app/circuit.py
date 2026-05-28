"""Shared OpenAI circuit breaker.

Three Valkey keys back this:
  openai:fail_count          (counter, TTL = 2 * cooldown)
  openai:circuit_open_until  (unix-ts, TTL = cooldown — exists only while open)
  openai:disabled            (manual override; "1" forces the circuit open)

The same module lives in worker/app/circuit.py (intentional duplicate — small
enough that adding a shared package isn't worth it yet).
"""

from __future__ import annotations

import time

import redis

FAIL_KEY = "openai:fail_count"
OPEN_KEY = "openai:circuit_open_until"
DISABLED_KEY = "openai:disabled"


def is_open(r: redis.Redis) -> bool:
    if r.get(DISABLED_KEY) == "1":
        return True
    return r.exists(OPEN_KEY) == 1


def seconds_until_close(r: redis.Redis) -> int:
    if r.get(DISABLED_KEY) == "1":
        return -1  # manually disabled, no auto-close
    ttl = r.ttl(OPEN_KEY)
    return ttl if ttl and ttl > 0 else 0


def record_success(r: redis.Redis) -> None:
    # Clear the failure counter on any success; if the circuit was open and
    # cooled down, the call that just succeeded is the probe — leave the
    # OPEN_KEY alone (it'll expire on its own TTL).
    r.delete(FAIL_KEY)


def record_failure(r: redis.Redis, *, threshold: int, cooldown_s: int) -> int:
    count = int(r.incr(FAIL_KEY))
    # Hold the counter for 2x cooldown so a single failure after cooldown
    # re-opens the breaker immediately (half-open semantics).
    r.expire(FAIL_KEY, cooldown_s * 2)
    if count >= threshold:
        r.setex(OPEN_KEY, cooldown_s, str(int(time.time()) + cooldown_s))
    return count


def snapshot(r: redis.Redis) -> dict:
    """For the /circuit ops endpoint."""
    return {
        "open": is_open(r),
        "manual_disabled": r.get(DISABLED_KEY) == "1",
        "fail_count": int(r.get(FAIL_KEY) or 0),
        "seconds_until_close": seconds_until_close(r),
    }
