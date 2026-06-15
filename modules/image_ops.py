from __future__ import annotations

from .models import Frame, Rect


BASE_COST_CROP_WIDTH = 560
BASE_COST_BOX_RANGES = (
    (48, 88),
    (92, 132),
    (135, 175),
    (178, 218),
    (222, 262),
    (266, 306),
    (309, 349),
    (353, 393),
    (396, 437),
    (440, 480),
    (483, 523),
)


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


def _cost_box_ranges(width: int) -> tuple[tuple[int, int], ...]:
    scale = width / BASE_COST_CROP_WIDTH
    return tuple(
        (max(0, round(start * scale)), min(width, round(end * scale)))
        for start, end in BASE_COST_BOX_RANGES
    )


def _box_column_counts(frame: Frame, start_x: int, end_x: int) -> list[int]:
    counts: list[int] = []
    for x in range(start_x, end_x):
        count = 0
        for y in range(5, frame.height - 5):
            off = (y * frame.width + x) * 3
            if is_cost_blue(frame.data[off], frame.data[off + 1], frame.data[off + 2]):
                count += 1
        counts.append(count)
    return counts


def _prefix_fill_fraction(columns: list[int], full_column_peak: float) -> float:
    if not columns or full_column_peak <= 0:
        return 0.0

    threshold = max(8.0, full_column_peak * 0.55)
    seen_fill = False
    low_run = 0
    low_start = 0
    for index, count in enumerate(columns):
        if count >= threshold:
            seen_fill = True
            low_run = 0
            continue
        if not seen_fill:
            continue
        if low_run == 0:
            low_start = index
        low_run += 1
        if low_run >= 3:
            return low_start / len(columns)
    return 1.0 if seen_fill else 0.0


def estimate_cost_gauge(frame: Frame) -> float | None:
    """Estimate the displayed EX cost from the segmented gauge crop.

    The full blue-pixel area is useful for detecting sudden drops, but it is
    noisy for partial boxes because the gauge glow bleeds into adjacent pixels.
    This reader measures each cost box separately and compresses the area of
    partial boxes with a column-prefix check so quick casts near 10.5/4.5 do
    not get pulled toward the whole-bar average.
    """

    boxes = _cost_box_ranges(frame.width)
    columns_by_box = [_box_column_counts(frame, start, end) for start, end in boxes if end > start]
    if not columns_by_box:
        return None

    box_counts = [sum(columns) for columns in columns_by_box]
    max_count = max(box_counts, default=0)
    if max_count <= 0:
        return 0.0

    full_candidates = [count for count in box_counts if count >= max_count * 0.75]
    full_area = median([float(count) for count in full_candidates]) if full_candidates else float(max_count)
    if full_area <= 0:
        return None

    full_columns = [
        max(columns)
        for count, columns in zip(box_counts, columns_by_box)
        if count >= full_area * 0.85 and columns
    ]
    full_column_peak = median([float(count) for count in full_columns]) if full_columns else frame.height * 0.4

    total = 0.0
    for count, columns in zip(box_counts, columns_by_box):
        raw_fraction = max(0.0, count / full_area)
        if raw_fraction >= 0.85:
            total += 1.0
            continue
        if raw_fraction <= 0.04:
            continue

        if raw_fraction < 0.25:
            fraction = raw_fraction * 1.10
        else:
            area_fraction = raw_fraction * 0.65
            prefix_fraction = _prefix_fill_fraction(columns, full_column_peak)
            fraction = min(area_fraction, prefix_fraction)
        total += min(0.95, max(0.0, fraction))
    return total


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
