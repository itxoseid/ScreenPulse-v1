"""
A small local dashboard: one page, served from localhost, reading straight
from the SQLite log. No frameworks, no build step, no external requests from
the page itself — it only talks back to this same local server.

Reading the terminal output works, but a live feed, a real bar chart, and a
search box you can type into is easier to actually use day to day.
"""

from __future__ import annotations

import json
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import PID_PATH
from .db import connect, recent_events
from .reports import breakdown_data, eod_summary, export_log, search_history

_CATEGORY_COLOR = {
    "coding": "#7ed697",
    "communication": "#7ac8dc",
    "browsing": "#82aaeb",
    "reading": "#c896d2",
    "writing": "#dec878",
    "design": "#c88cd6",
    "media": "#96b4eb",
    "meeting": "#eb8282",
    "gaming": "#96e6a1",
    "system": "#969aaa",
    "idle": "#5a5c68",
    "other": "#d0d2de",
}


def _pid_running() -> bool:
    if not PID_PATH.exists():
        return False
    try:
        pid = int(PID_PATH.read_text().strip())
    except ValueError:
        return False
    from .cli import _pid_alive  # local import: avoid a cycle at module load

    return _pid_alive(pid)


class _Handler(BaseHTTPRequestHandler):
    server_version = "ScreenPulseDashboard/1.0"

    def log_message(self, fmt, *args):  # noqa: A003 - silence default request logging
        pass

    def _json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    # --------------------------------------------------------------- routes

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        url = urlparse(self.path)
        q = parse_qs(url.query)

        if url.path == "/":
            self._html(_PAGE)
            return

        if url.path == "/api/status":
            self._json({"watching": _pid_running()})
            return

        if url.path == "/api/events":
            limit = int(q.get("limit", ["50"])[0])
            with connect() as conn:
                rows = [dict(r) for r in recent_events(conn, limit)]
            self._json(rows)
            return

        if url.path == "/api/breakdown":
            days = int(q.get("days", ["1"])[0])
            by = q.get("by", ["category"])[0]
            try:
                data = breakdown_data(days=days, group_by=by)
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            for d in data:
                d["color"] = _CATEGORY_COLOR.get(d["key"], "#8888a0") if by == "category" else "#7ac8dc"
            self._json(data)
            return

        if url.path == "/api/export":
            fmt = q.get("format", ["csv"])[0]
            days = q.get("days", [None])[0]
            text = export_log(fmt=fmt, days=int(days) if days else None)
            self.send_response(200)
            ctype = "application/json" if fmt == "json" else "text/csv"
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header(
                "Content-Disposition", f'attachment; filename="screenpulse.{fmt}"'
            )
            body = text.encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)

        if url.path == "/api/summary":
            body = self._read_json()
            day = date.fromisoformat(body["date"]) if body.get("date") else date.today()
            try:
                text = eod_summary(day)
            except Exception as exc:  # noqa: BLE001 - surface to the UI, don't crash
                self._json({"error": str(exc)}, 502)
                return
            self._json({"text": text})
            return

        if url.path == "/api/search":
            body = self._read_json()
            question = (body.get("question") or "").strip()
            if not question:
                self._json({"error": "empty question"}, 400)
                return
            try:
                answer = search_history(question)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, 502)
                return
            sql, _, text = answer.partition("\n\n")
            self._json({"sql": sql.removeprefix("query: "), "answer": text or answer})
            return

        self.send_response(404)
        self.end_headers()


_PAGE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>ScreenPulse</title>
<style>
  :root {
    --bg: #17171f; --panel: #1e1e29; --border: #2c2c3a; --fg: #d2d4de;
    --dim: #8a8ca0; --accent: #7ed697; --amber: #e6be5a; --red: #e65a5a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font: 14px/1.5 "Cascadia Code", "Consolas", monospace;
  }
  header {
    display: flex; align-items: center; gap: 10px;
    padding: 14px 20px; border-bottom: 1px solid var(--border);
  }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; letter-spacing: .02em; }
  #dot { width: 9px; height: 9px; border-radius: 50%; background: var(--dim); }
  #dot.on { background: var(--accent); box-shadow: 0 0 6px var(--accent); }
  #statusText { color: var(--dim); font-size: 12px; }
  main {
    display: grid; grid-template-columns: 1.3fr 1fr; gap: 18px;
    padding: 18px 20px; max-width: 1200px; margin: 0 auto;
  }
  @media (max-width: 860px) { main { grid-template-columns: 1fr; } }
  .panel {
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px; margin-bottom: 18px;
  }
  .panel h2 {
    margin: 0 0 12px; font-size: 12px; text-transform: uppercase;
    letter-spacing: .08em; color: var(--dim); font-weight: 600;
  }
  #feed { max-height: 520px; overflow-y: auto; }
  .ev { padding: 8px 0; border-bottom: 1px solid var(--border); }
  .ev:last-child { border-bottom: none; }
  .ev .top { display: flex; gap: 8px; align-items: baseline; }
  .ev .time { color: var(--dim); font-size: 12px; }
  .tag {
    font-size: 11px; padding: 1px 7px; border-radius: 999px; font-weight: 600;
  }
  .ev .app { font-weight: 600; }
  .ev .summary { color: var(--dim); margin-top: 2px; font-size: 13px; }
  .bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
  .bar-row .label { width: 100px; flex-shrink: 0; font-size: 12px; }
  .bar-track { flex: 1; background: var(--border); border-radius: 6px; height: 16px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 6px; }
  .bar-row .val { width: 90px; flex-shrink: 0; text-align: right; font-size: 12px; color: var(--dim); }
  select, input[type=text], button {
    background: var(--bg); color: var(--fg); border: 1px solid var(--border);
    border-radius: 6px; padding: 7px 10px; font: inherit;
  }
  button { cursor: pointer; }
  button:hover { border-color: var(--accent); }
  .row { display: flex; gap: 8px; margin-bottom: 12px; }
  .row input[type=text] { flex: 1; }
  #searchAnswer, #summaryText { white-space: pre-wrap; font-size: 13px; margin-top: 10px; }
  .sql { color: var(--dim); font-size: 12px; margin-top: 8px; }
  .muted { color: var(--dim); font-size: 12px; }
  .toggle { display: flex; gap: 6px; margin-bottom: 12px; }
  .toggle button.active { border-color: var(--accent); color: var(--accent); }
</style>
</head>
<body>
<header>
  <span id="dot"></span>
  <h1>ScreenPulse</h1>
  <span id="statusText">checking…</span>
  <span style="flex:1"></span>
  <a class="muted" href="/api/export?format=csv" style="color:var(--dim)">export csv</a>
</header>

<main>
  <div>
    <div class="panel">
      <h2>Live feed</h2>
      <div id="feed">Loading…</div>
    </div>
  </div>

  <div>
    <div class="panel">
      <h2>Breakdown</h2>
      <div class="toggle">
        <button data-days="1" class="active">Today</button>
        <button data-days="7">7 days</button>
        <button data-by="app">By app</button>
        <button data-by="category" class="active">By category</button>
      </div>
      <div id="bars">Loading…</div>
    </div>

    <div class="panel">
      <h2>Ask about your day</h2>
      <div class="row">
        <input id="q" type="text" placeholder='e.g. "what was I doing this morning"'>
        <button id="askBtn">Ask</button>
      </div>
      <div id="searchAnswer"></div>
    </div>

    <div class="panel">
      <h2>Daily summary</h2>
      <button id="summaryBtn">Generate today's summary</button>
      <div id="summaryText"></div>
    </div>
  </div>
</main>

<script>
const CAT_COLOR = {
  coding: "#7ed697", communication: "#7ac8dc", browsing: "#82aaeb",
  reading: "#c896d2", writing: "#dec878", design: "#c88cd6",
  media: "#96b4eb", meeting: "#eb8282", gaming: "#96e6a1",
  system: "#969aaa", idle: "#5a5c68", other: "#d0d2de",
};
const CAT_FALLBACK = "#8888a0";
let state = { days: 1, by: "category" };

async function refreshStatus() {
  try {
    const r = await fetch("/api/status");
    const d = await r.json();
    document.getElementById("dot").classList.toggle("on", d.watching);
    document.getElementById("statusText").textContent = d.watching ? "watching" : "not watching";
  } catch (e) {
    document.getElementById("statusText").textContent = "server unreachable";
  }
}

function timeOf(ts) { return ts.split("T")[1]?.slice(0,8) ?? ts; }

async function refreshFeed() {
  const r = await fetch("/api/events?limit=40");
  const rows = await r.json();
  const feed = document.getElementById("feed");
  if (!rows.length) { feed.innerHTML = '<p class="muted">Nothing logged yet.</p>'; return; }
  feed.innerHTML = rows.map(e => {
    const c = CAT_COLOR[e.category] || CAT_FALLBACK;
    return `
    <div class="ev">
      <div class="top">
        <span class="time">${timeOf(e.ts)}</span>
        <span class="tag" style="background:${c}22;color:${c}">${escapeHtml(e.category)}</span>
        <span class="app">${escapeHtml(e.app)}</span>
      </div>
      <div class="summary">${escapeHtml(e.activity_summary)}</div>
    </div>
  `;
  }).join("");
}

async function refreshBars() {
  const r = await fetch(`/api/breakdown?days=${state.days}&by=${state.by}`);
  const rows = await r.json();
  const bars = document.getElementById("bars");
  if (!rows.length || rows.error) { bars.innerHTML = '<p class="muted">No activity in this range.</p>'; return; }
  const peak = Math.max(...rows.map(r => r.count));
  bars.innerHTML = rows.map(r => `
    <div class="bar-row">
      <div class="label">${escapeHtml(r.key)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(r.count/peak*100).toFixed(0)}%;background:${r.color}"></div></div>
      <div class="val">${r.minutes} min · ${(r.share*100).toFixed(0)}%</div>
    </div>
  `).join("");
}

function escapeHtml(s) {
  return (s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

document.querySelectorAll(".toggle button").forEach(btn => {
  btn.addEventListener("click", () => {
    if (btn.dataset.days) {
      document.querySelectorAll("[data-days]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.days = parseInt(btn.dataset.days);
    }
    if (btn.dataset.by) {
      document.querySelectorAll("[data-by]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.by = btn.dataset.by;
    }
    refreshBars();
  });
});

document.getElementById("askBtn").addEventListener("click", async () => {
  const q = document.getElementById("q").value.trim();
  if (!q) return;
  const out = document.getElementById("searchAnswer");
  out.textContent = "Thinking…";
  try {
    const r = await fetch("/api/search", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({question: q})
    });
    const d = await r.json();
    if (d.error) { out.textContent = "Error: " + d.error; return; }
    out.innerHTML = `<div>${escapeHtml(d.answer)}</div><div class="sql">${escapeHtml(d.sql || "")}</div>`;
  } catch (e) { out.textContent = "Request failed: " + e; }
});
document.getElementById("q").addEventListener("keydown", e => { if (e.key === "Enter") document.getElementById("askBtn").click(); });

document.getElementById("summaryBtn").addEventListener("click", async () => {
  const out = document.getElementById("summaryText");
  out.textContent = "Generating… (can take a little while on a local model)";
  try {
    const r = await fetch("/api/summary", { method: "POST", headers: {"Content-Type": "application/json"}, body: "{}" });
    const d = await r.json();
    out.textContent = d.error ? "Error: " + d.error : d.text;
  } catch (e) { out.textContent = "Request failed: " + e; }
});

refreshStatus();
refreshFeed();
refreshBars();
setInterval(refreshStatus, 5000);
setInterval(refreshFeed, 4000);
</script>
</body>
</html>
"""


def run_dashboard(port: int = 8765, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"ScreenPulse dashboard: {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
