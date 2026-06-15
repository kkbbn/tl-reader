# tl-reader

Standalone Python prototype for extracting Blue Archive paid EX skill timelines from gameplay videos without LLM assistance.

The script is intentionally dependency-light: it uses Python standard library code plus external `ffmpeg`/`ffprobe`, and optionally `yt-dlp` for URL inputs. Image analysis is currently pure Python over raw RGB frames.

## Usage

```bash
python3 tl_reader.py "https://www.youtube.com/watch?v=..."
python3 tl_reader.py "/path/to/video.mp4"
```

Default paths:

- Downloaded videos: `~/Downloads/yt-dlp`
- Reports: `~/Downloads/tl-reader/<video-name>/`

Useful options:

```bash
python3 tl_reader.py video.mp4 --no-artifacts
python3 tl_reader.py video.mp4 --detect-fps 60
python3 tl_reader.py video.mp4 --max-cost 11
python3 tl_reader.py video.mp4 --roster cards.json
python3 tl_reader.py video.mp4 --refresh-wikiru
```

The script downloads current SchaleDB student icons into `cache/schaledb/` and
Wikiru fallback data into `cache/wikiru-icons/` on first use. The `cache/`
directory is project-local and ignored by git.

## Outputs

- `timeline.txt`: human-readable detected timeline.
- `timeline.json`: structured event output.
- `events.tsv`: event table for regression tests.
- `raw_events.tsv`: raw cost-drop events.
- `cost_samples.tsv`: cost-bar signal over time.
- `artifacts/`: before/after frame crops unless `--no-artifacts` is used.

Timeline entries use the in-game battle timer read from the right-top timer UI:

```text
7.2 (3:40.900) ホシノ(水着)
```

`video_time` is still written to JSON/TSV reports as a diagnostic field, but it
is not used in `timeline.txt`.

## Student Name Matching

Student names are not guessed from effect text. By default, the script compares
the consumed skill-card portrait against current SchaleDB card icons, with
Wikiru icons and metadata as fallback. A roster/template JSON can still be
provided to override or supplement visual matching with perceptual card hashes:

```json
{
  "cards": [
    {
      "name": "ヒナ(ドレス)",
      "cost": 6,
      "hash": "005c7e7e7c3cfc80"
    }
  ]
}
```

When no roster or visual match clears the configured threshold, the script
reports `unknown(slot=...,hash=...)`. This is deliberate: deterministic unknowns
are preferable to unreproducible guesses.

## Current Algorithm

1. Download or reuse an MP4.
2. Read the cost-bar region at `--detect-fps`.
3. Detect significant drops in bright blue cost-bar pixels.
4. Re-read each candidate gauge as individual boxes to estimate full and partial costs.
5. Compare hand-card regions before and after each drop to infer the consumed slot.
6. Match the consumed card against an optional roster JSON, cached SchaleDB icons, and Wikiru fallback data.
7. OCR the fixed-format battle timer (`MM:SS.mmm`) from the right-top timer UI.
8. Write deterministic text, JSON, TSV, and image artifacts.

## Known Gaps

- Timer OCR is specialized for the Blue Archive battle timer font and layout; it is not a general text OCR engine.
- Card-slot detection is heuristic and should be improved with real fixtures.
- Visual matching is deterministic, but low-resolution, greyed, or overlaid cards can still be ambiguous.
- Cost calibration assumes the configured max-cost is reasonable for the video.
- 0-cost follow-up EX activations are intentionally ignored for now.
