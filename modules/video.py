from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .models import Frame, Rect, VideoInfo
from .process import capture, run


def ffprobe(video: Path) -> VideoInfo:
    raw = capture(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,width,height,r_frame_rate,duration",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video),
        ],
    )
    data = json.loads(raw)
    stream = next(item for item in data["streams"] if item.get("codec_type") == "video")
    return VideoInfo(
        path=video,
        width=int(stream["width"]),
        height=int(stream["height"]),
        duration=float(data["format"]["duration"]),
        frame_rate=stream.get("r_frame_rate", ""),
    )


def read_frame(video: Path, info: VideoInfo, time_sec: float, rect: Rect | None = None) -> Frame:
    vf = []
    width = info.width
    height = info.height
    if rect:
        vf.append(f"crop={rect.width}:{rect.height}:{rect.x}:{rect.y}")
        width = rect.width
        height = rect.height
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, time_sec):.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
    ]
    if vf:
        cmd.extend(["-vf", ",".join(vf)])
    cmd.extend(["-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    data = subprocess.check_output(cmd)
    expected = width * height * 3
    if len(data) < expected:
        raise RuntimeError(f"ffmpeg returned an incomplete frame at {time_sec:.3f}s")
    return Frame(time=time_sec, width=width, height=height, data=data[:expected])


def iter_frames(video: Path, rect: Rect, fps: float, start: float = 0.0, duration: float | None = None):
    vf = f"crop={rect.width}:{rect.height}:{rect.x}:{rect.y},fps={fps}"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
    ]
    if start > 0:
        cmd.extend(["-ss", f"{start:.3f}"])
    cmd.extend(["-i", str(video)])
    if duration is not None:
        cmd.extend(["-t", f"{duration:.3f}"])
    cmd.extend(["-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    assert process.stdout is not None
    frame_size = rect.width * rect.height * 3
    index = 0
    try:
        while True:
            data = process.stdout.read(frame_size)
            if len(data) < frame_size:
                break
            yield Frame(start + index / fps, rect.width, rect.height, data)
            index += 1
    finally:
        process.stdout.close()
        process.wait()


def save_frame_jpeg(video: Path, time_sec: float, output: Path, rect: Rect | None = None) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    vf = []
    if rect:
        vf.append(f"crop={rect.width}:{rect.height}:{rect.x}:{rect.y}")
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, time_sec):.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
    ]
    if vf:
        cmd.extend(["-vf", ",".join(vf)])
    cmd.append(str(output))
    run(cmd)
