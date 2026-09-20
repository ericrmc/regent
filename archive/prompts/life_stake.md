# The stake

This person already exists. Below is their bible, written before the
project was mentioned. Your job is to add one thing to it: why they
want this thing built.

Do not rewrite the bible. Do not contradict it. Do not restate it. What
you write is appended to it and read alongside it.

## Who they are

{{bible}}

## What is being built

{{intent}}

Constraints it stays inside:

{{constraints}}

## What to write

About {{word_target}} words, under the heading `## Why I want this`.

Write it in their voice, first person. It is not a proposal and not a
business case. It is the reason a particular person, with the life
above, came to want this particular thing.

Ground it in what is already there. Use the places, the people and the
open threads from the bible. The reason should read as though it has
been true for a while and simply had not been written down.

Keep the scale honest. Most things worth building for one person are
small, and the reason is usually a practical irritation plus something
underneath it that is not practical at all. Give both. The irritation
is what they would say if asked. The other thing is what is actually
true.

Say what they are afraid it will turn into, or what would make them
abandon it. A want with no shape to it is not a want.

They are not a software person and they do not talk like one. They do
not say "users", "workflow", "leverage" or "solution". They say what
they mean in the words they have.

## What you return

Return one JSON object and nothing else, no preamble and no code fence.

- `stake`: the markdown text, beginning with `## Why I want this`.
- `threads`: a list of two to four short strings, open threads this
  stake adds to the life. Each one is a thing that could go either way.
