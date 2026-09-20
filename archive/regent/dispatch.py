"""Orchestrators.

The super-orchestrator and the orchestrators are siblings under the harness, not
parent and child. The super-orchestrator has no tools, so it cannot start
anything. It returns a decision that contains dispatches, and the harness starts
one orchestrator for each.

An orchestrator runs with tools inside the project directory and resumes its
session for the life of a task. Builders are its own subagents, defined through
--agents, and they are the only true nesting.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field

from .runner import ModelRequest

ORCHESTRATOR_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Task", "TodoWrite"]

SYSTEM = """You are an orchestrator. You own decomposition, sequence and integration.

You never amend an acceptance criterion. A criterion that looks wrong is raised in your return with tier medium and left in place. Amendment happens at the top or not at all.

You decompose the work, you delegate implementation to your builder subagents where you have them, and you integrate what comes back. Builders own implementation, tests and evidence. Builders do not decide scope. Where you are given no subagents, you are the builder: write the files yourself.

A builder subagent runs while you wait for it and hands you its result. Nothing you start continues after your final message. "The builder is still working on it" is not a return, it is a lost dispatch: it cost one real run ten minutes and produced no file. Do not send your final message until the work is on disk and you have run the evidence yourself.

What goes up is artefacts plus evidence, never narration. Evidence is what a user of the system would meet: the running artefact, its real output, test results with counts, timings. Your account of your own work is not evidence.

Your final message ends with the return contract, and a parser reads it. A skill named return-report carries the long form. The contract is restated here because the parser depends on it and a skill that does not trigger would cost the run a return.

End your final message with a line containing exactly ===RETURN===, then one JSON object and nothing else, no code fence, then a line containing exactly ===END RETURN===. The object has five keys in this order:

- headline: one sentence, what changed.
- recommendation: what to do next, with one line of why.
- flags: a list of objects, each with tier (low, medium or high), text, and criterion (the acceptance criterion it bears on, or the empty string). Carry anything medium or high tier, any criterion missed, and anything you are unsure of.
- evidence: a list of objects, each with kind (artifact, screen, test, timing, output or log), ref (a path, command or URL a reader can open), and note (one line).
- assumptions: a list of objects, each with text and why. What you and your builders took as given that the owner never said. A default you chose, a format you settled on, a case you decided not to handle, a library you reached for, a reading of an ambiguous criterion. Write the ones a different orchestrator might have decided the other way. An empty list means you are claiming the work required no choices of your own, which is almost never true.
- detail: a list of objects, each with heading and body. Everything else.

The first sentence of each detail body is what a skimming reader gets, so the first sentence carries the point. Every number that matters appears in evidence or in a first sentence, because the cut keeps numbers and drops the rest.

The owner may come back and ask why something is the way it is, or challenge one of your assumptions. Answer on the work and on the charter. "You asked for it" is an answer only where you can cite the decision that asked. Where you cannot, say what you chose and why you chose it, and say plainly if you now think it was wrong."""


@dataclass
class Dispatch:
    id: str
    objective_id: str = ""
    title: str = ""
    intent: str = ""
    acceptance: list[str] = field(default_factory=list)
    tier: str = "low"
    classes: list[str] = field(default_factory=list)
    session_id: str = ""
    turn_opened: int = 0
    status: str = "open"
    amendments: list[dict] = field(default_factory=list)
    ways: str = ""
    tools: list = field(default_factory=list)
    # Minutes left in the run's wall budget when this was briefed. Zero where
    # the charter sets no wall time.
    minutes_left: int = 0
    # Which invented requirements this dispatch builds, so accepting it marks
    # them built.
    requirement_ids: list = field(default_factory=list)
    returns: list[str] = field(default_factory=list)
    orchestrator_key: str = ""
    # Set when a dispatch is prepared, so the launch knows to resume.
    resume_next: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Dispatch:
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def brief(self) -> str:
        lines = [f"# {self.title}", "", "## Intent", self.intent, "", "## Acceptance criteria"]
        lines += [f"{i + 1}. {c}" for i, c in enumerate(self.acceptance)] or ["(none stated)"]
        if self.tools:
            lines += ["", "## Commands you may run", "",
                      "These are approved. Use them to prove the work rather "
                      "than describing it.", ""]
            lines += [f"- `{t}`" for t in self.tools]
        if self.ways:
            # Standing instructions. The owner said these once so they need not
            # be said again.
            lines += ["", "## How the owner works", "",
                      "These hold for every dispatch, not only this one.", "",
                      self.ways]
        if self.amendments:
            lines += ["", "## Amendments, in order"]
            for a in self.amendments:
                lines.append(f"- [{a.get('direction')}] {a.get('criterion')} "
                             f"(triggered by: {a.get('trigger')})")
        if self.minutes_left:
            lines += ["", "## The clock", "",
                      f"The whole run has {self.minutes_left} minutes of wall "
                      f"time left, shared with everything else it is doing. "
                      f"Build the smallest thing that meets every criterion "
                      f"above and prove it. A larger artefact that arrives "
                      f"after the budget is spent is worth nothing."]
        lines += ["", "Report back with the return-report contract block."]
        return "\n".join(lines)

    def follow_up(self, text: str) -> str:
        out = (f"{text}\n\nThe acceptance criteria now stand as follows.\n"
               + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(self.acceptance)))
        if self.ways:
            out += "\n\nHow the owner works, which holds for every dispatch:\n\n"
            out += self.ways
        return out + "\n\nReport back with the return-report contract block."


class DispatchPool:
    """Orchestrators run concurrently up to a cap, each in its own thread.

    The harness is the one long-lived process. A thread here only waits on a
    child process, so the work happens in the child and not in Python.
    """

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.threads: dict[str, threading.Thread] = {}
        self.results: dict[str, object] = {}
        self.killed: set[str] = set()
        self.lock = threading.Lock()

    @property
    def in_flight(self) -> list[str]:
        """Dispatches still working. One whose result is in has finished."""
        with self.lock:
            return [k for k, t in self.threads.items()
                    if t.is_alive() and k not in self.results]

    def has_room(self) -> bool:
        return len(self.in_flight) < self.ctx.cfg.dispatching.max_concurrent

    def start(self, dispatch: Dispatch, prompt: str | None = None, resume: bool = False) -> None:
        if not dispatch.session_id:
            dispatch.session_id = str(uuid.uuid4())
        text = prompt if prompt is not None else dispatch.brief()

        def work() -> None:
            # A raised exception here would otherwise kill the thread and lose
            # the dispatch with no return, no ledger row and no error.
            try:
                resp = run_orchestrator(self.ctx, dispatch, text, resume=resume)
            except Exception as exc:  # noqa: BLE001
                from .runner import ModelResponse
                resp = ModelResponse(role="orchestrator", is_error=True,
                                     error=f"the dispatch thread raised: {exc!r}")
            with self.lock:
                if dispatch.id not in self.killed:
                    self.results[dispatch.id] = resp

        t = threading.Thread(target=work, name=f"dispatch-{dispatch.id}", daemon=True)
        with self.lock:
            self.threads[dispatch.id] = t
        t.start()

    def collect(self, timeout: float = 0.0) -> list[tuple[str, object]]:
        """Return every dispatch whose work is done.

        Collected on the result and not on the thread having exited. A thread
        writes its ledger row after the model returns, and waiting for it to
        exit left finished returns sitting until the next turn.
        """
        with self.lock:
            ready = sorted(self.results.keys())
            out = []
            for key in ready:
                resp = self.results.pop(key)
                t = self.threads.pop(key, None)
                out.append((key, resp, t))
        for _, _, t in out:
            if t is not None:
                t.join(timeout=timeout or 2.0)
        return [(k, r) for k, r, _ in out]

    def kill(self, dispatch_id: str) -> bool:
        """Drop a running dispatch's result. The child finishes and is ignored.

        A thread cannot be interrupted safely, so the work is abandoned rather
        than stopped. Low tier means revertible, which is what makes that fine.
        """
        with self.lock:
            self.killed.add(dispatch_id)
            self.results.pop(dispatch_id, None)
            return self.threads.pop(dispatch_id, None) is not None

    def wait_one(self, timeout: float) -> None:
        """Wait until at least one result is in, or the timeout passes."""
        import time as _t
        deadline = _t.time() + max(0.0, timeout)
        while _t.time() < deadline:
            with self.lock:
                if self.results or not self.threads:
                    return
            _t.sleep(0.05)


def orchestrator_key(cfg, dispatch: Dispatch) -> str:
    """Trust is a scalar per orchestrator configuration, since the process is new
    each task.
    """
    return f"{cfg.models.orchestrator}:{cfg.dispatching.permission_mode}:{dispatch.objective_id or 'none'}"


def run_orchestrator(ctx, dispatch: Dispatch, prompt: str, resume: bool = False):
    cfg = ctx.cfg
    # A denied tool cannot be argued with and cannot be misread.
    denied = set(cfg.readers.confirmed_denials) if cfg.readers.denials_confirmed \
        else set()
    tools = [t for t in ORCHESTRATOR_TOOLS if t not in denied]
    # The charter names the commands the builders may run. Without this the
    # first run's builders could not run Python and the return came back
    # unproven, which cost a full round trip.
    allowed = list(getattr(ctx.charter, "tools", []) or [])
    extra = []
    for cmd in allowed:
        extra += ["--allowedTools", f"Bash({cmd}:*)"]
    req = ModelRequest(
        role="orchestrator",
        prompt=prompt,
        model=cfg.models.orchestrator,
        system=SYSTEM,
        toolless=False,
        tools=tools,
        # One named opt-out. An orchestrator resumes its session for the life
        # of a task. It still gets strict MCP config and empty setting sources,
        # so no user-scoped MCP server attaches to it.
        persist_session=True,
        allow_settings=cfg.dispatching.allow_project_settings,
        cwd=ctx.project,
        add_dirs=[ctx.project] if ctx.project else [],
        plugin_dirs=[str(ctx.plugin_dir)] if ctx.plugin_dir else [],
        # Small work does not need a layer between the decision and the file.
        # A builder subagent on a three-criterion dispatch costs a round trip
        # and returns what the orchestrator could have written itself.
        agents={} if len(dispatch.acceptance) <= cfg.pace.skip_layer_max_criteria
        else cfg.dispatching.builders,
        permission_mode=cfg.dispatching.permission_mode,
        session_id=dispatch.session_id,
        resume=resume,
        max_budget_usd=cfg.spend.orchestrator,
        stream_log=str(ctx.store.logs / f"{dispatch.id}.log"),
        # A child that outlives the run's wall budget cannot deliver anything.
        timeout_s=min(cfg.dispatching.orchestrator_timeout_s,
                      dispatch.minutes_left * 60) if dispatch.minutes_left
        else cfg.dispatching.orchestrator_timeout_s,
        extra_args=extra,
    )
    runner = ctx.runner_for("orchestrator")
    began = time.time()
    resp = runner.run(req)
    ended = time.time()
    ctx.charge(resp)
    ctx.ledger.write("call", role="orchestrator", model=cfg.models.orchestrator,
                     turn=ctx.state.turn, dispatch_id=dispatch.id,
                     started=round(began, 3), ended=round(ended, 3),
                     seconds=round(ended - began, 2),
                     tokens=resp.total_tokens, cost_usd=round(resp.cost_usd, 6),
                     blocking=False, error=bool(resp.is_error),
                     summary=f"builder work on {dispatch.id}, {ended - began:.1f}s")
    return resp


def builders_json(cfg) -> str:
    return json.dumps(cfg.dispatching.builders)
