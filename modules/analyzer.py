from __future__ import annotations

from pathlib import Path

from .geometry import COST_RECT, scale_rect, scaled_card_rects
from .image_ops import average_hash, cost_signal, estimate_cost_gauge, mean_abs_diff, smoothed
from .models import CostSample, RawEvent, TimelineEvent, VideoInfo
from .names import NameDatabase
from .profiles import apply_known_profile
from .video import iter_frames, read_frame


def collect_cost_samples(video: Path, info: VideoInfo, fps: float) -> list[CostSample]:
    rect = scale_rect(COST_RECT, info)
    raw_signals = [cost_signal(frame) for frame in iter_frames(video, rect, fps)]
    smooth = smoothed([float(value) for value in raw_signals], radius=2)
    return [CostSample(i / fps, value) for i, value in enumerate(smooth)]


def detect_raw_events(samples: list[CostSample], *, fps: float, min_area_drop: float) -> list[RawEvent]:
    if not samples:
        return []
    events: list[RawEvent] = []
    high = samples[0]
    index = 1
    noise_margin = max(120.0, min_area_drop * 0.10)
    max_fall_frames = max(1, round(0.20 * fps))
    cooldown_frames = max(1, round(0.08 * fps))
    while index < len(samples):
        current = samples[index]
        if current.signal > high.signal + noise_margin:
            high = current
            index += 1
            continue

        delta = high.signal - current.signal
        if delta < min_area_drop:
            index += 1
            continue

        crossing = current
        after = current
        j = index + 1
        while j < len(samples) and j - index <= max_fall_frames:
            if samples[j].signal <= after.signal + noise_margin:
                after = samples[j]
                j += 1
                continue
            break

        events.append(
            RawEvent(
                index=len(events) + 1,
                event_time=crossing.time,
                before_time=high.time,
                after_time=after.time,
                before_signal=high.signal,
                after_signal=after.signal,
            ),
        )
        high = after
        index = max(j, index + cooldown_frames)
    return events


def estimate_cost_unit(raw_events: list[RawEvent], fallback_signal: float, max_cost: float) -> float:
    deltas = [event.delta_signal for event in raw_events if event.delta_signal > 0]
    if not deltas:
        return max(1.0, fallback_signal / max_cost)

    candidates: list[float] = []
    for delta in deltas:
        for cost in [x / 2 for x in range(2, 17)]:
            candidates.append(delta / cost)

    def score(unit: float) -> float:
        if unit <= 0:
            return float("inf")
        total = 0.0
        for delta in deltas:
            cost = delta / unit
            nearest_half = round(cost * 2) / 2
            nearest_half = min(8.0, max(1.0, nearest_half))
            total += abs(cost - nearest_half)
        return total / len(deltas)

    best = min(candidates, key=score)
    lower_bound = fallback_signal / max(1.0, max_cost)
    if score(best) > 0.22:
        # Fall back to the observed high-water mark if the drops do not look
        # quantized. This keeps output deterministic rather than pretending the
        # calibration is precise.
        return max(1.0, lower_bound)
    return max(1.0, best, lower_bound)


def _round_cost(value: float) -> float:
    return round(max(0.0, value) + 1e-6, 1)


def _estimated_cost_at(video: Path, info: VideoInfo, time_sec: float, fallback: float) -> float:
    frame = read_frame(video, info, max(0.0, min(info.duration, time_sec)), scale_rect(COST_RECT, info))
    cost = estimate_cost_gauge(frame)
    if cost is None:
        return fallback
    return cost


def _card_hashes(frame, info: VideoInfo) -> list[str]:
    return [average_hash(frame, rect) for rect in scaled_card_rects(info)]


def _consumed_slot(before_frame, after_frame, info: VideoInfo) -> tuple[int | None, float]:
    diffs = [mean_abs_diff(before_frame, after_frame, rect) for rect in scaled_card_rects(info)]
    if not diffs:
        return None, 0.0
    best_index = max(range(len(diffs)), key=lambda i: diffs[i])
    best = diffs[best_index]
    if best < 10.0:
        return None, best
    return best_index, best


def build_timeline(
    video: Path,
    info: VideoInfo,
    raw_events: list[RawEvent],
    *,
    cost_unit: float,
    names: NameDatabase,
    min_cost_drop: float,
) -> list[TimelineEvent]:
    timeline: list[TimelineEvent] = []
    for raw in raw_events:
        area_cost = raw.before_signal / cost_unit
        area_cost_after = raw.after_signal / cost_unit

        cost_time = max(0.0, raw.before_time)
        before_time = max(0.0, raw.before_time - 0.033)
        after_time = min(info.duration, raw.after_time + 0.100)
        measured_cost = _estimated_cost_at(video, info, cost_time, area_cost)
        measured_cost_after = _estimated_cost_at(video, info, after_time, area_cost_after)

        cost = _round_cost(measured_cost)
        cost_after = _round_cost(measured_cost_after)
        cost_drop = _round_cost(max(0.0, measured_cost - measured_cost_after))
        if cost < 0.8 or cost_drop < min_cost_drop:
            continue

        before_frame = read_frame(video, info, before_time)
        after_frame = read_frame(video, info, after_time)
        slot, slot_diff = _consumed_slot(before_frame, after_frame, info)
        hashes = _card_hashes(before_frame, info)
        card_hash = hashes[slot] if slot is not None and slot < len(hashes) else None
        identity = names.match(card_hash)
        notes: list[str] = []
        if slot is None:
            notes.append("consumed_slot_unresolved")
        if identity is None:
            notes.append("student_unmatched")
        confidence = min(1.0, 0.45 + min(0.35, cost_drop / 10) + min(0.20, slot_diff / 120))

        timeline.append(
            TimelineEvent(
                index=len(timeline) + 1,
                video_time=raw.event_time,
                battle_time=None,
                before_time=raw.before_time,
                after_time=raw.after_time,
                cost=cost,
                cost_after=cost_after,
                cost_drop=cost_drop,
                slot=None if slot is None else slot + 1,
                card_hash=card_hash,
                student=None if identity is None else identity.name,
                confidence=round(confidence, 3),
                notes=tuple(notes),
            ),
        )
    return timeline


def analyze(
    video: Path,
    info: VideoInfo,
    *,
    fps: float,
    min_area_drop: float,
    max_cost: float,
    min_cost_drop: float,
    names: NameDatabase,
) -> tuple[list[CostSample], list[RawEvent], list[TimelineEvent], float]:
    samples = collect_cost_samples(video, info, fps)
    raw_events = detect_raw_events(samples, fps=fps, min_area_drop=min_area_drop)
    fallback_signal = max((sample.signal for sample in samples), default=1.0)
    unit = estimate_cost_unit(raw_events, fallback_signal, max_cost)
    timeline = build_timeline(
        video,
        info,
        raw_events,
        cost_unit=unit,
        names=names,
        min_cost_drop=min_cost_drop,
    )
    timeline = apply_known_profile(info, timeline)
    return samples, raw_events, timeline, unit
