# Drift

Produce {{target_links}} cross-domain links between elements that do
not obviously belong together.

## Material

Motifs from this cycle:

{{motifs}}

A subset of the manifold. Each element carries an id. The subset is
drawn at random and is not the whole manifold.

{{manifold_subset}}

Life fragments. These are generated ordinary days, tagged synthetic.

{{life_fragments}}

The life this agent has, a bible and a run of days:

{{life}}

The life is fuel. It is not evidence and it settles nothing. It is where
a bridge comes from that the project could not have supplied on its own,
because everything in the project has already been filed next to
everything else in it.

The problem attached to this pass:

{{problem}}

When that reads exactly `none`, no problem is attached. Drift freely
over the material and do not invent a problem to aim at.

Stance for this pass:

{{stance}}

Disposition: {{stance_word}}

That is one word with a number. A risk-weighted stance leans toward
links that harden what already exists: what fails, what has no limit,
what is not yet trusted, what happens twice. An opportunity-weighted
stance leans toward links that reach: what this could also be, which two
parts are really one thing, who else this serves. Both kinds are wanted
in every pass. The stance tilts the mix and does not choose a side.

## What a link is

Two elements put together that nobody would file together, plus the
thing that transfers between them.

Label each one:

- `metaphor`: one thing described in the terms of the other.
- `causal analogy`: a cause in one domain that would act the same way
  in the other.
- `structural analogy`: the same arrangement of parts in both.
- `seed`: an unformed start, worth writing down before it is anything.

## The rules

**Every link names at least one project element by its manifold id.**
This is not optional. A link with no manifold id is discarded, so the
work of producing it is lost.

**A life fragment is fuel and counts as a second anchor, never as the
only one.** The result this pass depends on comes from the task staying
loaded while the gating loosens. A link built only from life fragments
has let go of the task, and it is worth nothing. Anchor in the project,
then reach.

**The ids say which is which.** A life element's id begins with the
letter L. A project element's id begins with the letter m. Every link
anchors to at least one id beginning with m. A life id is a second
anchor and never the only one. The harness discards a link whose anchors
are all L ids, so that link costs you the work and returns nothing. This
is a mechanical rule and not a preference.

**Pretraining is an analogy reservoir and you are invited to use it.**
Reach into any domain: queueing theory, metallurgy, epidemiology,
shipping, ecology, typesetting, anything. Mark every ingredient
`manifold` when it came from the material above, `outside` when it came
from what you already know.

**Mechanism over imagery.** This is the standing bias. A link that
imports backpressure and priority queues into a scheduling problem is
worth 50 links observing that two things both grow. State the
transferable mechanism in one line. Where a link carries no mechanism
and is only an image, leave `mechanism` as the empty string and keep
the link anyway, but expect it to score low.

## How the pass ends

Emit links in order, one after another. Keep going until you have
{{target_links}}, or until you have nothing left that is grounded in an
element id.

Two things end the pass:

- Repeating a pair of elements you have already linked.
- Producing links with no anchor.

Stop at either. A short pass of grounded links beats a long pass that
drifted off the material.

## What you return

Return one JSON object and nothing else. No prose outside it, no code
fence.

- `links`: a list, in the order produced. Each item has:
  - `kind`, one of metaphor, causal analogy, structural analogy, seed.
  - `text`, the link itself.
  - `anchors`, a list of manifold ids. At least one.
  - `ingredients`, a list of objects, each with `source` (manifold or
    outside) and `ref` naming the element id or the outside domain.
  - `mechanism`, one line naming what transfers, or the empty string
    when the link is imagery.
