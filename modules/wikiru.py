from __future__ import annotations

import base64
import json
import re
import subprocess
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from .image_match import FEATURE_SIZE, IconFeature, ImageMatch, icon_feature, rank_card_histograms, rank_card_icons
from .models import Frame
from .progress import Progress
from .schaledb import load_features as load_schaledb_features


CHARACTER_LIST_URL = "https://bluearchive.wikiru.jp/?" + quote("キャラクター一覧")
FEATURES_VERSION = 1
COSTS_VERSION = 3
ART_FEATURES_VERSION = 1
METADATA_VERSION = 1


@dataclass(frozen=True)
class WikiruIcon:
    name: str
    source_url: str
    path: Path


@dataclass(frozen=True)
class WikiruArt:
    name: str
    source_url: str
    path: Path


class _ImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "img":
            self.images.append(dict(attrs))


def project_cache_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "cache"


def default_icon_cache_dir() -> Path:
    return project_cache_dir() / "wikiru-icons"


def _request(url: str) -> Request:
    return Request(url, headers={"User-Agent": "tl-reader/0.1"})


def _normalize_name(alt: str) -> str:
    raw = alt[: -len("_icon.png")]
    name = raw.replace("（", "(").replace("）", ")")
    if "_" in name and "(" not in name:
        base, variant = name.split("_", 1)
        name = f"{base}({variant})"
    return name


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w一-龯ぁ-んァ-ンー()]+", "_", name).strip("_") + ".png"


def _page_name(name: str) -> str:
    return name.replace("(", "（").replace(")", "）")


def _page_url(name: str) -> str:
    return "https://bluearchive.wikiru.jp/?" + quote(_page_name(name))


def parse_icon_index(html: str) -> list[tuple[str, str]]:
    parser = _ImageParser()
    parser.feed(html)
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for image in parser.images:
        alt = image.get("alt") or ""
        src = image.get("data-src") or image.get("src") or ""
        if not alt.endswith("_icon.png"):
            continue
        if image.get("width") != "60" or image.get("height") != "60":
            continue
        name = _normalize_name(alt)
        if name in seen:
            continue
        seen.add(name)
        entries.append((name, urljoin(CHARACTER_LIST_URL, src)))
    return entries


def download_icon_index(cache_dir: Path, progress: Progress | None = None) -> list[WikiruIcon]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    if progress is not None:
        progress.log(f"Fetching Wikiru character list into {cache_dir}")
    html = urlopen(_request(CHARACTER_LIST_URL), timeout=30).read().decode("utf-8", errors="replace")
    parsed = parse_icon_index(html)
    icons: list[WikiruIcon] = []
    ticker = progress.every(5.0) if progress is not None else None
    downloaded = 0
    for index, (name, source_url) in enumerate(parsed, start=1):
        path = cache_dir / _safe_filename(name)
        if not path.exists():
            path.write_bytes(urlopen(_request(source_url), timeout=30).read())
            downloaded += 1
        if ticker is not None:
            ticker.log(f"Caching Wikiru icons: {index}/{len(parsed)}")
        icons.append(WikiruIcon(name=name, source_url=source_url, path=path))
    (cache_dir / "manifest.json").write_text(
        json.dumps(
            {
                "source_url": CHARACTER_LIST_URL,
                "entries": [
                    {"name": icon.name, "source_url": icon.source_url, "path": icon.path.name}
                    for icon in icons
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if progress is not None:
        progress.log(f"Wikiru icon index ready: {len(icons)} icons ({downloaded} downloaded)")
    return icons


def load_icon_index(cache_dir: Path, *, refresh: bool = False, progress: Progress | None = None) -> list[WikiruIcon]:
    manifest = cache_dir / "manifest.json"
    if refresh or not manifest.exists():
        return download_icon_index(cache_dir, progress=progress)

    data = json.loads(manifest.read_text(encoding="utf-8"))
    icons = [
        WikiruIcon(
            name=str(entry["name"]),
            source_url=str(entry["source_url"]),
            path=cache_dir / str(entry["path"]),
        )
        for entry in data.get("entries", [])
    ]
    if not icons or any(not icon.path.exists() for icon in icons):
        return download_icon_index(cache_dir, progress=progress)
    if progress is not None:
        progress.log(f"Loaded Wikiru icon index: {len(icons)} icons")
    return icons


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


def _image_size(path: Path) -> tuple[int, int]:
    data = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ],
        ),
    )
    stream = data["streams"][0]
    return int(stream["width"]), int(stream["height"])


def _decode_rgba(path: Path) -> tuple[bytes, int, int]:
    width, height = _image_size(path)
    rgba = subprocess.check_output(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-",
        ],
    )
    return rgba, width, height


def _alpha_bbox(rgba: bytes, width: int, height: int) -> tuple[int, int, int, int]:
    min_x = width
    min_y = height
    max_x = 0
    max_y = 0
    found = False
    for y in range(height):
        row = y * width * 4
        for x in range(width):
            if rgba[row + x * 4 + 3] <= 32:
                continue
            found = True
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x + 1)
            max_y = max(max_y, y + 1)
    if not found:
        return 0, 0, width, height
    return min_x, min_y, max_x, max_y


def _resize_rgba_crop(rgba: bytes, width: int, height: int, rect: tuple[int, int, int, int]) -> bytes:
    x0, y0, crop_width, crop_height = rect
    output = bytearray(FEATURE_SIZE * FEATURE_SIZE * 4)
    for out_y in range(FEATURE_SIZE):
        src_y = round(y0 + (out_y + 0.5) * crop_height / FEATURE_SIZE - 0.5)
        for out_x in range(FEATURE_SIZE):
            src_x = round(x0 + (out_x + 0.5) * crop_width / FEATURE_SIZE - 0.5)
            dst = (out_y * FEATURE_SIZE + out_x) * 4
            if 0 <= src_x < width and 0 <= src_y < height:
                src = (src_y * width + src_x) * 4
                output[dst : dst + 4] = rgba[src : src + 4]
    return bytes(output)


def _art_feature_rects(rgba: bytes, width: int, height: int) -> list[tuple[int, int, int, int]]:
    min_x, min_y, max_x, max_y = _alpha_bbox(rgba, width, height)
    body_width = max(1, max_x - min_x)
    body_height = max(1, max_y - min_y)
    sizes = (0.20, 0.27, 0.35, 0.45, 0.58)
    x_centers = (0.40, 0.50, 0.60)
    y_centers = (0.16, 0.24, 0.32, 0.42)
    rects: list[tuple[int, int, int, int]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for size_ratio in sizes:
        side = max(24, round(body_height * size_ratio))
        for x_ratio in x_centers:
            for y_ratio in y_centers:
                center_x = min_x + body_width * x_ratio
                center_y = min_y + body_height * y_ratio
                rect = (round(center_x - side / 2), round(center_y - side / 2), side, side)
                if rect in seen:
                    continue
                seen.add(rect)
                rects.append(rect)
    return rects


def _select_art_source(name: str, html: str, page_url: str) -> str | None:
    parser = _ImageParser()
    parser.feed(html)
    best: tuple[int, str] | None = None
    for image in parser.images:
        alt = (image.get("alt") or "").replace("（", "(").replace("）", ")")
        src = image.get("data-src") or image.get("src") or ""
        if not alt.startswith(name) or not src:
            continue
        if not alt.endswith((".png", ".jpg", ".jpeg")):
            continue
        if any(marker in alt for marker in ("_icon", "SD", "メモリアル", "(小)")):
            continue
        try:
            area = int(image.get("width") or 0) * int(image.get("height") or 0)
            height = int(image.get("height") or 0)
        except ValueError:
            continue
        if height < 350:
            continue
        source_url = urljoin(page_url, src)
        if best is None or area > best[0]:
            best = (area, source_url)
    return None if best is None else best[1]


def download_art(cache_dir: Path, name: str) -> WikiruArt | None:
    art_dir = cache_dir / "art"
    art_dir.mkdir(parents=True, exist_ok=True)
    page_url = _page_url(name)
    html = urlopen(_request(page_url), timeout=30).read().decode("utf-8", errors="replace")
    source_url = _select_art_source(name, html, page_url)
    if source_url is None:
        return None
    suffix = Path(source_url).suffix
    path = art_dir / (_safe_filename(name).removesuffix(".png") + (suffix if suffix else ".png"))
    if not path.exists():
        path.write_bytes(urlopen(_request(source_url), timeout=30).read())
    return WikiruArt(name=name, source_url=source_url, path=path)


def load_art_features(cache_dir: Path, name: str, progress: Progress | None = None) -> list[IconFeature]:
    features_dir = cache_dir / "art-features"
    features_dir.mkdir(parents=True, exist_ok=True)
    features_path = features_dir / (_safe_filename(name).removesuffix(".png") + ".json")
    if features_path.exists():
        data = json.loads(features_path.read_text(encoding="utf-8"))
        if data.get("version") == ART_FEATURES_VERSION and data.get("feature_size") == FEATURE_SIZE:
            features = []
            for entry in data.get("entries", []):
                feature = icon_feature(
                    name,
                    str(entry["source_url"]),
                    base64.b64decode(str(entry["rgba"])),
                    kind="art",
                )
                if feature is not None:
                    features.append(feature)
            if features:
                return features

    if progress is not None:
        progress.log(f"Caching Wikiru full art: {name}")
    art = download_art(cache_dir, name)
    if art is None:
        return []
    rgba, width, height = _decode_rgba(art.path)
    entries = []
    features: list[IconFeature] = []
    for rect in _art_feature_rects(rgba, width, height):
        crop = _resize_rgba_crop(rgba, width, height, rect)
        feature = icon_feature(name, art.source_url, crop, kind="art")
        if feature is None:
            continue
        features.append(feature)
        entries.append({"source_url": art.source_url, "rgba": base64.b64encode(crop).decode("ascii")})

    features_path.write_text(
        json.dumps(
            {
                "version": ART_FEATURES_VERSION,
                "feature_size": FEATURE_SIZE,
                "entries": entries,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return features


def load_icon_features(cache_dir: Path, *, refresh: bool = False, progress: Progress | None = None) -> list[IconFeature]:
    icons = load_icon_index(cache_dir, refresh=refresh, progress=progress)
    features_path = cache_dir / "features.json"
    if not refresh and features_path.exists():
        data = json.loads(features_path.read_text(encoding="utf-8"))
        if data.get("version") == FEATURES_VERSION and data.get("feature_size") == FEATURE_SIZE:
            features = []
            for entry in data.get("entries", []):
                feature = icon_feature(
                    str(entry["name"]),
                    str(entry["source_url"]),
                    base64.b64decode(str(entry["rgba"])),
                )
                if feature is not None:
                    features.append(feature)
            if features:
                if progress is not None:
                    progress.log(f"Loaded Wikiru icon features: {len(features)} entries")
                return features

    if progress is not None:
        progress.log("Building Wikiru icon features")
    ticker = progress.every(5.0) if progress is not None else None
    feature_entries = []
    features: list[IconFeature] = []
    url_by_name = {icon.name: icon.source_url for icon in icons}
    for index, icon in enumerate(icons, start=1):
        rgba = _decode_icon_rgba(icon.path)
        feature = icon_feature(icon.name, icon.source_url, rgba)
        if feature is None:
            continue
        features.append(feature)
        feature_entries.append(
            {
                "name": icon.name,
                "source_url": url_by_name[icon.name],
                "rgba": base64.b64encode(rgba).decode("ascii"),
            },
        )
        if ticker is not None:
            ticker.log(f"Building Wikiru icon features: {index}/{len(icons)}")
    features_path.write_text(
        json.dumps(
            {
                "version": FEATURES_VERSION,
                "feature_size": FEATURE_SIZE,
                "entries": feature_entries,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    if progress is not None:
        progress.log(f"Built Wikiru icon features: {len(features)} entries")
    return features


class WikiruIconMatcher:
    def __init__(
        self,
        icons: list[IconFeature],
        threshold: float,
        cache_dir: Path,
        progress: Progress | None = None,
        known_costs: dict[str, int] | None = None,
    ) -> None:
        self.icons = icons
        self.threshold = threshold
        self.cache_dir = cache_dir
        self.progress = progress
        self.known_costs = {} if known_costs is None else known_costs
        self.costs_path = cache_dir / "costs.json"
        self.costs: dict[str, int | None] = self._load_costs()
        self.metadata_path = cache_dir / "metadata.json"
        self.metadata: dict[str, dict[str, bool]] = self._load_metadata()
        self.art_features: dict[str, list[IconFeature]] = {}
        self.schaledb_icons = [icon for icon in icons if icon.kind == "schaledb"]

    @classmethod
    def load(
        cls,
        cache_dir: Path | None = None,
        *,
        refresh: bool = False,
        threshold: float = 0.25,
        progress: Progress | None = None,
    ) -> "WikiruIconMatcher":
        directory = default_icon_cache_dir() if cache_dir is None else cache_dir.expanduser()
        schaledb = load_schaledb_features(refresh=refresh, progress=progress)
        wikiru_icons = load_icon_features(directory, refresh=refresh, progress=progress)
        return cls(
            [*schaledb.features, *wikiru_icons],
            threshold=threshold,
            cache_dir=directory,
            progress=progress,
            known_costs=schaledb.costs,
        )

    def _load_costs(self) -> dict[str, int | None]:
        if not self.costs_path.exists():
            return {}
        data = json.loads(self.costs_path.read_text(encoding="utf-8"))
        if data.get("version") != COSTS_VERSION:
            return {}
        return {str(key): value for key, value in data.get("costs", {}).items()}

    def _save_costs(self) -> None:
        self.costs_path.write_text(
            json.dumps({"version": COSTS_VERSION, "costs": self.costs}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _load_metadata(self) -> dict[str, dict[str, bool]]:
        if not self.metadata_path.exists():
            return {}
        data = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        if data.get("version") != METADATA_VERSION:
            return {}
        metadata = data.get("students", {})
        if not isinstance(metadata, dict):
            return {}
        return {str(key): dict(value) for key, value in metadata.items() if isinstance(value, dict)}

    def _save_metadata(self) -> None:
        self.metadata_path.write_text(
            json.dumps({"version": METADATA_VERSION, "students": self.metadata}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _fetch_cost(self, name: str) -> int | None:
        url = _page_url(name)
        html = urlopen(_request(url), timeout=30).read().decode("utf-8", errors="replace")
        anchor = html.find('id="ExSkill"')
        if anchor < 0:
            return None
        table_end = html.find("</table>", anchor)
        if table_end < 0:
            return None
        table = html[anchor:table_end]
        numbers: list[int] = []
        for row in re.findall(r"<tr>(.*?)</tr>", table, flags=re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)
            if len(cells) < 2:
                continue
            level = re.sub(r"<[^>]+>", "", cells[0]).strip()
            cost_text = re.sub(r"<[^>]+>", "", cells[1]).strip()
            if not re.fullmatch(r"[1-5]", level):
                continue
            if not re.fullmatch(r"[0-9\s→ー~～-]+(?:\(ExLv5\))?", cost_text):
                continue
            numbers.extend(int(value) for value in re.findall(r"\d+", cost_text))
        numbers = [value for value in numbers if 0 < value <= 10]
        if not numbers:
            return None
        return min(numbers)

    def _fetch_has_alternate_ex(self, name: str) -> bool:
        html = urlopen(_request(_page_url(name)), timeout=30).read().decode("utf-8", errors="replace")
        anchor = html.find('id="ExSkill"')
        if anchor < 0:
            return False
        section_end = html.find('id="NormalSkill"', anchor)
        if section_end < 0:
            section_end = html.find('id="PassiveSkill"', anchor)
        section = html[anchor : section_end if section_end > anchor else anchor + 8000]
        text = re.sub(r"<[^>]+>", " ", section)
        text = re.sub(r"\s+", " ", text)
        return "EXスキル（" in text and bool(re.search(r"Lv\s*コスト\s*効果.*?\b0\b", text))

    def cost_for(self, name: str) -> int | None:
        if name in self.known_costs:
            return self.known_costs[name]
        if name not in self.costs:
            try:
                self.costs[name] = self._fetch_cost(name)
            except Exception:
                self.costs[name] = None
            self._save_costs()
        return self.costs[name]

    def has_alternate_ex(self, name: str) -> bool:
        entry = self.metadata.get(name)
        if entry is not None and "alternate_ex" in entry:
            return bool(entry["alternate_ex"])
        try:
            value = self._fetch_has_alternate_ex(name)
        except Exception:
            value = False
        self.metadata[name] = {**self.metadata.get(name, {}), "alternate_ex": value}
        self._save_metadata()
        return value

    def _art_for(self, name: str) -> list[IconFeature]:
        if name not in self.art_features:
            try:
                self.art_features[name] = load_art_features(self.cache_dir, name, progress=self.progress)
            except Exception:
                self.art_features[name] = []
        return self.art_features[name]

    def _candidate_names(self, icon_matches: list[ImageMatch], expected_cost: float | None) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()

        def add(name: str) -> None:
            if name in seen:
                return
            seen.add(name)
            names.append(name)

        if expected_cost is not None and 1.0 <= expected_cost <= 6.5:
            rounded_cost = int(round(expected_cost))
            exact_count = 0
            for match in icon_matches[:90]:
                cost = self.cost_for(match.name)
                if cost is not None and cost == rounded_cost:
                    add(match.name)
                    exact_count += 1
                    if exact_count >= 22:
                        break
            for match in icon_matches[:8]:
                add(match.name)
        else:
            for match in icon_matches[:16]:
                add(match.name)
        return names

    def _combine_matches(
        self,
        icon_matches: list[ImageMatch],
        histogram_matches: list[ImageMatch],
        art_matches: list[ImageMatch],
        expected_cost: float | None,
    ) -> ImageMatch | None:
        matches_by_name: dict[str, dict[str, ImageMatch]] = {}
        for match in icon_matches:
            matches_by_name.setdefault(match.name, {})["icon"] = match
        for match in histogram_matches:
            matches_by_name.setdefault(match.name, {})["histogram"] = match
        for match in art_matches:
            matches_by_name.setdefault(match.name, {})["art"] = match

        if not matches_by_name:
            return None

        rounded_cost = int(round(expected_cost)) if expected_cost is not None and 1.0 <= expected_cost <= 6.5 else None
        ranks: dict[tuple[str, str], int] = {}
        for index, match in enumerate(icon_matches, start=1):
            ranks[(match.name, "icon")] = index
        for index, match in enumerate(histogram_matches, start=1):
            ranks[(match.name, "histogram")] = index
        for index, match in enumerate(art_matches, start=1):
            ranks[(match.name, "art")] = index

        def aggregate(name: str, values: dict[str, ImageMatch]) -> tuple[float, float]:
            score = 0.0
            if "histogram" in values:
                rank = ranks.get((name, "histogram"), 999)
                hist_distance = values["histogram"].distance
                hist_weight = 1.7 if hist_distance < 0.55 else 0.55
                score += hist_weight / (rank + 2)
                score += max(0.0, 0.55 - hist_distance) * 1.0
                if "icon" in values and hist_distance < 0.80:
                    score += 0.08
            if "icon" in values:
                rank = ranks.get((name, "icon"), 999)
                score += 1.4 / (rank + 4)
                score += max(0.0, 1.18 - values["icon"].distance) * 0.35
            if "art" in values:
                rank = ranks.get((name, "art"), 999)
                score += 0.30 / (rank + 5)
                score += max(0.0, 1.15 - values["art"].distance) * 0.06
            if rounded_cost is not None:
                cost = self.cost_for(name)
                if cost is not None:
                    score -= min(1.0, abs(cost - rounded_cost) * 0.45)
            return score, -min((match.distance for match in values.values()), default=9.0)

        best_name = max(matches_by_name, key=lambda name: aggregate(name, matches_by_name[name]))
        best_values = matches_by_name[best_name]
        best = max(best_values.values(), key=lambda match: match.score)
        cost = self.cost_for(best_name)
        aggregate_score = aggregate(best_name, best_values)[0]
        score = max(0.0, min(1.0, aggregate_score))
        return ImageMatch(best.name, best.source_url, best.distance, score, best.crop, cost, best.kind)

    def _rerank(self, matches: list[ImageMatch], expected_cost: float | None, card: Frame) -> ImageMatch | None:
        if not matches:
            return None
        rounded_cost = int(round(expected_cost)) if expected_cost is not None and 1.0 <= expected_cost <= 6.5 else None
        histogram_matches = rank_card_histograms(card, self.schaledb_icons, limit=160) if self.schaledb_icons else []
        best_icon = matches[0]
        best_cost = self.cost_for(best_icon.name)
        cost_compatible = rounded_cost is None or best_cost is None or abs(best_cost - rounded_cost) <= 1
        next_distance = matches[1].distance if len(matches) > 1 else best_icon.distance + 1.0
        if (
            cost_compatible
            and (
                best_icon.distance <= 0.95
                or (best_icon.distance <= 1.05 and next_distance - best_icon.distance >= 0.03)
            )
        ):
            score = max(0.0, min(1.0, 1.0 - best_icon.distance / 1.35))
            return ImageMatch(
                best_icon.name,
                best_icon.source_url,
                best_icon.distance,
                score,
                best_icon.crop,
                best_cost,
                best_icon.kind,
            )
        art_matches: list[ImageMatch] = []
        return self._combine_matches(matches, histogram_matches, art_matches, expected_cost)

    def match(self, card: Frame, expected_cost: float | None = None):
        match = self._rerank(rank_card_icons(card, self.icons, limit=160), expected_cost, card)
        if match is None or match.score < self.threshold:
            return None
        return match
