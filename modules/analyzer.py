from __future__ import annotations

from pathlib import Path

from .geometry import COST_RECT, scale_rect, scaled_card_rects
from .image_ops import average_hash, cost_signal, estimate_cost_gauge, mean_abs_diff, smoothed
from .models import CostSample, RawEvent, TimelineEvent, VideoInfo
from .names import CardIdentity, NameDatabase
from .progress import Progress
from .timer_ocr import read_battle_timer
from .video import iter_frames, read_frame


def collect_cost_samples(video: Path, info: VideoInfo, fps: float, progress: Progress | None = None) -> list[CostSample]:
    rect = scale_rect(COST_RECT, info)
    total_frames = max(1, round(info.duration * fps))
    if progress is not None:
        progress.log(f"Sampling cost gauge at {fps:g} fps ({total_frames} frames)")
    ticker = progress.every(5.0) if progress is not None else None
    raw_signals: list[int] = []
    for index, frame in enumerate(iter_frames(video, rect, fps), start=1):
        raw_signals.append(cost_signal(frame))
        if ticker is not None:
            percent = min(100.0, index * 100.0 / total_frames)
            ticker.log(f"Sampling cost gauge: {index}/{total_frames} frames ({percent:.0f}%)")
    if progress is not None:
        progress.log(f"Sampled {len(raw_signals)} cost frames")
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


def _mean_luma(frame, rect) -> float:
    total = 0.0
    count = 0
    step_x = max(1, rect.width // 32)
    step_y = max(1, rect.height // 32)
    for y in range(rect.y, min(rect.y + rect.height, frame.height), step_y):
        for x in range(rect.x, min(rect.x + rect.width, frame.width), step_x):
            off = (y * frame.width + x) * 3
            r, g, b = frame.data[off], frame.data[off + 1], frame.data[off + 2]
            total += 0.299 * r + 0.587 * g + 0.114 * b
            count += 1
    return total / max(1, count)


def _selected_slot(frame, info: VideoInfo) -> int | None:
    lumas = [_mean_luma(frame, rect) for rect in scaled_card_rects(info)]
    if len(lumas) < 2:
        return None
    best = max(range(len(lumas)), key=lambda index: lumas[index])
    ordered = sorted(lumas, reverse=True)
    if ordered[0] >= ordered[1] + 18.0 and ordered[0] >= 80.0:
        return best
    return None


def _match_key(identity: CardIdentity) -> float:
    if identity.source == "roster":
        return 2.0
    return identity.score or 0.0


def _match_frames(video: Path, info: VideoInfo, before_time: float, before_frame) -> list:
    frames = [before_frame]
    for offset in (0.50, 1.00):
        time_sec = before_time - offset
        if time_sec < 0:
            continue
        try:
            frames.append(read_frame(video, info, time_sec))
        except RuntimeError:
            continue
    return frames


def _matched_identity(
    names: NameDatabase,
    frames,
    info: VideoInfo,
    slot: int | None,
    expected_cost: float | None,
) -> tuple[int | None, str | None, CardIdentity | None]:
    rects = scaled_card_rects(info)

    best_slot: int | None = slot
    best_hash: str | None = None
    best_identity: CardIdentity | None = None
    slot_indexes = [slot] if slot is not None and slot < len(rects) else list(range(len(rects)))
    for frame in frames:
        hashes = _card_hashes(frame, info)
        for index in slot_indexes:
            rect = rects[index]
            card_hash = hashes[index] if index < len(hashes) else None
            identity = names.match_card(frame, rect, card_hash, expected_cost=expected_cost)
            if identity is None:
                if best_hash is None:
                    best_hash = card_hash
                continue
            if best_identity is None or _match_key(identity) > _match_key(best_identity):
                best_slot = index
                best_hash = card_hash
                best_identity = identity
    return best_slot, best_hash, best_identity


def build_timeline(
    video: Path,
    info: VideoInfo,
    raw_events: list[RawEvent],
    *,
    cost_unit: float,
    names: NameDatabase,
    min_cost_drop: float,
    progress: Progress | None = None,
) -> list[TimelineEvent]:
    timeline: list[TimelineEvent] = []
    if progress is not None:
        progress.log(f"Matching {len(raw_events)} cost-drop candidates")
    ticker = progress.every(5.0) if progress is not None else None
    active_alternate_ex: list[str] = []
    for raw_index, raw in enumerate(raw_events, start=1):
        if ticker is not None:
            ticker.log(f"Matching candidate {raw_index}/{len(raw_events)}")
        area_cost = raw.before_signal / cost_unit
        area_cost_after = raw.after_signal / cost_unit

        cost_time = max(0.0, raw.before_time)
        before_time = max(0.0, raw.before_time - 0.033)
        after_time = min(info.duration, raw.after_time + 0.100)
        measured_cost = _estimated_cost_at(video, info, cost_time, area_cost)
        measured_cost_after = _estimated_cost_at(video, info, after_time, area_cost_after)
        battle_time = read_battle_timer(video, info, raw.event_time)

        cost = _round_cost(measured_cost)
        cost_after = _round_cost(measured_cost_after)
        cost_drop = _round_cost(max(0.0, measured_cost - measured_cost_after))
        if cost < 0.8 or cost_drop < min_cost_drop:
            continue
        match_expected_cost = cost_drop
        if cost <= 3.5 and cost_after <= 1.5 and cost - cost_drop >= 0.8:
            match_expected_cost = round(cost)

        before_frame = read_frame(video, info, before_time)
        after_frame = read_frame(video, info, after_time)
        slot, slot_diff = _consumed_slot(before_frame, after_frame, info)
        selected_slot = _selected_slot(before_frame, info)
        if selected_slot is not None:
            slot = selected_slot
        card_hash = None
        identity = None
        alternate_ex_state = False
        if cost_after <= 1.2 and cost_drop >= 4.0 and active_alternate_ex:
            alternate_ex_state = True
            identity = CardIdentity(
                active_alternate_ex[-1],
                None,
                None,
                None,
                1.0,
                "alternate_ex_state",
            )
            slot = None
        else:
            slot, card_hash, identity = _matched_identity(
                names,
                _match_frames(video, info, before_time, before_frame),
                info,
                slot,
                match_expected_cost,
            )
        notes: list[str] = []
        if slot is None:
            notes.append("consumed_slot_unresolved")
        if battle_time is None:
            notes.append("timer_ocr_failed")
        if identity is None:
            notes.append("student_unmatched")
        elif identity.source == "wikiru" and identity.score is not None:
            notes.append(f"student_match=wikiru:{identity.score:.3f}")
        elif identity.source == "alternate_ex_state":
            notes.append("student_match=alternate_ex_state")
        if alternate_ex_state:
            notes.append("normal_card_not_consumed")
        confidence = min(1.0, 0.45 + min(0.35, cost_drop / 10) + min(0.20, slot_diff / 120))
        if identity is not None and names.has_alternate_ex(identity.name):
            if identity.name in active_alternate_ex:
                active_alternate_ex.remove(identity.name)
            active_alternate_ex.append(identity.name)
        names.learn(card_hash, identity)

        timeline.append(
            TimelineEvent(
                index=len(timeline) + 1,
                video_time=raw.event_time,
                battle_time=battle_time,
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
    if progress is not None:
        progress.log(f"Built timeline with {len(timeline)} paid EX events")
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
    progress: Progress | None = None,
) -> tuple[list[CostSample], list[RawEvent], list[TimelineEvent], float]:
    samples = collect_cost_samples(video, info, fps, progress=progress)
    raw_events = detect_raw_events(samples, fps=fps, min_area_drop=min_area_drop)
    if progress is not None:
        progress.log(f"Detected {len(raw_events)} raw cost-drop candidates")
    fallback_signal = max((sample.signal for sample in samples), default=1.0)
    unit = estimate_cost_unit(raw_events, fallback_signal, max_cost)
    if progress is not None:
        progress.log(f"Estimated cost unit: {unit:.1f} blue pixels")
    timeline = build_timeline(
        video,
        info,
        raw_events,
        cost_unit=unit,
        names=names,
        min_cost_drop=min_cost_drop,
        progress=progress,
    )
    return samples, raw_events, timeline, unit
