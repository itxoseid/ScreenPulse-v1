"""EOD summary, natural-language history search, and screen-time breakdown.

All model calls go to the local Ollama text model. No cloud, no API keys.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Optional

from .config import TEXT_MODEL
from .db import connect, events_for_day, run_query
from .ollama import OllamaClient

# Rough minutes attributed to each analyzed event (capture is event-sampled, not
# continuous, so this is an estimate based on the call gap).
MINUTES_PER_EVENT = 0.5


def _rows_to_text(rows) -> str:
    if not rows:
        return "(no rows)"
    keys = rows[0].keys()
    if {"ts", "app", "activity_summary", "category"} <= set(keys):
        return "\n".join(
            f"{r['ts']}  [{r['category']}]  {r['app']}: {r['activity_summary']}"
            for r in rows
        )
    # Projected/aggregated query: render generically.
    return "\n".join(
        ", ".join(f"{k}={r[k]}" for k in keys) for r in rows
    )


# --------------------------------------------------------------------------- EOD

def eod_summary(
    day: Optional[date] = None, client: Optional[OllamaClient] = None
) -> str:
    day = day or date.today()
    client = client or OllamaClient()
    with connect() as conn:
        rows = events_for_day(conn, day)
    if not rows:
        return f"No activity logged for {day.isoformat()}."

    prompt = (
        f"Here is a chronological log of what I did on {day.isoformat()}, based on "
        "periodic screenshots described by a local vision model. Write a friendly, "
        "readable 'here's what you did today' summary: a short narrative paragraph, "
        "then a bulleted list of the main threads of work/activity with rough time "
        "spent, then one line of gentle observation. Keep it under 250 words.\n\n"
        "Reply with the summary text only. Do not show any reasoning, planning, or "
        "step-by-step working.\n\n"
        f"{_rows_to_text(rows)}"
    )
    return client.generate(TEXT_MODEL, prompt, num_predict=1400, temperature=0.4).strip()


# ------------------------------------------------------------------------ search

_SEARCH_SYSTEM = (
    "You translate a natural-language question about a screen-activity log into a "
    "single SQLite SELECT query.\n"
    "Schema: events(id INTEGER, ts TEXT, app TEXT, activity_summary TEXT, category TEXT).\n"
    "ts is an ISO-8601 local-time STRING like '2026-09-10T17:58:40' (NOT a unix "
    "timestamp). Compare dates with date(ts) and SQLite modifiers, e.g.:\n"
    "  today:      WHERE date(ts) = date('now','localtime')\n"
    "  yesterday:  WHERE date(ts) = date('now','localtime','-1 day')\n"
    "  a time win: WHERE ts BETWEEN ? AND ?   (params as ISO strings)\n"
    'Respond ONLY with JSON: {"sql": "...", "params": [...]}. Use ? placeholders '
    "for literal values. Only a SELECT is allowed."
)


def search_history(question: str, client: Optional[OllamaClient] = None) -> str:
    client = client or OllamaClient()
    now = datetime.now()

    raw = client.generate(
        TEXT_MODEL,
        f"Current local time: {now.isoformat(timespec='seconds')}\nQuestion: {question}",
        system=_SEARCH_SYSTEM,
        json_format=True,
        num_predict=250,
    )
    raw = raw[raw.find("{") : raw.rfind("}") + 1]
    plan = json.loads(raw)
    sql, params = plan["sql"], tuple(plan.get("params", []))

    with connect() as conn:
        rows = run_query(conn, sql, params)

    if not rows:
        return f"(query: {sql})\nNo matching activity found."

    return client.generate(
        TEXT_MODEL,
        "You are answering a question about someone's screen-activity log.\n\n"
        f"Question: {question}\n\n"
        "These log rows matched the question:\n"
        + _rows_to_text(rows)
        + "\n\nWrite a short, natural reply (1-3 sentences) that answers the question "
        "using these rows. Write in prose, not a list, and do not repeat the raw "
        "field names.",
        num_predict=400,
        temperature=0.5,
    ).strip()


# --------------------------------------------------------------------- breakdown

def breakdown(days: int = 1, group_by: str = "category") -> str:
    if group_by not in ("category", "app"):
        raise ValueError("group_by must be 'category' or 'app'")
    since = (datetime.now() - timedelta(days=days)).isoformat()
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {group_by} AS k, COUNT(*) AS n FROM events "
            "WHERE ts >= ? GROUP BY k ORDER BY n DESC",
            (since,),
        ).fetchall()
    if not rows:
        return f"No activity in the last {days} day(s)."

    counts = Counter({r["k"]: r["n"] for r in rows})
    total = sum(counts.values())
    peak = max(counts.values())
    width = 32
    lines = [f"Screen-time breakdown by {group_by} — last {days} day(s)", ""]
    for k, n in counts.most_common():
        bar = "█" * max(1, round(width * n / peak))
        mins = n * MINUTES_PER_EVENT
        lines.append(f"{k[:18]:<18} {bar:<{width}} {mins:6.1f} min  ({n/total:.0%})")
    lines += ["", f"~{total * MINUTES_PER_EVENT:.0f} min across {total} analyzed events"]
    return "\n".join(lines)
