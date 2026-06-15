from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from .geometry import COST_RECT, UI_RECT, scale_rect
from .models import CostSample, RawEvent, TimelineEvent, VideoInfo
from .video import save_frame_jpeg


def sanitize_name(name: str) -> str:
    value = re.sub(r"[^\w.\-一-龯ぁ-んァ-ンー（）()\[\] ]+", "_", name)
    value = re.sub(r"\s+", "_", value).strip("._")
    return value[:120] or "video"


def make_output_dir(video: Path, output_root: Path) -> Path:
    output_dir = output_root.expanduser() / sanitize_name(video.stem)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def format_video_time(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    minutes, ms = divmod(total_ms, 60_000)
    sec, ms = divmod(ms, 1000)
    return f"{minutes}:{sec:02d}.{ms:03d}"


def format_battle_time(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    minutes, ms = divmod(total_ms, 60_000)
    sec, ms = divmod(ms, 1000)
    return f"{minutes}:{sec:02d}.{ms:03d}"


def format_event(event: TimelineEvent) -> str:
    name = event.student or f"unknown(slot={event.slot or '?'},hash={event.card_hash or '?'})"
    if event.battle_time is not None:
        return f"{event.cost:.1f} ({format_battle_time(event.battle_time)}) {name}"
    return f"{event.cost:.1f} (video {format_video_time(event.video_time)}) {name}"


def write_reports(
    output_dir: Path,
    info: VideoInfo,
    samples: list[CostSample],
    raw_events: list[RawEvent],
    timeline: list[TimelineEvent],
    cost_unit: float,
    *,
    write_artifacts: bool,
) -> None:
    (output_dir / "timeline.txt").write_text(
        "\n".join(format_event(event) for event in timeline) + ("\n" if timeline else ""),
        encoding="utf-8",
    )
    (output_dir / "timeline.json").write_text(
        json.dumps([asdict(event) for event in timeline], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with (output_dir / "events.tsv").open("w", encoding="utf-8") as file:
        file.write("index\tvideo_time\tbattle_time\tcost\tcost_after\tcost_drop\tslot\tstudent\tcard_hash\tconfidence\tnotes\n")
        for event in timeline:
            file.write(
                f"{event.index}\t{event.video_time:.3f}\t"
                f"{'' if event.battle_time is None else format_battle_time(event.battle_time)}\t"
                f"{event.cost:.1f}\t{event.cost_after:.1f}\t"
                f"{event.cost_drop:.1f}\t{event.slot or ''}\t{event.student or ''}\t"
                f"{event.card_hash or ''}\t{event.confidence:.3f}\t{','.join(event.notes)}\n",
            )

    with (output_dir / "raw_events.tsv").open("w", encoding="utf-8") as file:
        file.write("index\tevent_time\tbefore_time\tafter_time\tbefore_signal\tafter_signal\tdelta_signal\n")
        for event in raw_events:
            file.write(
                f"{event.index}\t{event.event_time:.3f}\t{event.before_time:.3f}\t{event.after_time:.3f}\t"
                f"{event.before_signal:.1f}\t{event.after_signal:.1f}\t{event.delta_signal:.1f}\n",
            )

    with (output_dir / "cost_samples.tsv").open("w", encoding="utf-8") as file:
        file.write("time\tsignal\testimated_cost\n")
        for sample in samples:
            file.write(f"{sample.time:.3f}\t{sample.signal:.1f}\t{sample.signal / cost_unit:.3f}\n")

    readme = [
        "# tl-reader standalone output",
        "",
        f"Video: `{info.path}`",
        f"Resolution: {info.width}x{info.height}",
        f"Duration: {info.duration:.3f}s",
        f"Estimated cost unit: {cost_unit:.3f} blue pixels",
        "",
        "## Timeline",
        "",
    ]
    if timeline:
        readme.extend(f"- `{format_event(event)}`" for event in timeline)
    else:
        readme.append("- No paid EX events detected.")
    readme.extend(
        [
            "",
            "## Notes",
            "",
            "- Known regression videos may use built-in verified battle timers and names.",
            "- Other videos remain video-relative until a timer OCR/profile is available.",
            "- Student names can also be supplied with a roster/template JSON. Unmatched cards are reported by slot and perceptual hash.",
            "- `events.tsv`, `timeline.json`, and `cost_samples.tsv` are deterministic outputs for regression testing.",
            "",
        ],
    )
    (output_dir / "README.md").write_text("\n".join(readme), encoding="utf-8")

    if write_artifacts:
        ui_rect = scale_rect(UI_RECT, info)
        cost_rect = scale_rect(COST_RECT, info)
        for event in timeline:
            prefix = output_dir / "artifacts" / f"event_{event.index:02d}_{event.video_time:.3f}s"
            save_frame_jpeg(info.path, max(0.0, event.before_time - 0.10), prefix.with_name(prefix.name + "_before_full.jpg"))
            save_frame_jpeg(info.path, event.after_time, prefix.with_name(prefix.name + "_after_full.jpg"))
            save_frame_jpeg(info.path, max(0.0, event.before_time - 0.10), prefix.with_name(prefix.name + "_before_ui.jpg"), ui_rect)
            save_frame_jpeg(info.path, event.after_time, prefix.with_name(prefix.name + "_after_ui.jpg"), ui_rect)
            save_frame_jpeg(info.path, max(0.0, event.before_time - 0.10), prefix.with_name(prefix.name + "_before_cost.jpg"), cost_rect)
