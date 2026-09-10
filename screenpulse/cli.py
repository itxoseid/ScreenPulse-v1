"""Command-line entry point for ScreenPulse."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

from .config import TEXT_MODEL, VISION_MODEL, Settings
from .db import init_db
from .ollama import OllamaClient


def _has(models: dict[str, str], name: str) -> bool:
    return name.split(":")[0] in models or name in models.values()


def _require_ollama(*, need_vision: bool, text_optional: bool = False) -> None:
    client = OllamaClient()
    if not client.is_up():
        raise SystemExit(
            f"Cannot reach Ollama at {client.host}. Start it with `ollama serve` "
            "(or the Ollama app) and try again."
        )
    models = {m.split(":")[0]: m for m in client.available_models()}

    if need_vision and not _has(models, VISION_MODEL):
        raise SystemExit(f"Missing vision model '{VISION_MODEL}'. Run: ollama pull {VISION_MODEL}")

    if not _has(models, TEXT_MODEL):
        msg = (
            f"Text model '{TEXT_MODEL}' is not available. Run: ollama pull {TEXT_MODEL}\n"
            "(If it appears in `ollama list` but still fails, re-pull it — older model "
            "blobs can break after an Ollama upgrade.)"
        )
        if text_optional:
            print(f"warning: {msg}\nContinuing in vision-only mode.\n", file=sys.stderr)
        else:
            raise SystemExit(msg)


def _cmd_watch(args: argparse.Namespace) -> int:
    _require_ollama(need_vision=True, text_optional=True)
    settings = Settings.from_env()
    if args.no_tui:
        from .pipeline import Pipeline

        pipe = Pipeline(
            settings,
            on_event=lambda e: print(
                f"{e.ts:%H:%M:%S}  [{e.category}] {e.app}: {e.activity_summary}"
            ),
            on_status=lambda s: print(f"  … {s}", file=sys.stderr),
        )
        try:
            pipe.run()
        except KeyboardInterrupt:
            pipe.stop()
        return 0

    from .tui import run_tui

    run_tui(settings)
    return 0


def _cmd_summary(args: argparse.Namespace) -> int:
    _require_ollama(need_vision=False)
    from .reports import eod_summary

    day = date.fromisoformat(args.date) if args.date else date.today()
    print(eod_summary(day))
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    _require_ollama(need_vision=False)
    from .reports import search_history

    question = " ".join(args.query)
    print(search_history(question))
    return 0


def _cmd_breakdown(args: argparse.Namespace) -> int:
    from .reports import breakdown

    print(breakdown(days=args.days, group_by=args.by))
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from .reports import export_log

    text = export_log(fmt=args.format, days=args.days)
    if args.out:
        from pathlib import Path

        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)
    return 0


def _cmd_prune(args: argparse.Namespace) -> int:
    from .db import connect, prune_events

    with connect() as conn:
        removed = prune_events(conn, keep_days=args.days)
    print(f"Removed {removed} event(s) older than {args.days} day(s).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="screenpulse",
        description="Local, offline screen-activity watcher powered by Ollama.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    w = sub.add_parser("watch", help="run the live capture pipeline + TUI")
    w.add_argument("--no-tui", action="store_true", help="plain stdout instead of the TUI")
    w.set_defaults(func=_cmd_watch)

    s = sub.add_parser("summary", help="generate an end-of-day summary")
    s.add_argument("--date", help="YYYY-MM-DD (default: today)")
    s.set_defaults(func=_cmd_summary)

    q = sub.add_parser("search", help="ask a natural-language question about your history")
    q.add_argument("query", nargs="+", help='e.g. "what was I doing at 3pm yesterday"')
    q.set_defaults(func=_cmd_search)

    b = sub.add_parser("breakdown", help="screen-time breakdown bars")
    b.add_argument("--days", type=int, default=1)
    b.add_argument("--by", choices=("category", "app"), default="category")
    b.set_defaults(func=_cmd_breakdown)

    e = sub.add_parser("export", help="export the log as CSV or JSON")
    e.add_argument("--format", choices=("csv", "json"), default="csv")
    e.add_argument("--days", type=int, default=None, help="only the last N days")
    e.add_argument("--out", help="write to this file instead of stdout")
    e.set_defaults(func=_cmd_export)

    pr = sub.add_parser("prune", help="delete events older than N days")
    pr.add_argument("--days", type=int, required=True)
    pr.set_defaults(func=_cmd_prune)

    return p


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    init_db()
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
