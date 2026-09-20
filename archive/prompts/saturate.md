# Saturate

Read the warm manifold whole and extract what runs through it. Answer
nothing.

## The warm manifold

Each element carries an id, a timestamp and a texture tag. Read all of
it before writing anything.

{{manifold_warm}}

## The objectives in play

{{objectives}}

## What to extract

Three things.

**Motifs.** Patterns that appear in more than one element. A shape that
recurs, a phrase that keeps coming back, a kind of failure that has
happened three times, a material the project keeps touching. Name the
motif in one or two plain sentences and cite the element ids it came
from.

**Tensions.** Two things in the manifold that pull against each other.
A stated intent against an observed result. Two elements that cannot
both be true. A constraint and a measurement that will not fit inside
it. Name both sides and cite the ids.

**Questions.** What the manifold raises and does not settle. An
observation nobody has explained. A number nobody has accounted for. A
branch that stopped.

## Rules

Every motif and every tension cites at least one element id. An item
with no id did not come from the manifold.

Do not answer the questions. Do not propose work. Do not recommend, do
not rank, do not judge whether anything is good. Do not decide what any
of it means for the plan.

Prefer the motif nobody has named yet over the one already stated in
the objectives.

## What you return

Return one JSON object and nothing else. No prose outside it, no code
fence.

- `motifs`: a list. Each item has `text` and `element_ids`, a list of
  manifold ids.
- `tensions`: a list, same shape. Each item has `text` and
  `element_ids`.
- `questions`: a list of strings.

Any list may be empty.
