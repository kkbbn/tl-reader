from __future__ import annotations

from .models import Rect, VideoInfo


BASE_WIDTH = 1916
BASE_HEIGHT = 1080

# These coordinates are calibrated against the common 1916x1080 Blue Archive
# battle capture layout used by the source videos. They are scaled for other
# resolutions.
COST_RECT = Rect(1190, 990, 560, 70)
UI_RECT = Rect(1130, 780, 760, 300)
TIMER_RECT = Rect(1530, 30, 410, 92)

# Normal hand-card locations. The portrait hash deliberately includes the card
# face and some frame context, because this script is intended to be
# deterministic rather than visually semantic.
CARD_RECTS = (
    Rect(1260, 790, 150, 220),
    Rect(1425, 790, 150, 220),
    Rect(1590, 790, 150, 220),
)


def scale_rect(rect: Rect, info: VideoInfo) -> Rect:
    return rect.scale(info.width, info.height, BASE_WIDTH, BASE_HEIGHT)


def scaled_card_rects(info: VideoInfo) -> tuple[Rect, ...]:
    return tuple(scale_rect(rect, info) for rect in CARD_RECTS)
