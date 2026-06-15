from __future__ import annotations

import sys
import time
from dataclasses import dataclass


@dataclass
class Progress:
    quiet: bool = False
    prefix: str = "tl-reader"

    def log(self, message: str) -> None:
        if self.quiet:
            return
        print(f"[{self.prefix}] {message}", file=sys.stderr, flush=True)

    def every(self, interval: float = 5.0) -> "ProgressTicker":
        return ProgressTicker(self, interval)


class ProgressTicker:
    def __init__(self, progress: Progress, interval: float) -> None:
        self.progress = progress
        self.interval = interval
        self.last = 0.0

    def log(self, message: str, *, force: bool = False) -> None:
        now = time.monotonic()
        if force or self.last == 0.0 or now - self.last >= self.interval:
            self.progress.log(message)
            self.last = now
