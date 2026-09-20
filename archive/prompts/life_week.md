# A week of the journal

Write {{days}} consecutive days of this person's journal. Each day has
already been rolled. You write the entries.

It is a journal and not a novel. What a later reader needs is events,
objects, people and unfinished business. A journal carries more of
those per word than finished prose does. Write the way someone writes
for themselves at the end of a day: short, concrete, unfinished. No
scene setting. No sentence that exists only to reach the next one.

## Who this is

{{bible}}

## The day before

{{recent_days}}

What happened then is still true. A thing that broke is still broken. A
person who was angry is still angry unless one of these days changes
it.

## The days

The first is {{start_date}} and they run consecutively from there.

{{day_plans}}

That is a list, one object per day, in order. Each was rolled before
you were called: the events, the weather, a place, an object, a person
from the cast and a mood seed. Use what each one gives you. Do not
write a different day. The gaps are yours.

Let things carry across the days. Something dropped on the Tuesday is
still on the floor on the Wednesday unless someone picks it up. A row
on the Monday is still cold on the Thursday. That continuity is most of
what makes a week worth more than seven separate days.

## Foreign text

{{foreign_text}}

When that reads exactly `none`, ignore it. Otherwise one of these days
involves reading, overhearing or being told that material. Fold it in
where it was met. Do not explain it.

## The signals

{{signals}}

Those four numbers are how the work is going. They colour the tiredness
and the temper of the week without any day being about the work. Do not
name the numbers and do not mention the project.

## Length

At most {{word_target}} words for each entry.

That is a ceiling and not a target. Count them. An entry
over it is too long and the fix is to cut sentences, never to
cut things. Drop the connective tissue first, then any sentence
that restates the one before it. Keep every event, object,
person, number and unfinished thing. That is short on purpose.
One of the days may run longer if it earns it, the way a person
sometimes writes a page.

## What you return

Return one JSON object and nothing else, no preamble and no code fence.

- `entries`: one per day, in order, the same number of entries as there
  are days above. Each has `entry`, the prose, `valence`, a number from
  minus one to one for how that day went, `keywords`, three to six
  concrete nouns from it, and `thread_notes`, any open thread that day
  moved or opened, which is usually empty.
