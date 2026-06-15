from __future__ import annotations

from .models import Frame, Rect


def is_cost_blue(r: int, g: int, b: int) -> bool:
    return r < 115 and g > 85 and b > 105 and (b - r) > 35 and (g - r) > 20


def cost_signal(frame: Frame) -> int:
    count = 0
    start_x = round(frame.width * 0.13)
    for y in range(5, frame.height - 5):
        row = y * frame.width * 3
        for x in range(start_x, frame.width - 5):
            off = row + x * 3
            if is_cost_blue(frame.data[off], frame.data[off + 1], frame.data[off + 2]):
                count += 1
    return count


def median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def smoothed(values: list[float], radius: int = 2) -> list[float]:
    output: list[float] = []
    for i in range(len(values)):
        window = values[max(0, i - radius) : min(len(values), i + radius + 1)]
        output.append(median(window))
    return output


def _luma_at(frame: Frame, x: int, y: int) -> int:
    off = (y * frame.width + x) * 3
    r, g, b = frame.data[off], frame.data[off + 1], frame.data[off + 2]
    return (299 * r + 587 * g + 114 * b) // 1000


def average_hash(frame: Frame, rect: Rect, hash_size: int = 8) -> str:
    values: list[int] = []
    for gy in range(hash_size):
        y0 = rect.y + gy * rect.height // hash_size
        y1 = rect.y + (gy + 1) * rect.height // hash_size
        for gx in range(hash_size):
            x0 = rect.x + gx * rect.width // hash_size
            x1 = rect.x + (gx + 1) * rect.width // hash_size
            total = 0
            count = 0
            step_x = max(1, (x1 - x0) // 4)
            step_y = max(1, (y1 - y0) // 4)
            for y in range(y0, min(y1, frame.height), step_y):
                for x in range(x0, min(x1, frame.width), step_x):
                    total += _luma_at(frame, x, y)
                    count += 1
            values.append(total // max(1, count))
    threshold = median([float(value) for value in values])
    bits = 0
    for value in values:
        bits = (bits << 1) | int(value >= threshold)
    return f"{bits:0{hash_size * hash_size // 4}x}"


def hamming_hex(left: str, right: str) -> int:
    width = max(len(left), len(right)) * 4
    return (int(left, 16) ^ int(right, 16)).bit_count() if width else 0


def mean_abs_diff(left: Frame, right: Frame, rect: Rect) -> float:
    total = 0
    count = 0
    step_x = max(1, rect.width // 64)
    step_y = max(1, rect.height // 64)
    for y in range(rect.y, min(rect.y + rect.height, left.height, right.height), step_y):
        for x in range(rect.x, min(rect.x + rect.width, left.width, right.width), step_x):
            off = (y * left.width + x) * 3
            roff = (y * right.width + x) * 3
            total += abs(left.data[off] - right.data[roff])
            total += abs(left.data[off + 1] - right.data[roff + 1])
            total += abs(left.data[off + 2] - right.data[roff + 2])
            count += 3
    return total / max(1, count)
