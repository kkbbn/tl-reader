from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .image_ops import hamming_hex


@dataclass(frozen=True)
class CardIdentity:
    name: str
    cost: int | None
    hash: str
    distance: int


class NameDatabase:
    def __init__(self, entries: list[dict], max_distance: int = 10) -> None:
        self.entries = entries
        self.max_distance = max_distance

    @classmethod
    def empty(cls) -> "NameDatabase":
        return cls([])

    @classmethod
    def load(cls, path: Path | None, max_distance: int = 10) -> "NameDatabase":
        if path is None:
            return cls.empty()
        data = json.loads(path.expanduser().read_text(encoding="utf-8"))
        entries = data.get("cards", data if isinstance(data, list) else [])
        if not isinstance(entries, list):
            raise SystemExit(f"Invalid roster JSON: {path}")
        return cls(entries, max_distance=max_distance)

    def match(self, card_hash: str | None) -> CardIdentity | None:
        if not card_hash:
            return None
        best: CardIdentity | None = None
        for entry in self.entries:
            entry_hash = entry.get("hash")
            name = entry.get("name")
            if not entry_hash or not name:
                continue
            distance = hamming_hex(card_hash, str(entry_hash))
            if best is None or distance < best.distance:
                best = CardIdentity(str(name), entry.get("cost"), str(entry_hash), distance)
        if best is not None and best.distance <= self.max_distance:
            return best
        return None
