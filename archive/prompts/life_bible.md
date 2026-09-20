# Life bible

Invent a person and write the document a later writer will use to write
their days.

## The facts you are given

These were rolled before you were called. They are a JSON object: a
name, an age, a city, an occupation, family and household, long-standing
relationships with names, a recent upheaval, recurring places, and open
threads.

{{seed_facts}}

Use every fact given. Invent freely around them. Contradict none of
them. Where a fact is thin, fill it in with specifics of your own. Where
a fact is odd, keep it odd and build around it rather than smoothing it
out.

## What this person does

This person's work is not software. It is not this project. Whatever
occupation the facts name is what they do, and it has its own tools,
hours, smells and irritations. The project that runs alongside this life
is not part of the life and never appears in it. Do not mention
software, agents, code, builds, tests or a project of any kind.

## What the bible contains

Write about {{word_target}} words, under these markdown headings.

**Who this is.** The person, their household, how their days are
shaped, what they are good at and what they avoid. Facts a later writer
can act on: what time they get up, what they eat, what they drive or
ride, what they owe money on.

**The cast.** Named people, one line each. The line says the
relationship and what is unresolved in it. A cast member with nothing
unresolved gives a later day nothing to use.

**Places.** Three or four places described concretely enough to return
to. Street names, what the floor is like, the noise, who is usually
there, what it costs, which door sticks. A later writer must be able to
set a scene in one of these without inventing the room.

**History.** A short one. How they got to this city, this job, this
household. The recent upheaval and what it broke.

**Open threads.** A list of the things that are unfinished. Each one is
a situation a later day can pick up: a message not answered, a payment
overdue, a diagnosis waiting, a job half applied for, a person not
spoken to since March.

## How to write it

Concrete over abstract. Named things, particular streets, specific
objects, brands, prices, times of day. A later day needs material to
use, so give it material.

Do not summarise what kind of person this is. A character assessment is
the one thing a later writer cannot use. Write what they own, what they
say, where they go and who is angry with them, and the kind of person
comes out of that.

## What you return

Return one JSON object and nothing else. No prose outside it, no code
fence.

- `bible`: the markdown text, about {{word_target}} words, with the
  headings above.
- `threads`: a list of 3 to 6 short strings. Each one states a single
  open thread in a few words, matching the open threads in the bible.
