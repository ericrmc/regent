"""Every tuned number in the design lives here, with the design's value as its default.

Nothing outside this module hardcodes a threshold. A config file passed to
`harness run --config` overrides any field by name, including nested dataclasses.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any


@dataclass
class Models:
    """Role to model alias. These aliases are what `claude --model` accepts."""

    wake: str = "opus"
    react: str = "opus"
    audit: str = "opus"
    saturate: str = "sonnet"
    consolidate: str = "sonnet"
    sift: str = "sonnet"
    salience: str = "haiku"
    day_fragment: str = "haiku"
    orchestrator: str = "opus"
    builder: str = "sonnet"
    spot_check: str = "opus"
    stepping_back: str = "opus"
    # Never the judge's model, so the two do not share a blind spot.
    reader: str = "haiku"
    reader_unsure: str = "sonnet"
    # Long prose with continuity. A second vendor here gives a voice that is not
    # the judge's, through runners.by_role.
    life_writer: str = "sonnet"
    # Condensing is the smallest model. It keeps facts, it does not invent.
    life_condense: str = "haiku"
    disposition: str = "haiku"
    # Drift runs several passes on mixed sizes. A smaller model makes jumps a
    # larger one would not, and wrong is cheap because Sift exists.
    drift: list[str] = field(default_factory=lambda: ["opus", "sonnet", "haiku"])


@dataclass
class Runners:
    """Which runner serves which role.

    `claude` is ClaudeCliRunner. Any other name must be a key in `commands`,
    which CommandRunner uses. Sift on a second vendor's model is the cheapest
    decorrelation available, so it is the role most likely to move.
    """

    default: str = "claude"
    by_role: dict[str, str] = field(default_factory=dict)
    commands: dict[str, dict] = field(default_factory=dict)


@dataclass
class Spend:
    """Per-call ceilings passed as --max-budget-usd. The run budget is the charter's."""

    wake: float = 2.0
    react: float = 1.0
    audit: float = 1.0
    saturate: float = 0.5
    drift: float = 0.5
    sift: float = 0.5
    consolidate: float = 0.5
    salience: float = 0.1
    day_fragment: float = 0.1
    orchestrator: float = 10.0
    spot_check: float = 2.0
    stepping_back: float = 3.0
    reader: float = 0.3
    life_bible: float = 3.0
    life_day: float = 1.0


@dataclass
class Drift:
    # Twenty links a pass. The real passes stopped at 35, 18 and 14 on motif
    # lock, so asking for 60 bought nothing.
    target_links_min: int = 15
    target_links_max: int = 20
    passes: int = 1
    # Catch, three stop rules, whichever fires first.
    max_links: int = 60
    max_tokens: int = 4000
    motif_lock_repeats: int = 3
    # A pair counts as repeated only when the mechanism repeats too. Eight
    # motifs make few pairs, and the lock fired on all three real passes.
    motif_lock_needs_mechanism: bool = True
    groundedness_floor: int = 3
    # Each pass reads a different random subset of the warm manifold.
    subset_fraction: float = 0.6
    subset_min: int = 8
    # Stance scales the budget. At full opportunity the target rises by this factor.
    stance_budget_span: float = 0.4
    # Curiosity raises the drift budget.
    curiosity_budget_span: float = 0.3


@dataclass
class Sift:
    keep: int = 5
    # Of the kept candidates, this many places are held for requirements. A
    # batch that invents nothing does not get to fill them with solutions: the
    # second real run kept 19 candidates and every one was a solution.
    places_for_requirements: int = 2
    # Numbers for every link in one short answer, then the write-up for the
    # best few only.
    two_step: bool = True
    write_up_best: int = 10
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "novelty": 0.25,
            "mechanism": 0.35,
            "leverage": 0.25,
            "cost": 0.15,
        }
    )
    # Stance shifts the weights by at most this much, in absolute terms.
    stance_weight_span: float = 0.15


@dataclass
class Manifold:
    # An element goes cold by decay, 20 cycles uncited.
    decay_cycles: int = 20
    warm_cap: int = 400
    # The forgetting pass drops warm elements probabilistically, by age and citation.
    forget_base_probability: float = 0.15
    forget_age_weight: float = 0.05
    forget_citation_shield: float = 0.4
    # Refusals and the ledger never decay.
    protected_textures: list[str] = field(default_factory=lambda: ["refusal"])
    textures: list[str] = field(
        default_factory=lambda: [
            "friction",
            "verbatim",
            "sensory",
            "refusal",
            "unfinished",
            "foreign",
            "life",
        ]
    )


@dataclass
class Attention:
    # Unread debt is consecutive returns on a branch with no full read. At three
    # the next one is full.
    debt_cap: int = 3
    # One in five glances and waves-through gets a full read later.
    audit_rate: float = 0.2
    trust_start: float = 0.5
    trust_gain: float = 0.05
    trust_loss_minor: float = 0.1
    # Where an audit finds something the flags should have carried, trust drops hard.
    trust_loss_buried: float = 0.35
    trust_floor_full_reads: float = 0.3
    # Score bands. A higher score buys more attention.
    band_full: float = 0.72
    band_skim: float = 0.42
    band_glance: float = 0.18
    # What each input is worth in the score.
    weight_queue_depth: float = -0.07
    weight_trust: float = -0.30
    weight_unease: float = 0.35
    weight_risk_stance: float = 0.25
    weight_debt: float = 0.12
    weight_noise: float = 0.15
    # The day's time, and the owner's own disposition.
    weight_sitting: float = 0.45
    weight_thorough: float = 0.30
    weight_trusting_disposition: float = 0.20
    base_score: float = 0.55
    # The skim keeps the first N sentences of each detail body.
    skim_detail_sentences: int = 1
    skim_keep_numbers: bool = True
    salience_max_lines: int = 60


@dataclass
class Signals:
    frustration_per_failure: float = 0.25
    curiosity_per_question: float = 0.12
    satisfaction_per_accept: float = 0.3
    unease_per_thin_evidence: float = 0.3
    # An interlude decays them, so a bad run colours the next judgement without owning it.
    interlude_decay: float = 0.25
    unease_blocks_dispatch_at: float = 0.8
    # Frustration has somewhere to go. Above this it advances the rung without
    # waiting for another reject.
    frustration_advances_rung_at: float = 0.75
    # Satisfaction closes the subgoal and releases its allocation.
    satisfaction_releases_at: float = 0.6
    # Rung per repeated failure, and the cap that kills a subgoal.
    ladder_rungs: int = 6
    kill_after_idle_cycles: int = 5


@dataclass
class Stance:
    """One scalar. -1 is risk-weighted, +1 is opportunity-weighted."""

    start: float = 0.0
    max_step_per_turn: float = 0.15
    baseline_step_per_day: float = 0.06
    temperament_step_per_week: float = 0.03
    bounds: tuple[float, float] = (-1.0, 1.0)
    tilt_friction: float = -0.12
    tilt_unfinished_foreign: float = 0.10
    tilt_drift_accepted: float = 0.12
    tilt_drift_died_grounded: float = -0.15
    tilt_unease_thin_evidence: float = -0.18
    interlude_drift_amplitude: float = 0.2


@dataclass
class Interlude:
    """The harness makes the draw, not the model."""

    weights: dict[str, float] = field(
        default_factory=lambda: {
            "day": 0.0,
            "foreign_reading": 0.12,
            "replay": 0.15,
            "forgetting_pass": 0.10,
            "dream": 0.08,
            "stance_drift": 0.18,
            "nothing": 0.15,
        }
    )
    every_n_turns: int = 1
    day_word_count: int = 6
    foreign_sources: list[str] = field(default_factory=list)


@dataclass
class Life:
    """Saturation needs volume. A trickle of fragments loads nothing."""

    enabled: bool = True
    bible_words: int = 1200
    # Thirty days written before the first turn, about 45,000 words, so the
    # first drift works in a full field.
    backstory_days: int = 30
    # A journal and not a novel. What loads the field is events, objects,
    # people and unfinished business per word.
    day_words_min: int = 120
    day_words_max: int = 300
    # One day in ten runs long, the way a person sometimes writes a page.
    long_day_in: int = 10
    long_day_words: int = 800
    # A week to a call, so thirty days is five calls.
    days_per_call: int = 7
    # Saturate and Drift get the bible and the most recent 80,000 words, whole.
    drift_window_words: int = 80_000
    # 80,000 words is roughly 104,000 tokens, which fits a 200k context beside
    # the manifold. A model with a smaller window is sized here rather than by
    # shrinking the default for everyone.
    window_by_model: dict[str, int] = field(default_factory=dict)
    # Wake and judgement get the last two days and the current mood.
    judgement_days: int = 2
    start_date: str = "2019-03-04"
    # The bible says why this person wants the charter's thing built.
    stake_words: int = 400
    # The project is in the diary the way work is in anyone's. Most days it is
    # absent. The harness rolls its presence and weights it up after a bad
    # return.
    project_day_weight: float = 0.18
    project_day_weight_after_bad_return: float = 0.45
    # A journal that turns into a work log has stopped being a life.
    project_share_cap: float = 0.25
    # The day's valence moves the stance baseline. A bad night makes a
    # risk-weighted morning.
    valence_baseline_step: float = 0.05
    bootstrap_concurrency: int = 4
    # An owner is written once and reused across projects, so a run starts at
    # turn 1 rather than after seventy minutes of backstory.
    owners_dir: str = "owners"
    owner: str = ""
    # A sitting is a turn. A day passes between sittings by default.
    day_between_sittings: bool = True


@dataclass
class SpotCheck:
    """An owner who only ever reads reports is managed by whoever writes them."""

    enabled: bool = True
    # One return in six, drawn by the harness.
    rate: float = 1.0 / 6.0
    unease_triggers_at: float = 0.6
    trust_triggers_below: float = 0.35
    max_per_turn: int = 2
    max_per_run: int = 0  # 0 means no ceiling beyond the budget.
    tools: list[str] = field(default_factory=lambda: ["Read", "Grep", "Glob"])
    # A gap drops trust hard. This is distinct from an audit, which re-reads the
    # stored return rather than the project.
    trust_gain_on_match: float = 0.08
    trust_loss_on_gap: float = 0.35
    findings_word_cap: int = 400
    # A spot check is also a saturation event.
    # A spot check is a saturation event, but it no longer starts a cycle.
    # The cycle runs on its schedule and nothing else.
    opens_drift: bool = False
    queries_per_turn: int = 2
    # An owner who never questions an assumption is being managed by whoever
    # wrote it. Zero challenges across a digest period is a fault.
    challenge_zero_over_turns: int = 10
    # Trusting owner: never looking for itself is a fault the digest names.
    floor_one_in: int = 6


@dataclass
class Requirements:
    """Invention is the purpose of the mood, the life and the dreaming."""

    # The share of the budget invented requirements may take, rework included.
    default_appetite: float = 0.50
    max_per_cycle: int = 3
    # Timid owner: zero invented across a digest period is a fault, not restraint.
    timid_if_zero_over_turns: int = 10
    # Churn: a reversal of an earlier direction must cite a trigger the first
    # decision lacked.
    churn_window: int = 20
    rework_tier: str = "medium"


@dataclass
class WaysConfig:
    """Standing practices. A way changes how the owner works, never what the
    owner is permitted.
    """

    enabled: bool = True
    # The file holds seven at most, so an eighth has to displace one.
    cap: int = 7
    review_in_turns: int = 10
    # Before each digest, and on the triggers below.
    rung_trigger: int = 4
    trust_collapse_at: float = 0.25
    min_turns_between: int = 3
    max_per_run: int = 0


@dataclass
class InfluenceConfig:
    """The human steers without ordering. None of this is required."""

    enabled: bool = True
    # A plant waits for the next day to be written, and the harness brings a
    # day forward where none is due within three turns.
    force_day_within_turns: int = 3
    # Turns after entering with nothing traced before it is called faded.
    fade_after_turns: int = 8
    # A mood lean moves the stance baseline by this much per day it covers.
    mood_baseline_step: float = 0.06


@dataclass
class Readers:
    """Whether text means a thing is read, never matched by words."""

    enabled: bool = True
    escalate_unsure: bool = True
    # A disposition is read three times and shown as a median with its spread.
    disposition_samples: int = 3
    # Where a refusal can be held by permissions, it is.
    propose_tool_denials: bool = True
    deniable_tools: list[str] = field(default_factory=lambda: [
        "WebFetch", "WebSearch", "Bash", "Write", "Edit", "NotebookEdit",
        "Task",
    ])
    # Confirmed by the human once, with the charter. Until then the proposal
    # is recorded and nothing is denied.
    confirmed_denials: list[str] = field(default_factory=list)
    denials_confirmed: bool = False


@dataclass
class Tiers:
    """Tier by reversibility and blast radius, never by how important it feels."""

    names: list[str] = field(default_factory=lambda: ["low", "medium", "high"])
    # Many medium decisions compounding into a high one is a runaway, so the
    # cumulative effect is tiered, not the single act.
    medium_runaway_window: int = 10
    medium_runaway_count: int = 6


@dataclass
class Amendments:
    """A ledger that only ever relaxes is a detector firing, not a record."""

    max_per_objective: int = 6
    min_raise_to_relax_ratio: float = 0.34
    ratio_check_after: int = 6


@dataclass
class Pace:
    """The wall clock is the constraint the design sets, so every call the
    builders wait on is a cost that has to earn itself.
    """

    # React merges into the sitting. Both read the same view and both wrote
    # notes, and the builders waited on two calls to get one set of them.
    one_call_per_sitting: bool = True
    # A sitting reads the plan, this turn's views, the last two days, the ways
    # and the last few turns of the ledger. Everything older is on disk.
    wake_ledger_turns: int = 5
    wake_life_days: int = 2
    # The first sitting has nothing in flight, so it fans out rather than
    # starting one thing and waiting on it.
    fan_out_first_sitting: int = 4
    # Work with few criteria does not need a layer between the decision and the
    # file. The orchestrator is the builder.
    skip_layer_max_criteria: int = 6
    # A spot check runs beside the next dispatch, never in front of it.
    spot_checks_beside_work: bool = True
    # How long a finished run waits on a cycle still in flight. The old wait
    # was the model call timeout, so a run could end fifteen minutes after its
    # last piece of work.
    cycle_join_s: int = 60
    # Curiosity brings a cycle forward. It does not bring one every turn.
    cycle_soonest_turns: int = 5


@dataclass
class Dispatching:
    max_concurrent: int = 4
    # Permission mode for headless orchestrator calls. Never default to skipping
    # permissions.
    permission_mode: str = "acceptEdits"
    orchestrator_timeout_s: int = 3600
    model_call_timeout_s: int = 900
    # With work in flight and nothing else to decide, the harness waits on the
    # child rather than spending a Wake call on an unchanged context.
    wait_for_return_s: int = 3600
    # Every child runs with --strict-mcp-config and empty setting sources. A
    # user-scoped MCP server started with --project-from-cwd would otherwise
    # attach to any child whose cwd is inside a repo. Set this true only for a
    # project whose own settings the orchestrator is meant to read.
    allow_project_settings: bool = False
    builders: dict[str, dict] = field(
        default_factory=lambda: {
            "builder": {
                "description": "Implements one piece of the dispatch, writes tests, and returns evidence a reader can open.",
                "prompt": (
                    "You implement one piece of work and return evidence. "
                    "You do not decide scope and you do not amend an acceptance criterion. "
                    "A criterion that looks wrong is reported to the orchestrator, not reinterpreted. "
                    "Evidence is what a user of the system would meet: the running artefact, its real output, "
                    "test results with counts, timings. Your account of your own work is narration, not evidence."
                ),
            }
        }
    )


@dataclass
class Cli:
    """Flags that hold the design's rules by mechanism.

    `--tools ""` alone is not enough. A measured call with only that flag still
    loaded the user's MCP servers, one of which could edit files. The three
    flags together return a call with no tools at all.
    """

    toolless_flags: list[str] = field(
        default_factory=lambda: [
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--disable-slash-commands",
        ]
    )
    # --bare needs API-key auth. This machine may be on OAuth, so it is opt-in.
    use_bare: bool = False
    executable: str = "claude"
    fallback_model: str = ""


@dataclass
class Digest:
    every_n_turns: int = 10
    ledger_lines_in_wake: int = 30


@dataclass
class Config:
    models: Models = field(default_factory=Models)
    runners: Runners = field(default_factory=Runners)
    spend: Spend = field(default_factory=Spend)
    drift: Drift = field(default_factory=Drift)
    sift: Sift = field(default_factory=Sift)
    manifold: Manifold = field(default_factory=Manifold)
    attention: Attention = field(default_factory=Attention)
    signals: Signals = field(default_factory=Signals)
    stance: Stance = field(default_factory=Stance)
    interlude: Interlude = field(default_factory=Interlude)
    life: Life = field(default_factory=Life)
    ways: WaysConfig = field(default_factory=WaysConfig)
    readers: Readers = field(default_factory=Readers)
    influence: InfluenceConfig = field(default_factory=InfluenceConfig)
    spot_check: SpotCheck = field(default_factory=SpotCheck)
    requirements: Requirements = field(default_factory=Requirements)
    tiers: Tiers = field(default_factory=Tiers)
    amendments: Amendments = field(default_factory=Amendments)
    dispatching: Dispatching = field(default_factory=Dispatching)
    pace: Pace = field(default_factory=Pace)
    cli: Cli = field(default_factory=Cli)
    digest: Digest = field(default_factory=Digest)
    notifier: str = "osascript"
    max_turns: int = 0  # 0 means run until a stop condition fires.
    # A Wake call that returns nothing usable decides nothing, so a run of them
    # is a loop that spends the budget and moves no work. It stops the run.
    max_failed_turns: int = 3
    # A turn that dispatches nothing, judges nothing and reads nothing changed
    # no state. A run of them is the top of the tree spinning, so it stops.
    max_idle_turns: int = 10
    # A low-tier dispatch starts the moment it is decided and the reader
    # checks it while it runs. A breach kills it.
    launch_first: bool = True
    # The spoon cycle runs on a schedule, not only when Wake is blocked.
    cycle_every_n_turns: int = 15
    # A cycle starts when dispatches go down and runs beside them. Judgement
    # never waits on a cycle, and one cycle runs at a time.
    cycle_in_background: bool = True

    @classmethod
    def load(cls, path: str | Path | None = None, profile: str = "") -> Config:
        cfg = cls()
        if profile:
            _merge(cfg, PROFILES[profile])
        if path:
            data = json.loads(Path(path).read_text())
            if "profile" in data:
                _merge(cfg, PROFILES[data.pop("profile")])
            _merge(cfg, data)
        return cfg

    def to_dict(self) -> dict:
        return asdict(self)


def _merge(target: Any, data: dict) -> None:
    known = {f.name: f for f in fields(target)}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"unknown config key: {key}")
        current = getattr(target, key)
        if is_dataclass(current) and isinstance(value, dict):
            _merge(current, value)
        else:
            setattr(target, key, value)


# A run-level profile is a named set of overrides applied before any config
# file. `cheap` holds the run to two model sizes.
PROFILES: dict[str, dict] = {
    "standard": {},
    "cheap": {
        "models": {
            "wake": "sonnet",
            "react": "sonnet",
            "audit": "sonnet",
            "spot_check": "sonnet",
            "stepping_back": "sonnet",
            "reader": "haiku",
            "reader_unsure": "haiku",
            "orchestrator": "sonnet",
            "builder": "sonnet",
            "life_writer": "sonnet",
            "life_condense": "haiku",
            "disposition": "haiku",
            "saturate": "haiku",
            "consolidate": "haiku",
            "sift": "haiku",
            "salience": "haiku",
            "day_fragment": "haiku",
            "drift": ["haiku"],
        }
    },
}
