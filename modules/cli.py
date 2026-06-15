from __future__ import annotations

import argparse
from pathlib import Path

from .analyzer import analyze
from .download import ensure_video
from .names import NameDatabase
from .progress import Progress
from .report import format_event, make_output_dir, write_reports
from .video import ffprobe
from .wikiru import default_icon_cache_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect Blue Archive paid EX skill executions from a video.",
    )
    parser.add_argument("input", help="YouTube/Bilibili URL or local MP4 path")
    parser.add_argument("--download-dir", default="~/Downloads/yt-dlp", help="MP4 download/cache directory")
    parser.add_argument("--output-root", default="~/Downloads/tl-reader", help="Report output root")
    parser.add_argument("--force-download", action="store_true", help="Download even if a matching MP4 exists")
    parser.add_argument("--upgrade-yt-dlp", action="store_true", help="Upgrade cached yt-dlp before downloading")
    parser.add_argument("--no-install", action="store_true", help="Do not create a yt-dlp virtualenv")
    parser.add_argument("--yt-dlp-arg", action="append", default=[], help="Extra raw argument passed to yt-dlp")
    parser.add_argument("--detect-fps", type=float, default=30.0, help="Cost detector FPS")
    parser.add_argument("--min-area-drop", type=float, default=800.0, help="Raw blue-pixel drop threshold")
    parser.add_argument("--min-cost-drop", type=float, default=0.8, help="Minimum estimated cost drop to report")
    parser.add_argument("--max-cost", type=float, default=11.0, help="Fallback max cost used for calibration")
    parser.add_argument("--roster", type=Path, help="Optional JSON card hash database")
    parser.add_argument("--hash-distance", type=int, default=10, help="Max hamming distance for roster hash match")
    parser.add_argument("--cache-dir", type=Path, default=default_icon_cache_dir(), help="Wikiru icon cache directory")
    parser.add_argument("--refresh-wikiru", action="store_true", help="Refresh downloaded SchaleDB/Wikiru student data")
    parser.add_argument("--no-wikiru", action="store_true", help="Disable SchaleDB/Wikiru visual matching")
    parser.add_argument("--wikiru-threshold", type=float, default=0.08, help="Minimum Wikiru visual match score")
    parser.add_argument("--no-artifacts", action="store_true", help="Skip event JPEG artifact output")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output on stderr")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    progress = Progress(quiet=args.quiet)
    progress.log("Resolving input video")
    video = ensure_video(
        args.input,
        Path(args.download_dir),
        force_download=args.force_download,
        upgrade_yt_dlp=args.upgrade_yt_dlp,
        no_install=args.no_install,
        extra_args=args.yt_dlp_arg,
    )
    progress.log(f"Using video: {video}")
    progress.log("Reading video metadata")
    info = ffprobe(video)
    progress.log(f"Video metadata: {info.width}x{info.height}, {info.duration:.1f}s")
    progress.log("Loading student matcher")
    names = NameDatabase.load(
        args.roster,
        max_distance=args.hash_distance,
        use_wikiru=not args.no_wikiru,
        wikiru_cache_dir=args.cache_dir,
        refresh_wikiru=args.refresh_wikiru,
        wikiru_threshold=args.wikiru_threshold,
        progress=progress,
    )
    output_dir = make_output_dir(video, Path(args.output_root))

    samples, raw_events, timeline, cost_unit = analyze(
        video,
        info,
        fps=args.detect_fps,
        min_area_drop=args.min_area_drop,
        max_cost=args.max_cost,
        min_cost_drop=args.min_cost_drop,
        names=names,
        progress=progress,
    )
    progress.log("Writing reports")
    write_reports(
        output_dir,
        info,
        samples,
        raw_events,
        timeline,
        cost_unit,
        write_artifacts=not args.no_artifacts,
    )
    progress.log("Done")

    for event in timeline:
        print(format_event(event))
    print()
    print(f"Video: {video}")
    print(f"Output: {output_dir}")
    return 0
