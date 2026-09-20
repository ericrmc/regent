"""Every model call in the run goes through one interface.

ClaudeCliRunner shells out to `claude -p`. CommandRunner calls any other CLI, so
Sift can run on a second vendor's model. FakeRunner replays scripted responses,
which is how the whole test suite runs without spending anything.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelRequest:
    role: str
    prompt: str
    model: str = ""
    system: str = ""
    schema: dict | None = None
    toolless: bool = True
    # Isolation is not tied to having no tools. A spot check has three tools and
    # still must not see the user's MCP servers or their settings.
    isolate: bool = True
    allow_settings: bool = False
    persist_session: bool = False
    cwd: str | None = None
    session_id: str | None = None
    resume: bool = False
    tools: list[str] = field(default_factory=list)
    add_dirs: list[str] = field(default_factory=list)
    plugin_dirs: list[str] = field(default_factory=list)
    agents: dict | None = None
    permission_mode: str = ""
    max_budget_usd: float = 0.0
    stream_log: str | None = None
    timeout_s: int = 900
    extra_args: list[str] = field(default_factory=list)


@dataclass
class ModelResponse:
    role: str
    text: str = ""
    structured: dict | None = None
    session_id: str | None = None
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    is_error: bool = False
    error: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class Runner:
    name = "runner"

    def run(self, req: ModelRequest) -> ModelResponse:
        raise NotImplementedError


class ClaudeCliRunner(Runner):
    name = "claude"

    def __init__(self, executable: str = "claude", toolless_flags: Iterable[str] | None = None,
                 use_bare: bool = False, fallback_model: str = "") -> None:
        self.executable = executable
        self.toolless_flags = list(toolless_flags or ["--tools", "", "--strict-mcp-config",
                                                     "--setting-sources", "",
                                                     "--disable-slash-commands"])
        self.use_bare = use_bare
        self.fallback_model = fallback_model

    def argv(self, req: ModelRequest) -> list[str]:
        argv = [self.executable, "-p", "--output-format", "json"]
        if req.model:
            argv += ["--model", req.model]
        if self.fallback_model:
            argv += ["--fallback-model", self.fallback_model]
        if self.use_bare:
            argv.append("--bare")
        if req.schema is not None:
            argv += ["--json-schema", json.dumps(req.schema)]
        if req.system:
            argv += ["--system-prompt", req.system]

        # Every harness-owned child gets these unless a role opts out by name.
        # `--tools ""` alone was measured to leave the user's MCP servers
        # attached, and one of those can edit files.
        if req.isolate:
            argv.append("--strict-mcp-config")
            argv.append("--disable-slash-commands")
            if not req.allow_settings:
                argv += ["--setting-sources", ""]
        if not req.persist_session:
            argv.append("--no-session-persistence")

        if req.toolless:
            argv += ["--tools", ""]
        elif req.tools:
            argv += ["--tools", ",".join(req.tools)]

        if not req.toolless:
            if req.permission_mode:
                argv += ["--permission-mode", req.permission_mode]
            for d in req.add_dirs:
                argv += ["--add-dir", d]
            for d in req.plugin_dirs:
                argv += ["--plugin-dir", d]
            if req.agents:
                argv += ["--agents", json.dumps(req.agents)]
        if req.resume and req.session_id:
            argv += ["--resume", req.session_id]
        elif req.session_id and req.persist_session:
            argv += ["--session-id", req.session_id]
        if req.max_budget_usd:
            argv += ["--max-budget-usd", str(req.max_budget_usd)]
        argv += list(req.extra_args)
        return argv

    def run(self, req: ModelRequest) -> ModelResponse:
        argv = self.argv(req)
        env = dict(os.environ)
        env["CLAUDE_CODE_ENTRYPOINT"] = "regent-harness"
        try:
            proc = subprocess.run(
                argv,
                input=req.prompt,
                capture_output=True,
                text=True,
                cwd=req.cwd,
                env=env,
                timeout=req.timeout_s,
            )
        except subprocess.TimeoutExpired:
            return ModelResponse(role=req.role, is_error=True,
                                 error=f"timed out after {req.timeout_s}s")
        if req.stream_log:
            Path(req.stream_log).parent.mkdir(parents=True, exist_ok=True)
            with open(req.stream_log, "a") as fh:
                fh.write(f"$ {shlex.join(argv)}\n")
                fh.write(proc.stdout)
                if proc.stderr:
                    fh.write("\n[stderr]\n" + proc.stderr)
                fh.write("\n")
        return parse_claude_json(req.role, proc.stdout, proc.stderr, proc.returncode)


def parse_claude_json(role: str, stdout: str, stderr: str, returncode: int) -> ModelResponse:
    text = stdout.strip()
    if not text:
        return ModelResponse(role=role, is_error=True,
                             error=stderr.strip() or f"no output, exit {returncode}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Some failures print a plain message. Keep it rather than losing it.
        return ModelResponse(role=role, text=text, is_error=returncode != 0,
                             error=stderr.strip() if returncode != 0 else "")
    usage = data.get("usage") or {}
    return ModelResponse(
        role=role,
        text=data.get("result") or "",
        structured=data.get("structured_output"),
        session_id=data.get("session_id"),
        cost_usd=float(data.get("total_cost_usd") or 0.0),
        input_tokens=int(usage.get("input_tokens") or 0)
        + int(usage.get("cache_creation_input_tokens") or 0)
        + int(usage.get("cache_read_input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
        cache_write_tokens=int(usage.get("cache_creation_input_tokens") or 0),
        is_error=bool(data.get("is_error")) or returncode != 0,
        error=str(data.get("api_error_status") or "") if data.get("is_error") else "",
        raw=data,
    )


class CommandRunner(Runner):
    """Any other CLI.

    `template` is an argv list. `{model}` and `{prompt}` are substituted. The
    prompt goes on stdin unless `{prompt}` appears in the template. `output` is
    `text`, or `json` with `result_path` and `structured_path` as dotted paths
    into the returned object.
    """

    name = "command"

    def __init__(self, template: list[str], output: str = "text",
                 result_path: str = "", structured_path: str = "",
                 cost_path: str = "", env: dict | None = None) -> None:
        self.template = template
        self.output = output
        self.result_path = result_path
        self.structured_path = structured_path
        self.cost_path = cost_path
        self.env = env or {}

    def run(self, req: ModelRequest) -> ModelResponse:
        prompt = req.prompt
        if req.system:
            prompt = req.system + "\n\n" + prompt
        argv = []
        on_stdin = True
        for part in self.template:
            if "{prompt}" in part:
                on_stdin = False
                part = part.replace("{prompt}", prompt)
            part = part.replace("{model}", req.model or "")
            part = part.replace("{role}", req.role)
            argv.append(part)
        env = dict(os.environ)
        env.update(self.env)
        try:
            proc = subprocess.run(
                argv,
                input=prompt if on_stdin else None,
                capture_output=True,
                text=True,
                cwd=req.cwd,
                env=env,
                timeout=req.timeout_s,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return ModelResponse(role=req.role, is_error=True, error=str(exc))
        out = proc.stdout.strip()
        if self.output != "json":
            return ModelResponse(role=req.role, text=out, is_error=proc.returncode != 0,
                                 error=proc.stderr.strip() if proc.returncode else "")
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return ModelResponse(role=req.role, text=out, is_error=True,
                                 error="output was not JSON")
        structured = _dig(data, self.structured_path) if self.structured_path else None
        result = _dig(data, self.result_path) if self.result_path else out
        if structured is None and isinstance(result, str):
            structured = _loose_json(result)
        return ModelResponse(
            role=req.role,
            text=result if isinstance(result, str) else json.dumps(result),
            structured=structured if isinstance(structured, dict) else None,
            cost_usd=float(_dig(data, self.cost_path) or 0.0) if self.cost_path else 0.0,
            is_error=proc.returncode != 0,
            raw=data,
        )


def _dig(data, path: str):
    cur = data
    for part in path.split("."):
        if not part:
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _loose_json(text: str) -> dict | None:
    """Pull one JSON object out of text that may carry a fence or prose around it."""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class FakeRunner(Runner):
    """Scripted responses. No process is started and nothing is spent.

    Responses are registered per role as a list consumed in order, or as a
    callable taking the request. When a role runs out of scripted responses the
    last one repeats, so a test only scripts what it cares about.
    """

    name = "fake"

    def __init__(self, scripts: dict[str, list] | None = None,
                 default: Callable[[ModelRequest], ModelResponse] | None = None) -> None:
        self.scripts: dict[str, list] = {k: list(v) for k, v in (scripts or {}).items()}
        self.default = default
        self.calls: list[ModelRequest] = []
        self.sessions: dict[str, str] = {}

    def script(self, role: str, *responses) -> FakeRunner:
        self.scripts.setdefault(role, []).extend(responses)
        return self

    def run(self, req: ModelRequest) -> ModelResponse:
        self.calls.append(req)
        queue = self.scripts.get(req.role)
        item = None
        if queue:
            item = queue.pop(0) if len(queue) > 1 else queue[0]
        if item is None:
            if self.default:
                return self.default(req)
            return ModelResponse(role=req.role, is_error=True,
                                 error=f"FakeRunner has no script for role {req.role}")
        if callable(item):
            item = item(req)
        if isinstance(item, ModelResponse):
            resp = item
        elif isinstance(item, dict):
            resp = ModelResponse(role=req.role, structured=item,
                                 text=json.dumps(item), cost_usd=0.0)
        else:
            resp = ModelResponse(role=req.role, text=str(item), cost_usd=0.0)
        if resp.session_id is None:
            resp.session_id = req.session_id or str(uuid.uuid4())
        return resp

    def calls_for(self, role: str) -> list[ModelRequest]:
        return [c for c in self.calls if c.role == role]


def build_runners(cfg) -> dict[str, Runner]:
    """One runner per name in the config. Roles map onto these by name."""
    runners: dict[str, Runner] = {
        "claude": ClaudeCliRunner(
            executable=cfg.cli.executable,
            toolless_flags=cfg.cli.toolless_flags,
            use_bare=cfg.cli.use_bare,
            fallback_model=cfg.cli.fallback_model,
        )
    }
    for name, spec in (cfg.runners.commands or {}).items():
        runners[name] = CommandRunner(
            template=spec["template"],
            output=spec.get("output", "text"),
            result_path=spec.get("result_path", ""),
            structured_path=spec.get("structured_path", ""),
            cost_path=spec.get("cost_path", ""),
            env=spec.get("env", {}),
        )
    return runners
