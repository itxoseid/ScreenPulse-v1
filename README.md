# ScreenPulse

A local, terminal-native screen-activity watcher. **Fully offline — no API keys,
no cloud calls.** ScreenPulse periodically grabs a screenshot (in memory only —
**frames are never written to disk**), throws away anything that hasn't visibly
changed, and sends the interesting frames to a local Ollama vision model for a
short description, which a local text model turns into structured JSON:
`{app, activity_summary, category, timestamp}`. Every analyzed event goes into a
local SQLite log you can summarize, search, and break down.

## Pipeline

1. **Capture** — `mss` grabs the full virtual screen every ~1.5s, kept in RAM.
2. **Diff filter** — downscaled grayscale pixel delta vs. the previous frame.
   Below threshold → discarded, no model call.
3. **Vision call** (`moondream`) — flagged frame → short scene description.
   POST to `http://localhost:11434/api/chat` (falls back to `/api/generate` for
   older model manifests).
4. **Text call** (`qwen3:4b` / `deepseek-r1:7b`) — turns the description into
   clean JSON. `<think>` blocks from reasoning models are stripped. If the text
   model is unavailable, ScreenPulse degrades to a second vision-model call.
5. **SQLite log** — `timestamp, app, activity_summary, category`.
6. **TUI** — `textual` live stream with a category-coloured feed and a running
   screen-time breakdown.

## Setup

Requires Python 3.10+ on Windows and a running [Ollama](https://ollama.com).

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Pull the models (once):

```bash
ollama pull moondream
ollama pull qwen3:4b        # or: ollama pull deepseek-r1:7b
```

> If a model shows in `ollama list` but calls fail with *"does not support
> generate/chat"*, re-pull it — older model blobs can break after an Ollama
> upgrade.

Optional: `pip install -e .` to get a `screenpulse` command instead of
`python -m screenpulse`.

## Usage

### Live watching

```bash
python -m screenpulse watch
```

`--no-tui` streams plain text to stdout instead. Stop with `q` (TUI) or `Ctrl+C`.
Runs even if only the vision model is available (vision-only mode).

### End-of-day summary

```bash
python -m screenpulse summary
python -m screenpulse summary --date 2026-09-09
```

### Searchable history

```bash
python -m screenpulse search "what was I doing at 3pm yesterday"
python -m screenpulse search "how much time did I spend in meetings this week"
```

The text model turns the question into a read-only `SELECT` against the log,
then formats an answer from the rows. Only `SELECT`/`WITH` queries are executed.

### Screen-time breakdown

```bash
python -m screenpulse breakdown
python -m screenpulse breakdown --days 7 --by app
```

## Storage & privacy

- Screenshots stay in memory; only text summaries are persisted.
- Everything runs against `localhost` Ollama — nothing leaves the machine.
- SQLite DB: `%LOCALAPPDATA%\ScreenPulse\screenpulse.db` (override with
  `SCREENPULSE_DB`).

## Configuration (env vars)

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server |
| `SCREENPULSE_VISION_MODEL` | `moondream` | frame description model |
| `SCREENPULSE_TEXT_MODEL` | `qwen3:4b` | structuring / summary / search model |
| `SCREENPULSE_INTERVAL` | `1.5` | seconds between frames |
| `SCREENPULSE_DIFF_THRESHOLD` | `0.02` | changed-pixel fraction to count as a change |
| `SCREENPULSE_MIN_CALL_GAP` | `8.0` | min seconds between vision calls |
| `SCREENPULSE_DB` | `%LOCALAPPDATA%\ScreenPulse\screenpulse.db` | log location |

## Not in v1

Focus guard, reminders, weekly trends, recap video, achievements, stuck-detector.
