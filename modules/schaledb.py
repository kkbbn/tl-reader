from __future__ import annotations

import base64
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from .image_match import FEATURE_SIZE, IconFeature, icon_feature
from .progress import Progress


STUDENTS_URL = "https://schaledb.com/data/jp/students.json"
ICON_URL = "https://schaledb.com/images/student/icon/{id}.webp?tl-reader=1"
FEATURES_VERSION = 2


@dataclass(frozen=True)
class SchaleFeatures:
    features: list[IconFeature]
    costs: dict[str, int]


def default_cache_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "cache" / "schaledb"


def _request(url: str) -> Request:
    return Request(url, headers={"User-Agent": "tl-reader/0.1"})


def _normalize_name(name: str) -> str:
    return name.replace("（", "(").replace("）", ")")


def _student_cost(student: dict) -> int | None:
    skills = student.get("Skills", [])
    if isinstance(skills, dict):
        values = [skills.get("Ex", {})]
    else:
        values = skills
    for skill in values:
        if not isinstance(skill, dict):
            continue
        if skill.get("SkillType") != "ex":
            if "Cost" not in skill:
                continue
        costs = [int(value) for value in skill.get("Cost", []) if isinstance(value, int)]
        costs = [value for value in costs if 0 < value <= 10]
        if costs:
            return min(costs)
    return None


def _decode_icon_rgba(path: Path) -> bytes:
    return subprocess.check_output(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            f"scale={FEATURE_SIZE}:{FEATURE_SIZE}:flags=area",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-",
        ],
    )


def load_features(
    cache_dir: Path | None = None,
    *,
    refresh: bool = False,
    progress: Progress | None = None,
) -> SchaleFeatures:
    directory = default_cache_dir() if cache_dir is None else cache_dir.expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    features_path = directory / "features.json"
    if not refresh and features_path.exists():
        data = json.loads(features_path.read_text(encoding="utf-8"))
        if data.get("version") == FEATURES_VERSION and data.get("feature_size") == FEATURE_SIZE:
            features = []
            for entry in data.get("entries", []):
                feature = icon_feature(
                    str(entry["name"]),
                    str(entry["source_url"]),
                    base64.b64decode(str(entry["rgba"])),
                    kind="schaledb",
                )
                if feature is not None:
                    features.append(feature)
            costs = {str(key): int(value) for key, value in data.get("costs", {}).items()}
            if features:
                if progress is not None:
                    progress.log(f"Loaded SchaleDB student icon features: {len(features)} entries")
                return SchaleFeatures(features, costs)

    if progress is not None:
        progress.log(f"Fetching SchaleDB student data into {directory}")
    raw_students = json.loads(urlopen(_request(STUDENTS_URL), timeout=30).read().decode("utf-8"))
    if isinstance(raw_students, dict):
        students = list(raw_students.values())
    else:
        students = list(raw_students)
    icons_dir = directory / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    costs: dict[str, int] = {}
    features: list[IconFeature] = []
    ticker = progress.every(5.0) if progress is not None else None
    for index, student in enumerate(students, start=1):
        student_id = int(student["Id"])
        name = _normalize_name(str(student["Name"]))
        source_url = ICON_URL.format(id=student_id)
        path = icons_dir / f"{student_id}.webp"
        if not path.exists() or refresh:
            try:
                path.write_bytes(urlopen(_request(source_url), timeout=30).read())
            except Exception:
                continue
        try:
            rgba = _decode_icon_rgba(path)
        except Exception:
            continue
        feature = icon_feature(name, source_url, rgba, kind="schaledb")
        if feature is None:
            continue
        features.append(feature)
        entries.append(
            {
                "id": student_id,
                "name": name,
                "source_url": source_url,
                "rgba": base64.b64encode(rgba).decode("ascii"),
            },
        )
        cost = _student_cost(student)
        if cost is not None:
            costs[name] = cost
        if ticker is not None:
            ticker.log(f"Caching SchaleDB icons: {index}/{len(students)}")

    features_path.write_text(
        json.dumps(
            {
                "version": FEATURES_VERSION,
                "feature_size": FEATURE_SIZE,
                "entries": entries,
                "costs": costs,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    if progress is not None:
        progress.log(f"Built SchaleDB student icon features: {len(features)} entries")
    return SchaleFeatures(features, costs)
