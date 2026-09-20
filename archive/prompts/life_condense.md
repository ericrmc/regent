# Condense to journal form

These entries were written as finished prose. Rewrite each one as a
journal entry.

A journal is not a novel. What a later reader needs from it is events,
objects, people and unfinished business. Finished prose spends most of
its words on the sentences between those things.

## The entries

{{entries}}

That is a list, one object per day, in order, each with its date and
its text.

## What to keep

Everything that happened, everything that was there, everyone who
appeared, and everything left unresolved. Every named person. Every
object with a detail attached to it, and the detail. Every place. Every
number. Every thing said, in the words it was said in. Every thing
noticed and not settled.

Where the original says a cupboard door hangs off the top hinge because
the bottom one has pulled out of the chipboard, the entry keeps the
hinge, the chipboard and the fact that it is still not fixed.

## What to drop

The connective tissue. Scene setting, transitions, restatements, and
any sentence whose only job is to carry the reader from one thing to
the next. Reflection that adds no new fact.

## How to write it

Short, concrete, unfinished. The way someone writes for themselves at
the end of a day and stops when they run out rather than when the
paragraph closes. Present the day's things plainly. Do not summarise
the day and do not say what it meant.

At most {{word_target}} words each.

That is a ceiling and not a target. Count them. An entry
over it is too long and the fix is to cut sentences, never to
cut things. Drop the connective tissue first, then any sentence
that restates the one before it. Keep every event, object,
person, number and unfinished thing. Keep the first person and the voice.

## What you return

Return one JSON object and nothing else, no preamble and no code fence.

- `entries`: one per entry above, in the same order and the same
  number. Each has `entry`, the condensed text, and `kept`, a list of
  three to eight concrete things from the original that the entry still
  carries.
