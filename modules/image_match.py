from __future__ import annotations

import math
from colorsys import rgb_to_hsv
from dataclasses import dataclass

from .models import Frame, Rect


FEATURE_SIZE = 24


@dataclass(frozen=True)
class IconFeature:
    name: str
    source_url: str
    rgba: bytes
    mask: tuple[int, ...]
    y: tuple[float, ...]
    u: tuple[float, ...]
    v: tuple[float, ...]
    hist: tuple[float, ...]
    kind: str = "icon"


@dataclass(frozen=True)
class ImageMatch:
    name: str
    source_url: str
    distance: float
    score: float
    crop: Rect
    cost: int | None = None
    kind: str = "icon"


def crop_frame(frame: Frame, rect: Rect) -> Frame:
    x0 = max(0, min(frame.width, rect.x))
    y0 = max(0, min(frame.height, rect.y))
    x1 = max(x0, min(frame.width, rect.x + rect.width))
    y1 = max(y0, min(frame.height, rect.y + rect.height))
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    rows = []
    for y in range(y0, y1):
        start = (y * frame.width + x0) * 3
        end = start + width * 3
        rows.append(frame.data[start:end])
    return Frame(frame.time, width, height, b"".join(rows))


def resize_crop_rgb(frame: Frame, rect: Rect, size: int = FEATURE_SIZE) -> bytes:
    x0 = max(0, min(frame.width - 1, rect.x))
    y0 = max(0, min(frame.height - 1, rect.y))
    width = max(1, min(rect.width, frame.width - x0))
    height = max(1, min(rect.height, frame.height - y0))
    output = bytearray(size * size * 3)
    for oy in range(size):
        sy = y0 + min(height - 1, round((oy + 0.5) * height / size - 0.5))
        for ox in range(size):
            sx = x0 + min(width - 1, round((ox + 0.5) * width / size - 0.5))
            src = (sy * frame.width + sx) * 3
            dst = (oy * size + ox) * 3
            output[dst : dst + 3] = frame.data[src : src + 3]
    return bytes(output)


def _normalized(values: list[float]) -> tuple[float, ...]:
    if not values:
        return ()
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    scale = math.sqrt(variance) + 1e-6
    return tuple((value - mean) / scale for value in values)


def icon_feature(name: str, source_url: str, rgba: bytes, *, kind: str = "icon") -> IconFeature | None:
    mask = tuple(index // 4 for index in range(0, len(rgba), 4) if rgba[index + 3] > 32)
    if len(mask) < FEATURE_SIZE * FEATURE_SIZE // 4:
        return None

    y_values: list[float] = []
    u_values: list[float] = []
    v_values: list[float] = []
    for pixel in mask:
        offset = pixel * 4
        r, g, b = rgba[offset], rgba[offset + 1], rgba[offset + 2]
        y = 0.299 * r + 0.587 * g + 0.114 * b
        y_values.append(y)
        u_values.append(r - y)
        v_values.append(b - y)
    return IconFeature(
        name=name,
        source_url=source_url,
        rgba=rgba,
        mask=mask,
        y=_normalized(y_values),
        u=_normalized(u_values),
        v=_normalized(v_values),
        hist=_hsv_hist_rgba(rgba),
        kind=kind,
    )


def _rgb_yuv(rgb: bytes) -> tuple[list[float], list[float], list[float]]:
    y_values: list[float] = []
    u_values: list[float] = []
    v_values: list[float] = []
    for offset in range(0, len(rgb), 3):
        r, g, b = rgb[offset], rgb[offset + 1], rgb[offset + 2]
        y = 0.299 * r + 0.587 * g + 0.114 * b
        y_values.append(y)
        u_values.append(r - y)
        v_values.append(b - y)
    return y_values, u_values, v_values


def _masked_normalized(values: list[float], mask: tuple[int, ...]) -> tuple[float, ...]:
    return _normalized([values[index] for index in mask])


def _masked_distance(card_yuv: tuple[list[float], list[float], list[float]], icon: IconFeature) -> float:
    card_y = _masked_normalized(card_yuv[0], icon.mask)
    card_u = _masked_normalized(card_yuv[1], icon.mask)
    card_v = _masked_normalized(card_yuv[2], icon.mask)
    total = 0.0
    weight = 0.0
    for left, right in zip(card_y, icon.y):
        total += (left - right) ** 2
        weight += 1.0
    for left, right in zip(card_u, icon.u):
        total += 0.35 * (left - right) ** 2
        weight += 0.35
    for left, right in zip(card_v, icon.v):
        total += 0.35 * (left - right) ** 2
        weight += 0.35
    return math.sqrt(total / max(1e-6, weight))


def card_portrait_windows(card: Frame) -> list[Rect]:
    widths = (0.83, 0.90)
    x_offsets = (0.03, 0.07, 0.11)
    y_offsets = (0.11, 0.18, 0.25)
    windows: list[Rect] = []
    seen: set[tuple[int, int, int]] = set()
    for width_ratio in widths:
        size = max(8, round(card.width * width_ratio))
        for x_ratio in x_offsets:
            for y_ratio in y_offsets:
                x = round(card.width * x_ratio)
                y = round(card.height * y_ratio)
                if x + size > card.width or y + size > card.height:
                    continue
                key = (x, y, size)
                if key in seen:
                    continue
                seen.add(key)
                windows.append(Rect(x, y, size, size))
    return windows


def card_face_windows(card: Frame) -> list[Rect]:
    # These windows focus on the face/hair area and avoid most of the card
    # frame and EX-cost badge. They are intentionally smaller than the generic
    # portrait windows because SchaleDB icons already match the in-game card
    # portrait, apart from tilt, compression, and overlays.
    ratios = (
        (0.03, 0.14, 0.90),
        (0.07, 0.20, 0.83),
        (0.13, 0.23, 0.75),
        (0.17, 0.25, 0.67),
        (0.20, 0.27, 0.60),
        (0.13, 0.32, 0.73),
        (0.07, 0.25, 0.80),
        (0.17, 0.20, 0.73),
        (0.23, 0.30, 0.53),
        (0.00, 0.14, 1.00),
    )
    windows: list[Rect] = []
    seen: set[tuple[int, int, int]] = set()
    for x_ratio, y_ratio, size_ratio in ratios:
        size = max(8, round(card.width * size_ratio))
        x = round(card.width * x_ratio)
        y = round(card.height * y_ratio)
        if x + size > card.width or y + size > card.height:
            continue
        key = (x, y, size)
        if key in seen:
            continue
        seen.add(key)
        windows.append(Rect(x, y, size, size))
    return windows


def _hsv_hist_rgb(rgb: bytes) -> tuple[float, ...]:
    bins_h = 24
    bins_s = 4
    bins_v = 4
    hist = [0.0] * (bins_h * bins_s * bins_v)
    for offset in range(0, len(rgb), 3):
        r = rgb[offset] / 255.0
        g = rgb[offset + 1] / 255.0
        b = rgb[offset + 2] / 255.0
        hue, saturation, value = rgb_to_hsv(r, g, b)
        if value < 0.12 or (saturation < 0.08 and value > 0.75):
            continue
        weight = saturation * (0.5 + 0.5 * value)
        h_index = min(bins_h - 1, int(hue * bins_h))
        s_index = min(bins_s - 1, int(saturation * bins_s))
        v_index = min(bins_v - 1, int(value * bins_v))
        hist[(h_index * bins_s + s_index) * bins_v + v_index] += weight
    total = sum(hist) + 1e-6
    return tuple(value / total for value in hist)


def _hsv_hist_rgba(rgba: bytes) -> tuple[float, ...]:
    rgb = bytearray()
    for offset in range(0, len(rgba), 4):
        if rgba[offset + 3] <= 32:
            continue
        rgb.extend(rgba[offset : offset + 3])
    return _hsv_hist_rgb(bytes(rgb))


def _hist_distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return 0.5 * sum((a - b) ** 2 / (a + b + 1e-6) for a, b in zip(left, right))


def rank_card_icons(card: Frame, icons: list[IconFeature], *, limit: int = 30) -> list[ImageMatch]:
    best_by_name: dict[str, ImageMatch] = {}
    for crop in card_portrait_windows(card):
        rgb = resize_crop_rgb(card, crop)
        card_yuv = _rgb_yuv(rgb)
        for icon in icons:
            distance = _masked_distance(card_yuv, icon)
            score = max(0.0, min(1.0, 1.0 - distance / 1.35))
            current = best_by_name.get(icon.name)
            if current is None or distance < current.distance:
                best_by_name[icon.name] = ImageMatch(icon.name, icon.source_url, distance, score, crop, kind=icon.kind)
    return sorted(best_by_name.values(), key=lambda match: match.distance)[:limit]


def rank_card_histograms(card: Frame, icons: list[IconFeature], *, limit: int = 30) -> list[ImageMatch]:
    best_by_name: dict[str, ImageMatch] = {}
    for crop in card_face_windows(card):
        card_hist = _hsv_hist_rgb(resize_crop_rgb(card, crop))
        for icon in icons:
            distance = _hist_distance(card_hist, icon.hist)
            score = max(0.0, min(1.0, 1.0 - distance / 0.9))
            current = best_by_name.get(icon.name)
            if current is None or distance < current.distance:
                best_by_name[icon.name] = ImageMatch(icon.name, icon.source_url, distance, score, crop, kind=f"{icon.kind}:hist")
    return sorted(best_by_name.values(), key=lambda match: match.distance)[:limit]


def match_card_icon(card: Frame, icons: list[IconFeature]) -> ImageMatch | None:
    ranked = rank_card_icons(card, icons, limit=1)
    return ranked[0] if ranked else None
