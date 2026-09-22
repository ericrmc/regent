"""The watch page: one HTML file, served live off the ledger or written out whole.

`snapshot` is everything the page draws, read out of the run's sqlite with a
read-only handle so a running run is never disturbed. `watch.html` is package
data beside this file and is read on every request, so an edit to the page shows
on a refresh.
"""
from __future__ import annotations

import http.server
import json
import re
import sqlite3
import threading
import time
import webbrowser
from pathlib import Path

from regent import HOME, PACKAGE
from regent.charter import shell
from regent.life import owner_dir

PAGE = PACKAGE / "watch.html"


def latest_run(where: str | None) -> Path:
    """A run folder, a project folder or name, or nothing at all, which means the newest run."""
    if where and (Path(where).expanduser() / "run.db").exists():
        return Path(where).expanduser()
    found = sorted((HOME / "runs").glob(f"{Path(where).name if where else ''}*/run.db"), key=lambda f: f.stat().st_mtime)
    if not found:
        raise SystemExit(f"no run found for {where or 'anything'} in {HOME / 'runs'}")
    return found[-1].parent


def snapshot(root: Path) -> dict:
    """Everything the page draws: the ledger, the state, the days he lived through, and the builder's commits."""
    c = sqlite3.connect(f"file:{root / 'run.db'}?mode=ro", uri=True)
    events = [{"id": i, "t": t, "kind": k, "d": json.loads(d)} for i, t, k, d in c.execute("SELECT id, t, kind, data FROM event")]
    state = json.loads((c.execute("SELECT v FROM state WHERE k='run'").fetchone() or ["{}"])[0])
    c.close()
    start = next((e["d"] for e in events if e["kind"] == "start"), {})
    days, memory, commits = {}, "", []
    try:
        owner = owner_dir(start.get("owner", ""))
        lc = sqlite3.connect(f"file:{owner / 'life.db'}?mode=ro", uri=True)
        ns = [e["d"]["n"] for e in events if e["kind"] == "day"]
        days = dict(lc.execute(f"SELECT n, text FROM day WHERE n IN ({','.join('?' * len(ns))})", ns))
        memory = (lc.execute("SELECT text FROM memory WHERE project=?", (start.get("project", ""),)).fetchone() or [""])[0]
        lc.close()
    except (SystemExit, sqlite3.Error):
        pass
    project = Path(start.get("project", ""))
    log = shell("git log --reverse --format=@%ct%x09%s --shortstat", project, 20, 4000)[0] if (project / ".git").exists() else ""
    for line in log.splitlines():
        if line.startswith("@"):
            when, _, subject = line[1:].partition("\t")
            commits.append({"t": int(when), "subject": subject, "plus": 0, "minus": 0})
        elif commits and "changed" in line:
            commits[-1]["plus"] = int((re.search(r"(\d+) insertion", line) or [0, 0])[1])
            commits[-1]["minus"] = int((re.search(r"(\d+) deletion", line) or [0, 0])[1])
    fresh = max((f.stat().st_mtime for f in root.glob("run.db*")), default=0)
    return {"run": root.name, "events": events, "state": state, "days": days, "memory": memory, "commits": commits,
            "quiet_for": round(time.time() - fresh)}


def watch_cmd(a, root: Path | None = None, background: bool = False):
    """One page, two uses: served live from the ledger, or written out whole with the run inside it."""
    root = root or latest_run(a.run)
    source = PAGE
    page = source.read_text()
    if getattr(a, "export", None):
        data = json.dumps(snapshot(root), ensure_ascii=False).replace("</", "<\\/")
        page = page.replace("<title>Regent Daybook", f"<title>{root.name.rsplit('-', 2)[0]} daybook")
        Path(a.export).write_text(page.replace('type="application/json">null<', f'type="application/json">{data}<'))
        print(f"written to {a.export}")
        return 0

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            live = self.path.startswith("/data")
            body = (json.dumps(snapshot(root)) if live else
                    '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                    + source.read_text()).encode()   # read each time, so an edit to the page shows on refresh
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if live else "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"watching {root.name} at http://127.0.0.1:{server.server_address[1]}", flush=True)
    webbrowser.open(f"http://127.0.0.1:{server.server_address[1]}")
    if background:
        return threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
