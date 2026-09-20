"""Escalations notify, because an escalation is the one thing in the run that
waits on a person.

The notifier is pluggable. On macOS the default shells out to osascript. Any
failure falls back to a log line, so a missing notifier never stops the run.
"""

from __future__ import annotations

import shutil
import subprocess


class Notifier:
    name = "log"

    def __init__(self, store=None) -> None:
        self.store = store
        self.sent: list[tuple[str, str]] = []

    def send(self, title: str, message: str) -> bool:
        self.sent.append((title, message))
        if self.store:
            self.store.log(f"NOTIFY {title}: {message}")
        return True


class OsascriptNotifier(Notifier):
    name = "osascript"

    def send(self, title: str, message: str) -> bool:
        self.sent.append((title, message))
        if not shutil.which("osascript"):
            return super().send(title, message)
        script = (f'display notification {_q(message)} with title {_q(title)}')
        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        except Exception:
            return super().send(title, message)
        if self.store:
            self.store.log(f"NOTIFY {title}: {message}")
        return True


class CommandNotifier(Notifier):
    name = "command"

    def __init__(self, template: list[str], store=None) -> None:
        super().__init__(store)
        self.template = template

    def send(self, title: str, message: str) -> bool:
        self.sent.append((title, message))
        argv = [p.replace("{title}", title).replace("{message}", message)
                for p in self.template]
        try:
            subprocess.run(argv, capture_output=True, timeout=30)
        except Exception:
            return super().send(title, message)
        return True


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def build(cfg, store=None) -> Notifier:
    name = cfg.notifier
    if isinstance(name, list):
        return CommandNotifier(name, store)
    if name == "osascript":
        return OsascriptNotifier(store)
    return Notifier(store)
