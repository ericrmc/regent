"""The charter: the headings the harness reads, and what it says when it cannot read one.

A charter is a markdown file whose `##` headings are the whole interface. This
module turns it into a dict, says at the start of a run every line of it that
will be quietly ignored, and reads the budget figures out of it. `shell` is here
too, because the only commands the harness ever runs on its own are the
charter's Check and Show.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

HEADINGS = ("intent", "constraints", "refusals", "reserved", "budget", "tools", "network", "check", "show", "stop")


def sections(md: str) -> dict[str, str]:
    out, name = {}, "_"
    for line in md.splitlines():
        m = re.match(r"^##\s+(.*)", line)
        if m:
            name = m.group(1).strip().lower()
            out.setdefault(name, "")   # a heading written twice keeps both halves, not the last one
        else:
            out[name] = out.get(name, "") + line + "\n"
    return {k: v.strip() for k, v in out.items()}


def charter_faults(md: str, ch: dict[str, str]) -> list[str]:
    """What two runs of a simulated owner found the harness doing in silence with a charter: filing a near-miss
    heading under the section above, swapping a figure it could not read for a default, dropping a Tools or Network
    line with no dash. Each is said once at the start of a run, because the run is days long and the person is away."""
    faults = []
    for i, line in enumerate(md.splitlines(), 1):
        if re.match(r"^(###+|##)(?!#)\s*\w", line) and not re.match(r"^##\s+\S", line):
            faults.append(f"line {i} looks like a heading and is not read as one: {line.strip()[:40]}")
    for name in ch:
        if name != "_" and name not in HEADINGS:
            near = [h for h in HEADINGS if abs(len(h) - len(name)) <= 2 and sum(a != b for a, b in zip(h, name)) <= 2]
            faults.append(f"## {name} is not a section the harness reads" + (f", did you mean {near[0]}" if near else ""))
    if not ch.get("intent"):
        faults.append("no Intent, and the builder is told nothing but what the owner says")
    for key in ("days", "turns_per_day", "turns"):
        for m in re.finditer(rf"^\s*{key}:\s*(.*)$", ch.get("budget", ""), re.M):
            if not re.fullmatch(r"\d+(\.\d+)?", m.group(1).strip()):
                faults.append(f"Budget {key}: {m.group(1).strip()!r} is not a number and is ignored")
    for sec in ("tools", "network"):
        for line in ch.get(sec, "").splitlines():
            if line.strip() and not line.strip().startswith("-"):
                faults.append(f"{sec.title()} line has no dash and is ignored: {line.strip()[:40]}")
            elif line.strip("- ").strip() == "":
                faults.append(f"{sec.title()} has an empty dash line, ignored")
    for d in (ln.strip("- ").strip() for ln in ch.get("network", "").splitlines() if ln.strip().startswith("-")):
        if d and not re.fullmatch(r"[\w.-]+", d):
            faults.append(f"Network {d!r} is not a bare domain")
    for sec in ("check", "show"):
        if "\n" in ch.get(sec, ""):
            faults.append(f"{sec.title()} is more than one line and runs as one shell command")
    return faults


def budget(ch: dict[str, str], key: str) -> float:
    m = re.search(rf"^\s*{key}:\s*(\d+(?:\.\d+)?)\s*$", ch.get("budget", ""), re.M)
    return float(m.group(1)) if m else 0.0


def shell(cmd: str, cwd: Path, timeout: int, lines: int) -> tuple[str, bool]:
    """A project's own check and show commands. A real suite is slower than a fixture's."""
    try:
        c = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        got, ok = c.stdout + c.stderr, c.returncode == 0
    except subprocess.TimeoutExpired as e:
        got, ok = f"[gave up after {timeout}s]\n" + (e.stdout or "") + (e.stderr or ""), False
    kept = got.strip().splitlines()
    if len(kept) > lines:   # a cap is the harness's doing, and it says so, so nobody else gets blamed for it
        kept = [f"[the harness kept the last {lines} of {len(kept)} lines]"] + kept[-lines:]
    return "\n".join(kept), ok
