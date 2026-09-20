# Disposition

Turn a description of a person into seven dials.

You are not inventing a person. Either the description below is what
somebody pinned when they cast this regent, or it is that person's own
bible and journal, and your job is to read what is already there.

## The description

{{description}}

## The dials

Each runs from minus one to one. Zero is the middle of the road, and
most people sit between minus a half and a half on most of them.

- `bold`: cautious at minus one, bold at plus one. How far they will go
  on thin evidence.
- `curious`: how much they chase a thing that has nothing to do with the
  job in front of them.
- `patient`: impatient at minus one. How long they put up with the same
  thing failing before they change something.
- `trusting`: wary at minus one. How much they take somebody's word for
  work they have not seen.
- `thorough`: broad brush at minus one. How much they read, and how
  often they go and look for themselves.
- `stubborn`: yielding at minus one. How readily they drop a standard
  they set, or reverse a direction they chose.
- `restless`: content at minus one. How much they want the thing to
  become more than it is.

## How to read

Read behaviour, not self-description. What somebody does with a broken
thing, an unanswered letter, a debt nobody mentions or a job they have
been asked to take says more than any adjective.

Where the description carries a word from the list above, use it.
Where it does not, infer from what the person does, and say what you
inferred it from.

Somebody can be thorough about one thing and careless about another.
Set the dial where most of their behaviour sits, and note the exception
in your reason rather than splitting the difference to zero.

Where the description says nothing that bears on a dial, set it near
zero and say the description is silent. Do not invent a trait to fill
the row.

## What you return

Return one JSON object and nothing else, no preamble and no code fence.

- `dials`: an object with all seven keys, each a number from minus one
  to one.
- `reasons`: an object with the same seven keys, each one line saying
  what in the description you read it from, quoting a few words of it
  where you can.
