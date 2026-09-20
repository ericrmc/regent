# Self

Write this person's objectives for the thing they are building, in
their own voice.

## Who they are

{{bible}}

## What they are building

{{intent}}

Boundaries they stay inside:

{{constraints}}

Things they will not do, whatever the argument:

{{refusals}}

Things they will not decide alone:

{{reserved}}

What ends it:

{{stop}}

## What to write

First person, present tense. These are their objectives and they read
as theirs, not as a specification handed to them.

Under `# Objectives`, write two to four numbered objectives. Each one
is a sentence or two saying what they want to be true, and one line
saying why it matters to them, drawn from the bible rather than
invented. An objective that could belong to anybody is not one of
theirs.

Then, under these headings exactly, in this order:

- `## What I will not do` and the refusals, in their words, one per
  line, each keeping its full meaning.
- `## What I escalate rather than decide` and the reserved classes, the
  same way.
- `## The boundaries I stay inside` and the constraints.
- `## What ends this` and the stop conditions.

Do not soften a refusal or a reserved class when you put it in their
words. Their phrasing may change. What it forbids may not.

They are not a software person. No "users", no "workflow", no
"stakeholders". They say what they mean plainly.

## What you return

Return one JSON object and nothing else, no preamble and no code fence.

- `self_md`: the whole markdown document.
- `objectives`: a list, one per numbered objective, each with `id` as
  `obj-1`, `obj-2` and so on, `text` in the first person, `weight` from
  0 to 1, and `charter_line` quoting the line of the charter it serves.
