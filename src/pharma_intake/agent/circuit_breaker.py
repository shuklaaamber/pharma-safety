"""Step 5: circuit breaker for repeated identical invalid tool calls."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..config import CIRCUIT_BREAKER_MAX_INVALID


def call_signature(tool: str, args: Any) -> str:
    """Tool name + canonical hash of the arguments exactly as supplied."""
    canon = json.dumps(args, sort_keys=True, default=str, separators=(",", ":"))
    return f"{tool}:{hashlib.sha256(canon.encode()).hexdigest()[:16]}"


class CircuitBreaker:
    """Trips when the same signature is invalid MORE than `max_invalid` times in a row."""

    def __init__(self, max_invalid: int = CIRCUIT_BREAKER_MAX_INVALID):
        self.max_invalid = max_invalid
        self.reset()

    def reset(self) -> None:
        self.tripped = False
        self._last_sig: str | None = None
        self._count = 0

    @property
    def consecutive_invalid(self) -> int:
        return self._count

    def record(self, signature: str, invalid: bool) -> bool:
        """Record an outcome; returns True if the breaker is (now) tripped."""
        if invalid:
            self._count = self._count + 1 if signature == self._last_sig else 1
            self._last_sig = signature
            if self._count > self.max_invalid:
                self.tripped = True
        else:
            self._last_sig, self._count = None, 0
        return self.tripped
