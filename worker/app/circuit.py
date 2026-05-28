"""Shared OpenAI circuit breaker.

Three Valkey keys back this:
  openai:fail_count          (counter, TTL = 2 * cooldown)
  openai:circuit_open_until  (unix-ts, TTL = cooldown — exists only while open)
  openai:disabled            (manual override; "1" forces the circuit open)

The same module lives in api/app/circuit.py (intentional duplicate — small
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
        return -1
    ttl = r.ttl(OPEN_KEY)
    return ttl if ttl and ttl > 0 else 0


def record_success(r: redis.Redis) -> None:
    r.delete(FAIL_KEY)


def record_failure(r: redis.Redis, *, threshold: int, cooldown_s: int) -> int:
    count = int(r.incr(FAIL_KEY))
    r.expire(FAIL_KEY, cooldown_s * 2)
    if count >= threshold:
        r.setex(OPEN_KEY, cooldown_s, str(int(time.time()) + cooldown_s))
    return count


def snapshot(r: redis.Redis) -> dict:
    return {
        "open": is_open(r),
        "manual_disabled": r.get(DISABLED_KEY) == "1",
        "fail_count": int(r.get(FAIL_KEY) or 0),
        "seconds_until_close": seconds_until_close(r),
    }
