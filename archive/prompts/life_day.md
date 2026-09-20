# Life day

Write this person's journal. The days have already been rolled. You
write the entries.

It is a journal and not a novel. What a later reader needs from it is
events, objects, people and unfinished business, and a journal carries
more of those per word than finished prose does. Write the way someone
writes for themselves at the end of a day: short, concrete, unfinished,
no scene setting, no paragraph that exists to get to the next one.

## Who this is

{{bible}}

## The last day or two

{{recent_days}}

What happened yesterday is still true today. A thing that broke is still
broken. A person who was angry is still angry unless this day changes
it. Continue from here.

## The day

Date: {{date}}

{{day_plan}}

That object was rolled before you were called: the events of the day,
the weather, a place, an object, a person from the cast, and a mood
seed. Use what it gives you. Do not write a different day. The gaps
between those facts are yours to fill with whatever you like.

## Threads this day touches

{{threads_today}}

When that is empty, this day touches none of them. That is a normal
day and most days are.

## Foreign text

{{foreign_text}}

When that reads exactly `none`, ignore it. Otherwise something in this
day involves reading, overhearing or being told that material. Fold it
in as it was met, in the room where it was met. Do not explain it, do
not summarise it, do not have the person work out what it means.

## The signals

{{signals}}

Four numbers from the work: frustration, curiosity, satisfaction,
unease. They colour this day's texture and its tiredness, the way work
colours a person's evening. The day is not about the work. A high
frustration day is a day where small things go wrong and the person is
short with someone. A high satisfaction day is a day where they are
generous and eat well. Never name the numbers in the prose and never
name the work they came from.

## How to write it

About {{word_target}} words, as lived prose.

Sensory detail. The actual objects, what things smelled like, what they
sounded like, what a surface felt like under a hand. What people said,
in their own words, with their own grammar.

Unfinished thoughts. Things noticed and not resolved. An irritation that
goes nowhere. A question asked and not answered. A phone call that gets
cut off and is not made again.

This is mostly not about the project and never mentions it. No software,
no agents, no code, no builds, no tests, no computers at work.

Do not summarise the day. Do not end with what it meant. A reflection on
the day gives a later reader nothing to hold, and material to hold is
the whole point of writing it. Stop mid-thought rather than closing
neatly.

## The project

{{project_material}}

When that reads exactly `none`, this is a day with no project in it.
Do not mention the thing they are building, and do not mention
software, code, builds or tests at all.

Otherwise it is a day the project is in, the way work is in anyone's
diary. What is above is everything they actually saw of it: the reports
as they read them, and what they found the times they went and looked
themselves. Each carries an id.

Write about it as themselves. Opinionated, partial, unfair if that is
how they feel. They may be pleased, irritated, suspicious, or bored by
it. They may be wrong about it, and if their memory of it is thinner
than the record they should sound like someone remembering, not someone
reading a file.

Hard limits on that passage:

- It is at most {{project_share}} of the day. The rest of the day is
  the rest of their life and is the larger part. A journal that turns
  into a work log has stopped being a life.
- They write only about what is above. Nothing else about the project
  exists to them today. Do not invent a detail, a file, a number or a
  conversation that is not there.
- They never quote code and never name a file path. They did not see
  any. They saw a report and their own look at the thing.
- They do not write it as a status update. No lists, no headings, no
  summary of where things stand.
- Do not cite the ids in the prose. Write it as a person writes a
  diary.

## What you return

Return one JSON object and nothing else. No prose outside it, no code
fence.

- `entry`: the day's prose, about {{word_target}} words.
- `valence`: a number from minus one to one. Minus one is a bad day, one
  is a good day.
- `keywords`: 4 to 8 concrete nouns taken from the entry.
- `thread_notes`: a list of short strings. Any open thread this day
  moved, closed or opened, stated in a few words, for the next day to
  carry forward. It may be empty.
