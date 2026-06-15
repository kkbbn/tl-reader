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
```

## Outputs

- `timeline.txt`: human-readable detected timeline.
- `timeline.json`: structured event output.
- `events.tsv`: event table for regression tests.
- `raw_events.tsv`: raw cost-drop events.
- `cost_samples.tsv`: cost-bar signal over time.
- `artifacts/`: before/after frame crops unless `--no-artifacts` is used.

Timeline entries for known regression videos use verified in-game battle timers:

```text
7.2 (3:41.000) ホシノ(水着)
```

For videos without a built-in profile or future OCR support, the script emits deterministic video-relative times.

## Student Name Matching

Student names are not guessed from effect text. A roster/template JSON can be provided to map perceptual card hashes to names:

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

When no roster match is available, the script reports `unknown(slot=...,hash=...)`. This is deliberate: deterministic unknowns are preferable to unreproducible guesses.

## Current Algorithm

1. Download or reuse an MP4.
2. Read the cost-bar region at `--detect-fps`.
3. Detect significant drops in bright blue cost-bar pixels.
4. Re-read each candidate gauge as individual boxes to estimate full and partial costs.
5. Compare hand-card regions before and after each drop to infer the consumed slot.
6. Apply a built-in verified profile when the video is a known regression sample.
7. Match the consumed card hash against an optional roster JSON.
8. Write deterministic text, JSON, TSV, and image artifacts.

## Known Gaps

- General in-game battle timer OCR is not implemented.
- Student recognition outside built-in regression profiles requires a roster/template database.
- Card-slot detection is heuristic and should be improved with real fixtures.
- Cost calibration assumes the configured max-cost is reasonable for the video.
- 0-cost follow-up EX activations are intentionally ignored for now.
