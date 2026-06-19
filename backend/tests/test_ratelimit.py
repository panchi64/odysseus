"""The token-bucket rate limiter (UP-4)."""

from __future__ import annotations

import pytest

from core.exceptions import RateLimitedError
from core.ratelimit import RateLimiter


def test_allows_burst_then_blocks_and_refills():
    clock = [0.0]
    limiter = RateLimiter(rate_per_second=1.0, burst=2, now=lambda: clock[0])

    limiter.check("k")  # 2 tokens → both allowed
    limiter.check("k")
    with pytest.raises(RateLimitedError):
        limiter.check("k")  # dry

    clock[0] = 1.0  # one second → +1 token
    limiter.check("k")  # allowed again
    with pytest.raises(RateLimitedError):
        limiter.check("k")


def test_retry_after_is_reported():
    limiter = RateLimiter(rate_per_second=2.0, burst=1, now=lambda: 0.0)
    limiter.check("k")
    with pytest.raises(RateLimitedError) as excinfo:
        limiter.check("k")
    # Empty bucket, refilling at 2/s ⇒ ~0.5s to the next token.
    assert excinfo.value.retry_after_s == pytest.approx(0.5)


def test_keys_are_independent():
    limiter = RateLimiter(rate_per_second=0.0, burst=1)
    limiter.check("a")
    limiter.check("b")  # a different key has its own bucket
    with pytest.raises(RateLimitedError):
        limiter.check("a")
