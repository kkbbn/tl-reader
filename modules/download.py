from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import venv
from pathlib import Path

from .process import run


def is_url(value: str) -> bool:
    return bool(re.match(r"https?://", value))


def parse_media_id(url: str) -> str | None:
    patterns = [
        r"(?:v=|/shorts/|youtu\.be/)([-_A-Za-z0-9]{11})",
        r"/(BV[0-9A-Za-z]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _cache_root() -> Path:
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache).expanduser() / "tl-reader" / "yt-dlp"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "tl-reader" / "yt-dlp"
    return Path.home() / ".cache" / "tl-reader" / "yt-dlp"


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _importable_yt_dlp() -> bool:
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


def _system_yt_dlp_cmd() -> list[str] | None:
    executable = shutil.which("yt-dlp")
    if executable:
        return [executable]
    if _importable_yt_dlp():
        return [sys.executable, "-m", "yt_dlp"]
    return None


def _ensure_cached_yt_dlp(upgrade: bool) -> list[str]:
    venv_dir = _cache_root() / "venv"
    python = _venv_python(venv_dir)
    if not python.exists():
        print(f"Creating yt-dlp virtualenv at {venv_dir}", flush=True)
        venv.EnvBuilder(with_pip=True).create(venv_dir)

    probe = subprocess.run(
        [str(python), "-m", "yt_dlp", "--version"],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if upgrade or probe.returncode != 0:
        run([str(python), "-m", "pip", "install", "--upgrade", "yt-dlp[default]"])
    return [str(python), "-m", "yt_dlp"]


def ensure_yt_dlp(upgrade: bool = False, no_install: bool = False) -> list[str]:
    if upgrade:
        return _ensure_cached_yt_dlp(upgrade=True)
    existing = _system_yt_dlp_cmd()
    if existing:
        return existing
    if no_install:
        raise SystemExit("yt-dlp is not installed and --no-install was specified.")
    return _ensure_cached_yt_dlp(upgrade=False)


def matching_downloads(download_dir: Path, media_id: str | None) -> list[Path]:
    if not download_dir.exists():
        return []
    files = [path for path in download_dir.glob("*.mp4") if path.is_file()]
    if media_id:
        files = [path for path in files if f"[{media_id}]" in path.name]
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)


def download_video(
    url: str,
    download_dir: Path,
    *,
    force: bool = False,
    upgrade_yt_dlp: bool = False,
    no_install: bool = False,
    extra_args: list[str] | None = None,
) -> Path:
    download_dir.mkdir(parents=True, exist_ok=True)
    media_id = parse_media_id(url)
    if not force:
        matches = matching_downloads(download_dir, media_id)
        if matches:
            print(f"Reusing downloaded MP4: {matches[0]}")
            return matches[0].resolve()

    before = {path.resolve() for path in download_dir.glob("*.mp4")}
    yt_dlp = ensure_yt_dlp(upgrade=upgrade_yt_dlp, no_install=no_install)
    ffmpeg_available = shutil.which("ffmpeg") is not None
    fmt = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b" if ffmpeg_available else "b[ext=mp4]/best[ext=mp4]"
    cmd = [
        *yt_dlp,
        "--newline",
        "--paths",
        str(download_dir),
        "--output",
        "%(title).200B [%(id)s].%(ext)s",
        "--format",
        fmt,
        "--no-playlist",
    ]
    if ffmpeg_available:
        cmd.extend(["--merge-output-format", "mp4", "--remux-video", "mp4"])
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(url)
    run(cmd)

    matches = matching_downloads(download_dir, media_id)
    if matches:
        return matches[0].resolve()
    after = {path.resolve() for path in download_dir.glob("*.mp4")}
    new_files = sorted(after - before, key=lambda path: path.stat().st_mtime, reverse=True)
    if new_files:
        return new_files[0]
    raise SystemExit("Download finished, but no MP4 could be located.")


def ensure_video(
    input_value: str,
    download_dir: Path,
    *,
    force_download: bool = False,
    upgrade_yt_dlp: bool = False,
    no_install: bool = False,
    extra_args: list[str] | None = None,
) -> Path:
    if not is_url(input_value):
        path = Path(input_value).expanduser()
        if not path.exists():
            raise SystemExit(f"Input MP4 not found: {path}")
        return path.resolve()
    return download_video(
        input_value,
        download_dir.expanduser(),
        force=force_download,
        upgrade_yt_dlp=upgrade_yt_dlp,
        no_install=no_install,
        extra_args=extra_args,
    )
