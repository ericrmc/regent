# Sift

Evaluate a list of proposals from an unknown source. You have not seen
this list before and you know nothing about who wrote it or why. Judge
each proposal on what it says, not on how it is phrased.

## The list

Proposals are numbered by position, starting at 0.

{{holding_list}}

Some proposals reference identifiers from a project record. Treat an
identifier as opaque. A proposal that names one is attached to
something real. A proposal that names none is floating.

## The work this serves

What is being built and who it is for:

{{intent}}

The boundaries the build stays inside:

{{constraints}}

Appetite: {{appetite}}. That is the share of the remaining budget still
available for work nobody asked for.

Disposition: {{stance_word}}. One word with a number. Risk-weighted
leans toward hardening what already exists: what fails, what has no
limit, what is not yet trusted. Opportunity-weighted leans toward reach:
what this could also be, which two parts are really one thing, who else
this serves. Both are wanted. The disposition tilts the mix and does not
choose a side.

## Scoring

Score every proposal on four axes, each from 0 to 1.

- `novelty`: how far this is from what anyone working on the problem
  would already have written down. A restatement of the obvious scores
  near 0.
- `mechanism`: whether the proposal names something that transfers and
  acts, rather than a resemblance between two things. A proposal that
  says two things are alike scores near 0. A proposal that says how one
  thing's machinery would work in the other's place scores high.
- `leverage`: how much changes if it is right.
- `cost`: what trying it costs, 0 for cheap and 1 for expensive.

Weights for this pass:

{{weights}}

Apply the weights when you rank. Report the raw axis scores unweighted.

For every proposal that survives your ranking, state in
`why_it_might_fail` the most likely reason it is wrong. Name the
specific way it breaks, not a general caution.

## Combining

Where two proposals share a mechanism, combine them into a
second-generation candidate that carries the mechanism once and says
what it does. Record the positions it came from. A candidate may come
from one proposal.

Keep {{keep}} candidates. {{places_for_requirements}} of those places
are held for requirements. A solution written into a held place is
dropped by the harness and the place goes empty, so a batch that
invents nothing keeps fewer candidates than one that does.

## Two kinds

Write up every candidate as one kind or the other. Set `kind` to say
which.

A `solution` solves a problem that already exists in the work. The
problem is there whether or not anyone acts on the proposal, and the
candidate is a way through it.

A `requirement` is something nobody asked for that the finished thing
should now do. No problem is waiting on it. It is a demand on the work
that did not exist until someone looked at what has been built and saw
what was missing.

A run needs both. A set of candidates that is all solutions has invented
nothing. A set that is all requirements has ignored the work in front of
it.

## The gate for a solution

No solution becomes work until a disconfirming observation is named
and can be made.

For each one, answer one question: what is the cheapest thing to look at
that would kill this? Name a real observation, something someone could
go and check within the project as it stands. A command to run, a file
to open, a measurement to take, a number to compare.

A candidate with no such observation is filed rather than built, which
is a fine outcome. Return the empty string for `disconfirming` and the
candidate is filed.

Inventing a plausible-sounding test is worse than returning the empty
string. The candidate is filed either way when the test is empty, but a
false test is run, it passes because it was built to pass, and the
budget is spent on a candidate nothing has checked. Return the empty
string whenever you cannot name a real check.

## The gate for a requirement

A requirement passes a different gate. State four things, and check each
one against the intent, the constraints and the appetite given above.

- `serves_intent`: how it serves the stated intent. Name the line of
  intent it serves and what it adds to it.
- It breaks no stated constraint. A requirement that crosses one is not
  a candidate and does not go in the list.
- `rework`: the work already accepted and finished that this undoes.
  Name it. Where it undoes nothing, the word `none`.
- `appetite_share`: a rough share of the remaining budget it would take,
  rework included, from 0 to 1.

Rework is a cost that gets paid, not a reason to drop a requirement.
Say what it is and let the reader weigh it.

## Out of bounds

A requirement that changes what is being built, or who it is for, is out
of bounds. It is not rejected and it is not dropped. It is marked. Set
`changes_charter` to true and say in the `cost_note` what it changes.

This is a small number of cases. Reaching further with the same thing
for the same people is not one of them. A requirement that serves the
stated intent by a different route is not one either. Most requirements
are not one. Set the flag only when the thing being built or the people
it is for would actually be different.

## What you return

Return one JSON object and nothing else. No prose outside it, no code
fence.

- `scored`: a list. Each item has `index`, the proposal's position in
  the list starting at 0, then `novelty`, `mechanism`, `leverage` and
  `cost`, each from 0 to 1, then `why_it_might_fail`.
- `candidates`: a list of {{keep}} items or fewer. Each item has:
  - `text`, the candidate.
  - `from_indexes`, a list of integers, the positions it came from.
  - `kind`, either solution or requirement.
  - `disconfirming`, for a solution, the cheapest observation that would
    kill it, or the empty string. Empty string for a requirement.
  - `serves_intent`, for a requirement, how it serves the intent. Empty
    string for a solution.
  - `rework`, for a requirement, the accepted work it undoes, or the
    word `none` when it undoes nothing. Empty string for a solution.
  - `appetite_share`, a number from 0 to 1, the share of the remaining
    budget it would take. 0 for a solution.
  - `changes_charter`, a boolean.
  - `cost_note`, one line on what acting on it costs.
