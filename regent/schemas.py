"""The shape of every structured answer the harness asks a model for.

One schema per stage, built from two helpers so the shapes stay readable. Every
property is required: a model that may leave a field out leaves it out, and the
code that reads it then carries a branch for the absence of something it asked
for.
"""
from __future__ import annotations

STR, BOOL = {"type": "string"}, {"type": "boolean"}


def arr(x: dict) -> dict:
    return {"type": "array", "items": x}


def obj(**props) -> dict:
    return {"type": "object", "properties": props, "required": list(props)}


DECISION = obj(
    stance_line=STR, verdict={"type": "string", "enum": ["continue", "accept", "reject"]}, message=STR,
    challenged=BOOL, constrained=BOOL, wants_new=arr(obj(name=STR, want=STR, notice=STR, idea=STR)),
    requirements_built=arr(STR), ideas_declined=arr(obj(idea=STR, why=STR, not_now=BOOL)),
    ideas_answered=arr(obj(idea=STR, answer=STR)),
    constraints_changed=arr(obj(constraint=STR, now=STR, why=STR)), ask_the_human=STR,
    wants_to_look=BOOL, looked_at=arr(STR), look_matched=BOOL, notes_to_self=STR, done=BOOL)
ANSWERED_BACK = obj(said=STR, leave=BOOL)
ASKED = obj(question=STR, assumptions=arr(obj(assumption=STR, holds=BOOL, why=STR)), enough=BOOL)
TAKEN = obj(taken=STR, not_followed=arr(STR), not_reached=STR, picked_up=arr(STR))
READBACK = obj(readings=arr(obj(name=STR, spec=STR, test=STR)), questions=arr(STR))
ANSWERED = obj(said=STR, misread=arr(obj(name=STR, what=STR)))
MOTIFS = obj(motifs=arr(STR), tensions=arr(STR), questions=arr(STR))
LINKS = obj(links=arr(obj(kind={"type": "string", "enum": ["metaphor", "causal analogy", "structural analogy", "seed"]},
                          text=STR, anchors=arr(STR), other=STR, mechanism=STR)))
SIFTED = obj(candidates=arr(obj(kind={"type": "string", "enum": ["ask", "doubt", "wish", "worry"]},
                                text=STR, test=STR, from_indexes=arr({"type": "integer"}), why_it_might_fail=STR)))
FED = obj(feeds=arr(obj(notion=STR, seed=STR, stream=STR, strength={"type": "integer"}, because=STR)))
STEPBACK = obj(why_now=STR, could_become=STR, follows=STR,
               observations=arr(STR), ways=arr(STR), notes_for_the_human=arr(STR))
PICTURE = obj(picture=STR, gaps=arr(STR))
CAST = obj(name=STR, slug=STR, bible=STR, events=arr(STR), pursuits=arr(STR))
EVENTS = obj(events=arr(STR))
PURSUITS = obj(pursuits=arr(STR))
