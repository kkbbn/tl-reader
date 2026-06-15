from __future__ import annotations

import json
from colorsys import rgb_to_hsv
from dataclasses import dataclass
from pathlib import Path

from .image_match import crop_frame
from .image_ops import hamming_hex
from .models import Frame, Rect
from .progress import Progress
from .wikiru import WikiruIconMatcher, default_icon_cache_dir


@dataclass(frozen=True)
class CardIdentity:
    name: str
    cost: int | None
    hash: str | None
    distance: int | None
    score: float | None
    source: str


class NameDatabase:
    def __init__(
        self,
        entries: list[dict],
        max_distance: int = 10,
        icon_matcher: WikiruIconMatcher | None = None,
    ) -> None:
        self.entries = entries
        self.max_distance = max_distance
        self.icon_matcher = icon_matcher
        self.image_cache: dict[str, CardIdentity | None] = {}
        self.learned: list[CardIdentity] = []

    @classmethod
    def empty(cls) -> "NameDatabase":
        return cls([])

    @classmethod
    def load(
        cls,
        path: Path | None,
        max_distance: int = 10,
        *,
        use_wikiru: bool = True,
        wikiru_cache_dir: Path | None = None,
        refresh_wikiru: bool = False,
        wikiru_threshold: float = 0.25,
        progress: Progress | None = None,
    ) -> "NameDatabase":
        matcher = None
        if use_wikiru:
            matcher = WikiruIconMatcher.load(
                default_icon_cache_dir() if wikiru_cache_dir is None else wikiru_cache_dir,
                refresh=refresh_wikiru,
                threshold=wikiru_threshold,
                progress=progress,
            )
        if path is None:
            return cls([], max_distance=max_distance, icon_matcher=matcher)
        data = json.loads(path.expanduser().read_text(encoding="utf-8"))
        entries = data.get("cards", data if isinstance(data, list) else [])
        if not isinstance(entries, list):
            raise SystemExit(f"Invalid roster JSON: {path}")
        return cls(entries, max_distance=max_distance, icon_matcher=matcher)

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
            if best is None or distance < (best.distance or 999):
                best = CardIdentity(str(name), entry.get("cost"), str(entry_hash), distance, None, "roster")
        if best is not None and best.distance <= self.max_distance:
            return best
        return None

    def _match_learned(self, card_hash: str | None, expected_cost: float | None) -> CardIdentity | None:
        if not card_hash:
            return None
        rounded_cost = int(round(expected_cost)) if expected_cost is not None and 1.0 <= expected_cost <= 6.5 else None
        best: CardIdentity | None = None
        for entry in self.learned:
            if entry.hash is None:
                continue
            if rounded_cost is not None and entry.cost is not None and abs(entry.cost - rounded_cost) > 1:
                continue
            distance = hamming_hex(card_hash, entry.hash)
            if distance > max(12, self.max_distance + 8):
                continue
            if best is None or distance < (best.distance or 999):
                best = CardIdentity(entry.name, entry.cost, entry.hash, distance, entry.score, "learned")
        return best

    def _low_color_card(self, frame: Frame, rect: Rect) -> bool:
        total = 0.0
        count = 0
        step_x = max(1, rect.width // 24)
        step_y = max(1, rect.height // 24)
        for y in range(rect.y + rect.height // 5, min(rect.y + rect.height * 4 // 5, frame.height), step_y):
            for x in range(rect.x + rect.width // 8, min(rect.x + rect.width * 7 // 8, frame.width), step_x):
                off = (y * frame.width + x) * 3
                r = frame.data[off] / 255.0
                g = frame.data[off + 1] / 255.0
                b = frame.data[off + 2] / 255.0
                _, saturation, value = rgb_to_hsv(r, g, b)
                if value < 0.10:
                    continue
                total += saturation
                count += 1
        return count > 0 and total / count < 0.20

    def learn(self, card_hash: str | None, identity: CardIdentity | None) -> None:
        if not card_hash or identity is None:
            return
        if identity.source not in {"wikiru", "roster", "learned"}:
            return
        if identity.score is not None and identity.score < 0.12:
            return
        for entry in self.learned:
            if entry.name == identity.name and entry.hash == card_hash:
                return
        self.learned.append(
            CardIdentity(identity.name, identity.cost, card_hash, 0, identity.score, identity.source),
        )

    def match_card(
        self,
        frame: Frame,
        rect: Rect,
        card_hash: str | None,
        *,
        expected_cost: float | None = None,
    ) -> CardIdentity | None:
        roster_match = self.match(card_hash)
        if roster_match is not None:
            return roster_match
        if self._low_color_card(frame, rect):
            learned_match = self._match_learned(card_hash, expected_cost)
            if learned_match is not None:
                return learned_match
        if self.icon_matcher is None:
            return None

        cost_key = "" if expected_cost is None else f":{round(expected_cost):.0f}"
        cache_key = (card_hash or f"{rect.x}:{rect.y}:{rect.width}:{rect.height}:{frame.time:.3f}") + cost_key
        if cache_key in self.image_cache:
            return self.image_cache[cache_key]

        card = crop_frame(frame, rect)
        match = self.icon_matcher.match(card, expected_cost=expected_cost)
        if match is None:
            self.image_cache[cache_key] = None
            return None

        identity = CardIdentity(
            name=match.name,
            cost=match.cost,
            hash=card_hash,
            distance=None,
            score=match.score,
            source="wikiru",
        )
        self.image_cache[cache_key] = identity
        return identity

    def has_alternate_ex(self, name: str) -> bool:
        if self.icon_matcher is None:
            return False
        return self.icon_matcher.has_alternate_ex(name)
