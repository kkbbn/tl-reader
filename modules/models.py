from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def scale(self, width: int, height: int, base_width: int = 1916, base_height: int = 1080) -> "Rect":
        return Rect(
            max(0, round(self.x * width / base_width)),
            max(0, round(self.y * height / base_height)),
            max(1, round(self.width * width / base_width)),
            max(1, round(self.height * height / base_height)),
        )


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    width: int
    height: int
    duration: float
    frame_rate: str


@dataclass(frozen=True)
class Frame:
    time: float
    width: int
    height: int
    data: bytes


@dataclass(frozen=True)
class CostSample:
    time: float
    signal: float


@dataclass(frozen=True)
class RawEvent:
    index: int
    event_time: float
    before_time: float
    after_time: float
    before_signal: float
    after_signal: float

    @property
    def delta_signal(self) -> float:
        return self.before_signal - self.after_signal


@dataclass(frozen=True)
class TimelineEvent:
    index: int
    video_time: float
    battle_time: float | None
    before_time: float
    after_time: float
    cost: float
    cost_after: float
    cost_drop: float
    slot: int | None
    card_hash: str | None
    student: str | None
    confidence: float
    notes: tuple[str, ...]
