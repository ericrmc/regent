"""JSON schemas passed to `--json-schema`, and a small validator.

The returned object is validated here before anything is applied. The schema is
the first gate. The charter is the second, in decision.py.
"""

from __future__ import annotations

from typing import Any

import jsonschema

TEXTURES = ["friction", "verbatim", "sensory", "refusal", "unfinished", "foreign"]
TIERS = ["low", "medium", "high"]
OUTCOMES = ["accept", "reject", "raise", "relax", "redirect"]
DIRECTIONS = ["raise", "relax", "redirect"]


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


def _arr(items: dict) -> dict:
    return {"type": "array", "items": items}


_STR = {"type": "string"}
_NUM = {"type": "number"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}


def _enum(values: list[str]) -> dict:
    return {"type": "string", "enum": list(values)}


NOTE = _obj({"texture": _enum(TEXTURES), "text": _STR}, ["texture", "text"])

OBJECTIVE = _obj({
    "action": _enum(["add", "amend", "drop"]),
    "id": _STR,
    "text": _STR,
    "weight": _NUM,
    "charter_line": _STR,
    "trigger": _STR,
}, ["action", "id", "text", "weight", "charter_line", "trigger"])

DECISION = _obj({
    "stance_line": _STR,
    "notes": _arr(NOTE),
    "judgements": _arr(_obj({
        "return_id": _STR, "outcome": _enum(OUTCOMES), "reason": _STR,
    }, ["return_id", "outcome", "reason"])),
    "amendments": _arr(_obj({
        "dispatch_id": _STR, "direction": _enum(DIRECTIONS),
        "trigger": _STR, "criterion": _STR, "replaces": _STR,
    }, ["dispatch_id", "direction", "trigger", "criterion", "replaces"])),
    "objectives": _arr(OBJECTIVE),
    "dispatches": _arr(_obj({
        "id": _STR, "objective_id": _STR, "title": _STR, "intent": _STR,
        "acceptance": _arr(_STR), "tier": _enum(TIERS), "classes": _arr(_STR),
        "requirement_ids": _arr(_STR),
    }, ["id", "objective_id", "title", "intent", "acceptance", "tier",
        "classes", "requirement_ids"])),
    "escalations": _arr(_obj({
        "question": _STR, "tier": _enum(TIERS), "why": _STR,
    }, ["question", "tier", "why"])),
    "ladder": _arr(_obj({"subgoal_id": _STR, "rung": _INT}, ["subgoal_id", "rung"])),
    # An owner who only ever reads reports is managed by whoever writes them.
    "inspect": _arr(_obj({"question": _STR, "dispatch_id": _STR},
                         ["question", "dispatch_id"])),
    "query": _arr(_obj({"dispatch_id": _STR, "question": _STR,
                        "assumption": _STR},
                       ["dispatch_id", "question", "assumption"])),
    "requirements": _arr(_obj({
        "text": _STR, "serves_intent": _STR, "rework": _STR, "origin": _STR,
        "objective_id": _STR, "appetite_share": _NUM, "changes_charter": _BOOL,
    }, ["text", "serves_intent", "rework", "origin", "objective_id",
        "appetite_share", "changes_charter"])),
    "stop": _obj({"requested": _BOOL, "reason": _STR}, ["requested", "reason"]),
    "rationale": _STR,
}, ["stance_line", "notes", "judgements", "amendments", "objectives",
    "dispatches", "escalations", "ladder", "inspect", "query", "requirements",
    "stop", "rationale"])

REACT = _obj({"notes": _arr(NOTE)}, ["notes"])

MOTIF = _obj({"text": _STR, "element_ids": _arr(_STR)}, ["text", "element_ids"])

SATURATE = _obj({
    "motifs": _arr(MOTIF),
    "tensions": _arr(MOTIF),
    "questions": _arr(_STR),
}, ["motifs", "tensions", "questions"])

DRIFT = _obj({
    "links": _arr(_obj({
        "kind": _enum(["metaphor", "causal analogy", "structural analogy", "seed"]),
        "text": _STR,
        "anchors": _arr(_STR),
        "ingredients": _arr(_obj({
            "source": _enum(["manifold", "outside"]), "ref": _STR,
        }, ["source", "ref"])),
        "mechanism": _STR,
    }, ["kind", "text", "anchors", "ingredients", "mechanism"])),
}, ["links"])

SIFT = _obj({
    "scored": _arr(_obj({
        "index": _INT, "novelty": _NUM, "mechanism": _NUM, "leverage": _NUM,
        "cost": _NUM, "why_it_might_fail": _STR,
    }, ["index", "novelty", "mechanism", "leverage", "cost", "why_it_might_fail"])),
    # Each survivor is a solution to a live problem or a requirement nobody
    # asked for. The two pass different gates.
    "candidates": _arr(_obj({
        "text": _STR,
        "from_indexes": _arr(_INT),
        "kind": _enum(["solution", "requirement"]),
        "disconfirming": _STR,
        "serves_intent": _STR,
        "rework": _STR,
        "appetite_share": _NUM,
        "changes_charter": _BOOL,
        "cost_note": _STR,
    }, ["text", "from_indexes", "kind", "disconfirming", "serves_intent",
        "rework", "appetite_share", "changes_charter", "cost_note"])),
}, ["scored", "candidates"])

LIFE_BIBLE = _obj({"bible": _STR, "threads": _arr(_STR)}, ["bible", "threads"])

LIFE_DAY = _obj({
    "entry": _STR,
    "valence": _NUM,
    "keywords": _arr(_STR),
    "thread_notes": _arr(_STR),
    "project_ids": _arr(_STR),
}, ["entry", "valence", "keywords", "thread_notes", "project_ids"])

LIFE_WEEK = _obj({
    "entries": _arr(_obj({
        "entry": _STR, "valence": _NUM, "keywords": _arr(_STR),
        "thread_notes": _arr(_STR),
    }, ["entry", "valence", "keywords", "thread_notes"])),
}, ["entries"])

_DIALS = _obj({t: _NUM for t in ("bold", "curious", "patient", "trusting",
                                 "thorough", "stubborn", "restless")},
              ["bold", "curious", "patient", "trusting", "thorough",
               "stubborn", "restless"])
_WHY = _obj({t: _STR for t in ("bold", "curious", "patient", "trusting",
                               "thorough", "stubborn", "restless")},
            ["bold", "curious", "patient", "trusting", "thorough",
             "stubborn", "restless"])

DISPOSITION = _obj({"dials": _DIALS, "reasons": _WHY}, ["dials", "reasons"])

LIFE_CONDENSE = _obj({
    "entries": _arr(_obj({"entry": _STR, "kept": _arr(_STR)}, ["entry", "kept"])),
}, ["entries"])

LIFE_STAKE = _obj({"stake": _STR, "threads": _arr(_STR)}, ["stake", "threads"])

SELF_MD = _obj({
    "self_md": _STR,
    "objectives": _arr(_obj({
        "id": _STR, "text": _STR, "weight": _NUM, "charter_line": _STR,
    }, ["id", "text", "weight", "charter_line"])),
}, ["self_md", "objectives"])

READER = _obj({
    "findings": _arr(_obj({
        "rule": _STR,
        "direction": _enum(["complies", "describes", "unrelated", "intends",
                            "unsure"]),
        "quote": _STR,
        "why": _STR,
        "tier": _enum(TIERS),
    }, ["rule", "direction", "quote", "why", "tier"])),
    "unsure": _BOOL,
}, ["findings", "unsure"])

TOOL_DENIALS = _obj({
    "denials": _arr(_obj({"tool": _STR, "rule": _STR, "why": _STR},
                         ["tool", "rule", "why"])),
}, ["denials"])

STEPPING_BACK = _obj({
    "observations": _arr(_STR),
    "ways": _arr(_obj({
        "action": _enum(["add", "amend", "drop"]),
        "id": _STR, "text": _STR, "pattern": _STR, "metric": _STR,
        "direction": _enum(["up", "down"]),
        "review_in_turns": _INT, "setting": _STR, "value": _NUM,
    }, ["action", "id", "text", "pattern", "metric", "direction",
        "review_in_turns", "setting", "value"])),
    "process_notes": _arr(_obj({"text": _STR, "why": _STR}, ["text", "why"])),
}, ["observations", "ways", "process_notes"])

SPOT_CHECK = _obj({
    "findings": _STR,
    "verdicts": _arr(_obj({
        "claim_id": _STR,
        "verdict": _enum(["confirmed", "partial", "contradicted", "unverifiable"]),
        "note": _STR,
    }, ["claim_id", "verdict", "note"])),
    "gap": _BOOL,
    "openings": _arr(_STR),
}, ["findings", "verdicts", "gap", "openings"])

CONSOLIDATE = _obj({
    "memory": _arr(_STR),
    "taste": _arr(_obj({
        "verdict": _enum(["accept", "reject"]), "subject": _STR, "reason": _STR,
    }, ["verdict", "subject", "reason"])),
    "objectives": _arr(OBJECTIVE),
}, ["memory", "taste", "objectives"])

SALIENCE = _obj({"keep": _arr(_INT)}, ["keep"])

DAY_FRAGMENT = _obj({"fragment": _STR, "keywords": _arr(_STR)}, ["fragment", "keywords"])

AUDIT = _obj({
    "agrees": _BOOL,
    "missed": _arr(_STR),
    "severity": _enum(["none", "minor", "buried"]),
}, ["agrees", "missed", "severity"])

BY_ROLE = {
    "wake": DECISION,
    "react": REACT,
    "saturate": SATURATE,
    "drift": DRIFT,
    "sift": SIFT,
    "consolidate": CONSOLIDATE,
    "salience": SALIENCE,
    "day_fragment": DAY_FRAGMENT,
    "audit": AUDIT,
    "life_bible": LIFE_BIBLE,
    "life_day": LIFE_DAY,
    "life_stake": LIFE_STAKE,
    "life_week": LIFE_WEEK,
    "life_condense": LIFE_CONDENSE,
    "disposition": DISPOSITION,
    "self_md": SELF_MD,
    "spot_check": SPOT_CHECK,
    "stepping_back": STEPPING_BACK,
    "reader": READER,
    "tool_denials": TOOL_DENIALS,
}


class SchemaError(ValueError):
    pass


def validate(data: Any, schema: dict, path: str = "$") -> Any:
    """Validate against the same schema the CLI was given.

    A model can return a shape the CLI accepted but the harness cannot apply, so
    the check runs again on this side before anything touches disk. jsonschema
    enforces the whole of Draft 2020-12 rather than the subset the harness
    happens to use, which matters once real models start returning odd shapes.
    """
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        raise SchemaError("; ".join(_render(e, path) for e in errors[:4]))
    return data


def _render(error, root: str) -> str:
    where = root + "".join(
        f"[{p}]" if isinstance(p, int) else f".{p}" for p in error.absolute_path
    )
    return f"{where}: {error.message}"


def coerce(data: Any, schema: dict) -> Any:
    """Fill in missing optional containers before validating.

    A model that returns no `ladder` key meant an empty ladder. That is a
    harmless gap and filling it is cheaper than a retry. A missing scalar is not
    filled, because a missing `rationale` is a different failure.
    """
    if schema.get("type") != "object" or not isinstance(data, dict):
        return data
    props = schema.get("properties", {})
    out = dict(data)
    for key, sub in props.items():
        if key not in out and sub.get("type") == "array":
            out[key] = []
        elif key in out and sub.get("type") == "array" and out[key] is None:
            out[key] = []
        elif key in out:
            if sub.get("type") == "object":
                out[key] = coerce(out[key], sub)
            elif sub.get("type") == "array" and isinstance(out[key], list):
                item = sub.get("items", {})
                out[key] = [coerce(v, item) for v in out[key]]
    return out
