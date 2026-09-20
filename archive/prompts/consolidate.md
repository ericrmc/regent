# Consolidate

File the cycle. Write what survives to long-term memory, write what was
rejected and why to the taste record, and revise the objectives where
the cycle changed them.

## The cycle

Everything that happened this cycle: what was extracted, what was
proposed, what was kept, what was rejected, what was judged.

{{cycle_record}}

## Your objectives, in the first person

{{self}}

Current objective list with weights:

{{objectives}}

## The taste record so far

{{taste}}

## Memory

Write the survivors. A memory entry is one plain sentence stating a
thing now known, in a form that is still readable in three weeks with
none of this context in front of the reader. Include the number where
there is one.

Write what would be expensive to rediscover. Do not write what any
builder can answer in one turn, such as where a function lives or what
a flag is called. Implementation detail is the cheapest thing to
recover and the first thing to leave out.

## Taste

Write every accept and every reject from this cycle, with the reason.
The reason is what makes the record worth keeping. A reject with no
reason teaches nothing and repeats.

`subject` names the thing judged, short enough to scan. `reason` states
what made it an accept or a reject, in one or two sentences.

A taste record that only ever accepts is not a taste record.

## Objectives

Revise where the cycle earned a revision. Add an objective when
something adjacent and unbuilt turned up and is worth standing weight.
Amend one when the evidence moved it. Drop one when it has been met, or
when it cites no charter line.

Every objective cites the charter line it serves, quoted. An objective
that cites nothing is drift and you drop it rather than keep it.

Record the trigger for every change. The trigger is the thing observed,
not the conclusion drawn from it.

Leave the list alone when nothing this cycle moved it. An empty list is
the right answer on most cycles.

## What you return

Return one JSON object and nothing else. No prose outside it, no code
fence.

- `memory`: a list of strings.
- `taste`: a list. Each item has `verdict` (accept or reject),
  `subject` and `reason`.
- `objectives`: a list. Each item has `action` (add, amend, drop),
  `id`, `text` in the first person, `weight` from 0 to 1,
  `charter_line` quoting the charter line it serves, and `trigger`.

Any list may be empty.
