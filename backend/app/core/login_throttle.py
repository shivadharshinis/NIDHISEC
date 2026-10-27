"""In-process throttling of failed logins, keyed by email address.

State lives in memory, so it resets on restart and is not shared between
worker processes. That is adequate for the single-process prototype; a shared
store (e.g. Redis) is needed before running multiple workers.
"""

import threading
import time
from collections import defaultdict, deque


class LoginThrottle:
    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, window_seconds: float, now: float) -> deque[float]:
        attempts = self._failures[key]
        while attempts and now - attempts[0] > window_seconds:
            attempts.popleft()
        return attempts

    def retry_after(self, key: str, max_failures: int, window_seconds: float) -> int:
        """Seconds until another attempt is allowed (0 if not locked)."""
        now = time.monotonic()
        with self._lock:
            attempts = self._prune(key, window_seconds, now)
            if len(attempts) < max_failures:
                return 0
            return max(1, int(window_seconds - (now - attempts[0])))

    def record_failure(self, key: str, window_seconds: float) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(key, window_seconds, now).append(now)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._failures.clear()
            else:
                self._failures.pop(key, None)


login_throttle = LoginThrottle()
