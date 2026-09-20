# Regent: a design

> **Status, 2026-09-21.** This document describes the *first* architecture,
> which is now in `archive/`. Its reasoning is current and is why the project
> exists: authority sits with a simulated owner under a charter; the owner is a
> life, a lossy memory and a divergence organ; the spoon cycle (saturate, drift,
> catch, sift, consolidate) runs while he sleeps and is never him; the entropy
> of a life comes from dice and not from the model; a regent is cast, not
> specified. Read those sections as written.
>
> Its mechanism is not current. The harness is one file. Gone: the three-level
> tree of regent, orchestrator and builder; dispatches and the `===RETURN===`
> protocol; the manifold as a store with ids and textures (the project elements
> are numbered fresh each cycle from his memory and requirements); attention as
> a module with its own model call; spot checks as a separate call; risk tiers
> and the signal ladder; the interlude table; every fixed count ("every
> fifteenth turn", "three consecutive links"), each now a draw or a hazard; and
> the 224 tunables. Claude Code does the work those parts did.
>
> `README.md` and the docstring in `regent.py` describe what runs.

The change is where the authority sits, not what gets done. Intent,
judgement and ideas are the same three functions a human product owner
performs. Today a person performs them, and on projects where the risk
per decision is low, that person is the slowest part of the loop. This
design hands the three functions to an agent, bounds them by a charter
written once at the start, and keeps a short list of decisions the
human still owns.

The system is called Regent. A regent rules in the sovereign's place,
with real authority and under a charter, until the sovereign takes it
back. The regent here is the simulated owner. The harness is the
program that runs them.

Everything downstream already runs at agent speed. Orchestrators
decompose and sequence, builders write code and return evidence. The
wait is at the top, for someone to look, react, decide and re-aim. Move
that function into the loop and the turn time at the top drops from a
person's response time to an agent's. The cost is that errors compound
without a person noticing, which is what the charter, the risk tiers
and the digest exist to bound.

Every number in this document is a starting default, to be tuned
against the digest.

## The charter

The charter is what the human writes before stepping out. It is short
on purpose. A long charter recreates the bottleneck in written form,
because every clause is a decision the agent then cannot make.

| Field | Content |
| --- | --- |
| Intent | what is being built and who it is for, in plain sentences |
| Constraints | the boundaries the build stays inside |
| Refusals | what is never acceptable, whatever the argument for it |
| Reserved | the decision classes that still escalate |
| Budget | tokens, wall time, spend |
| Appetite | the share of the budget invented requirements may take, their rework included. Default 50% |
| Tools | the commands the builders may run, such as the language's interpreter and test runner. Passed to every orchestrator as allowed tools |
| Stop | what ends the run, successfully or not |

Everything not reserved belongs to the agent. That inversion is the
whole mechanism. A permission model that lists what the agent may do
produces an agent that asks. A model that lists what it may not do
produces an agent that acts.

**Risk tiers** decide what reserves. Tier by reversibility and blast
radius, never by how important the thing feels.

| Tier | Test | Authority |
| --- | --- | --- |
| Low | revertible by one commit, no external effect | decide, log |
| Medium | costly to undo, visible inside the project only | decide, log, name it in the digest |
| High | irreversible, external, spends real money, touches a person | reserved, escalate, only that branch waits |

Most decisions on most projects are low. That is the finding this
design rests on. Naming a module, choosing a queue, rejecting a
builder's approach, rewriting an acceptance criterion, dropping a
feature that is not earning its keep, all of it is revertible and none
of it needs a person.

## What makes it an owner

Three organs separate this from a planner loop:

1. **A standing self.** Objectives, refusals and taste that outlive a
   session, so it originates work rather than answering a prompt, and
   revises that work on contact with what comes back.
2. **A divergence organ.** A bounded way to invent requirements nobody
   asked for, using accumulated experience as fuel. This is what the
   mood, the life and the dreaming are for.
3. **A judgement organ.** Taste with a spine, run in a context that
   never saw the options being produced.

The divergence organ is the hard one, and the N1 hypnagogia result
gives it a mechanism and, more usefully, a shape: prime hard, loosen
the gating, catch the output before coherence goes, verify while awake.
Awake is too rigid. Deep sleep is unrecoverable. The value sits in the
narrow band between, and the band has to be closed deliberately,
because nothing closes it on its own.

**Mission ownership.** There is one self. The person in the life is the
owner of the project: they want it built, for a reason their life
supplies, and the ideas about it are theirs. The charter is transcribed
once into `self.md` in their voice, as objectives rather than as a
ticket, and every subgoal is generated from there. What is checkable is behaviour, not
conviction: the agent originates work nobody asked for, refuses work
that conflicts with its objectives, and defends the intent against
drift from its own orchestrators. An agent holding a ticket returns the
ticket completed. An agent holding a mission returns the thing that was
wanted, and says when the ticket was wrong.

The charter stays user-written. Objectives in `self.md` are the agent's
to add and amend, each with a recorded trigger, each citing the charter
line it serves. An objective that cites nothing is drift.

## The manifold

The manifold is the regent's working experience. It is
written continuously, never summarised, and read whole.

| Texture | Examples |
| --- | --- |
| Friction | failing tests, retries, a build that took 40 minutes |
| Verbatim | the user's own words, quoted, never paraphrased |
| Sensory | screenshots, latency numbers, log tails, error strings |
| Refusal | what was rejected, and the stated reason |
| Unfinished | abandoned branches, TODOs, questions never answered |
| Foreign | anything read from outside the project |
| Life | the agent's invented life, held apart in the life journal, tagged synthetic |

Every element carries an id, a timestamp and a texture tag. Ids are how
a later claim proves it came from lived material rather than from
invention.

The manifold is warm or cold. Warm is in context and read whole. An
element goes cold by decay, 20 cycles uncited, or by a forgetting pass.
Cold is out of context, not deleted. It returns by replay, or when a
return cites it.

## The spoon cycle

Six states. Temperature is the sampling knob, but the real control is
what each state may read and write.

| State | Temp | Reads | Writes | Exit |
| --- | --- | --- | --- | --- |
| Wake | 0.2 | plan, evidence, self | decisions, dispatches | queue empty or blocked |
| Saturate | 0.4 | warm manifold and the life, whole | motif list | motifs extracted |
| Drift | 1.0 | motifs, manifold, the life, pretraining | raw links | the spoon drops |
| Catch | n/a | nothing | links to holding file | file written |
| Sift | 0.2 | holding file only | ranked candidates | candidates gated |
| Consolidate | 0.4 | cycle record | self, taste, memory | manifold pruned |

Wake is the default, and the cycle is rare. It runs on a schedule of
every fifteenth turn and on nothing else. A spot check that opened
something, a blocked Wake and a hard decision do not start one. A dream
drawn in the interlude counts as the scheduled cycle and resets the
count. The first cycle waits until something has been built and
accepted, since before that there is nothing to dream about. Two real
runs fired seven cycles in fourteen turns, spent 55% of the money on
them, and got two requirements, both from the first.

The record says why the later cycles landed nothing. Sift wrote 19 of
its 25 survivors as solutions to live problems, because the cycle was
handed a problem to solve. Solving the builders' problems is the
builders' job. Of the six it did write as requirements, two landed, one
was refused for appetite under the old cap, and three vanished between
the background cycle and his next sitting with no row to say so. So the
cycle is asked a different question: what could this become, and what
is it missing for the person it is for. At least three of Sift's five
write-ups are requirements. Every candidate a cycle produces ends in a
ledger row: landed, refused with the reason, or put to him and declined.
None may disappear.

`claude -p` exposes no temperature, so in this build the column is a
target and not a setting. Implementation states how Drift reaches it.

**Saturate** extracts motifs, tensions and unresolved questions. It
answers nothing.

**Drift** asks for 40 to 60 cross-domain links between manifold
elements that do not obviously belong together, each labelled metaphor,
causal analogy, structural analogy or seed, each naming at least one
project element by id. A life fragment is fuel and counts as a second
anchor, never as the only one, because the N1 result depends on the
task staying loaded while the gating loosens. Pretraining is invited as
an analogy reservoir, and every ingredient is marked manifold or
outside. The standing bias is
mechanism over imagery. A link that imports backpressure and priority
queues into a scheduling problem is worth 50 links observing that two
things both grow.

**Catch** is the falling spoon, three stop rules, whichever fires
first:

- 60 links or 4,000 tokens.
- Motif lock: three consecutive links reusing a pair already emitted.
- Groundedness floor: three consecutive links with no project anchor.

The third is the one that matters. A link with no anchor is the model
in N2, fluent about nothing, and past that point the pass costs more to
evaluate than it returns.

**Sift** runs in a fresh context that never saw the drift happen, and
reads the holding file as an anonymous list. An evaluator that watched
itself generate a thing rates its own thing highly, and the cycle is
worth nothing if the filter is captured. Sift scores novelty,
mechanism, leverage and cost, states for each survivor why it might
fail, combines survivors into second-generation candidates, and keeps
five. Each survivor is written up as one of two things: a solution to a
live problem, or a new requirement.

**The gate.** No solution becomes work until a disconfirming
observation is named and made. What is the cheapest thing to look at
that would kill this? A candidate with no such observation is poetry
and gets filed, not built. This is the only defence against apophenia,
and the cycle is not safe to run without it. A requirement passes a
different gate, stated in Inventing requirements.

**Consolidate** writes survivors to long-term memory, writes rejections
and their reasons to the taste record, and prunes the manifold.

## The interlude

Between turns the agent does not sit frozen waiting for the next
return. It has an interlude, and the interlude is randomised. Without
it a long project collapses into one groove: the same stance, the same
motifs, the same reading of every artefact, which is what a person
avoids by going home, sleeping badly, reading something unrelated and
coming back annoyed.

Each interlude draws from a weighted table.

| Event | Effect |
| --- | --- |
| A day | passes between sittings by default, so it is no longer a draw. The date advances and a journal entry of 120 to 300 words is written |
| Foreign reading | pulls material from an unrelated domain into the manifold |
| Replay | resurfaces a cold manifold element, chosen at random |
| Forgetting pass | drops warm elements probabilistically, by age and citation count |
| Dream | an unbounded drift with no problem attached, kept only if Sift takes it |
| Stance drift | perturbs the disposition within bounds |
| Nothing | the interlude passes and the state is unchanged |

The guardrail is a hard line. An interlude perturbs what the agent
notices and how it weights, never what it is permitted to do. It cannot
touch the charter, the refusals, the reserved list, the decision ledger
or the gate. Randomness in disposition is productive. Randomness in
authority is a runaway.

The harness makes the draw, not the model. A model asked to be random
returns its favourite few answers, so the event, the seed material and
the amplitude come from a seeded generator outside it, and the seed is
logged so a run replays. Day fragments are seeded the same way, from
random draws over an external corpus, or every day is a rainy morning
with coffee.

The deeper reason for all of it is that the judge and the builders are
the same model. Given the same context they share blind spots, and the
evidence that convinced the builder convinces the judge. Texture,
forgetting and a moved stance make the judge a different reader from
the one that did the work, which a human owner is for free.

**Forgetting is a feature twice over.** It is how the context stays
affordable across a project that runs for weeks, and it is what makes
the agent re-encounter its own system as a reader rather than as its
author. A regent that remembers exactly why every
compromise was made will defend all of them. One that has forgotten
looks at the artefact and asks why it is like that, which is the
question that finds the thing worth changing.

## The life

Saturation needs a loaded field. The N1 recipe is dense material that
is then loosened, and a trickle of fragments loads nothing. The agent
therefore has a life, which sits behind the project the way a person's
days sit behind their work.

It is a journal and not a novel. The first run wrote 58,000 words of
finished prose at about 90 seconds a day, and the links Drift made from
it cited what happened and what was there: a phone that rings out to
fourteen, a hinge hole crumbled in chipboard, a plot card pointing at a
renumbered row. None needed the sentences around those things. What
loads the field is events, objects, people and unfinished business per
word, and a journal carries more of those per word than prose does.

| Part | Content |
| --- | --- |
| Bible | who this is: a cast, places, a history, threads that stay open, and why this person wants the charter's thing built. Written once at the start, amended rarely |
| Backstory | thirty days written before the first turn, about 6,000 words, a week to a call. It is the life before the project began |
| Journal | one entry per simulated day, 120 to 300 words, append-only. One day in ten runs long, up to 800, the way a person sometimes writes a page |

A day is mostly not about the project. It is an argument, a train
ride, a meal, something overheard, a smell, an errand that went wrong,
a thing read, a memory. It is written the way people write for
themselves: fragments, dropped subjects, times, names, a list, a line
someone said, a thing left hanging. "Slept badly. Barry's letter re the
fence, a surveyor now, 'as a courtesy'. Didn't answer. Torch batteries
furred white." Every rolled event, object and person has to be in it.
Scene-setting, transitions and finish do not. Summary and reflection
still give Drift nothing to hold, and brevity is no excuse for them.

The owner belongs to no one run. Bible and backstory live under
`owners/<name>/` and are written once. A new project adds only the
stake and carries on the journal from where it stopped.

**The entropy comes from outside the model.** A model writing a life
unaided writes the same mild day forever. The harness rolls each day's
events from tables, threads them through the bible's open storylines,
and hands the writer real external text to fold in, which is the same
material Foreign reading pulls. The model supplies the prose. The dice
and the world supply what happens.

The owner need not work in software. A day job far from the project is
an advantage, because distance is what Drift feeds on.

**The project is in the diary the way work is in anyone's.** Most days
it is absent. Some days it gets a paragraph, and now and then a whole
evening. The harness rolls its presence like any other event, weighted
up after a bad return, and caps its share of a day at a quarter, since
a journal that turns into a work log has stopped being a life.

What the owner writes about the project comes only from what they saw:
the views the attention filter gave them and the findings of their own
spot checks, cited by id. Source code is never in it. The journal is
therefore their memory of the project, lossy and opinionated, and it is
the forgetting made concrete. What they remember is what stuck.

They will sometimes remember it wrong. Judgement takes fact from the
ledger and the plan, and takes from the diary only how the owner feels
about those facts. A spot check is what corrects a false memory.

**The life bleeds out.** The signals colour the day, so a run of failed
returns is a short-tempered evening. The day's valence in turn moves
the stance baseline. A bad night makes a risk-weighted morning.

**Where it is read.**

| Reader | Sees |
| --- | --- |
| Saturate and Drift | the bible and the most recent 80,000 words, whole |
| Wake and judgement | the last two days and the current mood |
| Sift | none of it |

Judgement carries the residue of a life, not the archive. Token cost is
not the reason, since the run is allowed to spend. The reason is that a
person decides on mood and yesterday, and that the charter must not be
diluted in the one call where every word of it has to land. Older days go cold like any other
element, and Replay can bring one back.

The journal is append-only, so everything before today is a stable
prefix and the prompt cache carries it. The cost per drift pass is
close to the cost of the new day.

Nothing in the life is evidence. It is fuel for Drift, a second anchor
at most, and the gate tests every candidate against the project alone.

**A sitting.** The regent owns the project and its decisions, and gives
it a small part of the day. A turn is a sitting: the hour after a shift,
a Sunday morning, ten minutes on a break. By default a day passes
between sittings, written beside the builders' work, which a journal
entry of 200 words makes cheap. Thirty turns is a month of their life.

Each day's roll includes how much time the project gets: none, a few
minutes, or an evening. That number feeds the attention draw, so a
wave-through has a cause a person would recognise. On a day with no
time the builders carry on with their own recommendation and the unread
debt grows. The project being a small part of a full day is also why
the dreaming works: most of what is on their mind is somewhere else.

## Casting

A regent is cast and not specified. The human pins a few facts, the
dice roll the rest, and the result is a person who fits and whom nobody
designed.

What is worth pinning is personality. The regent's work is dreaming,
noticing and deciding, and none of that comes from a career. The model
already knows the domain. What differs from one regent to the next is
what they cannot leave alone, how long they put up with a bad return,
how far they trust people who work for them, and whether a finished
thing makes them want more or want to stop.

Personality is held twice. In the bible it is prose: how they talk,
what they are like to work for, what they avoid. In the harness it is
the disposition, a set of dials that belong to the owner and not to the
run.

| Trait | Dial it moves |
| --- | --- |
| Cautious to bold | stance temperament, the slow baseline mood moves around |
| Curious | drift budget and how often a cycle runs |
| Patient | how fast frustration builds, and so how fast the ladder is climbed |
| Trusting | starting trust in an orchestrator, and how much attention trust buys off |
| Thorough | the lean of the read-mode draw, and the spot-check rate above its floor |
| Stubborn | how readily a criterion relaxes or a direction reverses |
| Restless | how much of the appetite they tend to use |

Reading a disposition off prose is a sample and not a measurement. Two
readings of the same regent a few minutes apart disagreed on five of
seven dials, and one changed sign. So a reading is taken three times and
shown as a median with its spread, the human approves what was shown,
and exactly those numbers are stored. A disposition is then fixed. It is
read again only when someone asks.

A pin can be a word, "impatient, generous, cannot leave a loose end",
and a reader turns it into dial settings once, shown to the human. A pin
can also be a dial set directly. Every trait not pinned is rolled. A
dial moves inside its floor, the same line ways and the interlude hold:
no personality lowers the spot-check floor, the audit rate or the debt
cap. Invention has a floor as well. A restless regent invents more per
cycle, and no disposition takes the count below the default, because
invention is what the regent is for. A cautious regent invents a
different kind of requirement, hardening over reach, and as many of
them.

Occupation, city, household and the rest stay rolled unless pinned, and
a life far from the project is an advantage. Where a project needs real
knowledge, a standard or a house style, it goes on the owner's shelf,
`owners/<name>/shelf/`, as things they have read.

```
regent owner new                          roll everything
regent owner new --pin "impatient, thorough, bold"
regent owner new --pin temperament=-0.4 --pin occupation="a lock keeper"
regent owner new --candidates 3           roll three, show a paragraph each, pick one
```

An owner is reused. Their journal carries on, their taste record grows,
and a regent on a fourth project is more experienced than one on a
first.

## Attention

A person does not read every word that comes back. They skim, they
glance, and on a full day they ask what the orchestrator recommends and
say go. The agent needs the same range for two reasons. Reading
everything is what fills a context, and an owner who reads everything
trains orchestrators to write returns nobody could skim.

An instruction to skim does nothing, because a model reads every token
it is handed. Attention is therefore a filter in the harness, between
the return and the agent, and the agent only ever receives the view its
attention bought.

**The return contract.** Every return has the same six parts in the
same order, which is what makes the cut mechanical.

| Part | Content |
| --- | --- |
| Headline | one sentence, what changed |
| Recommendation | what the orchestrator would do next, with one line of why |
| Flags | anything medium or high tier, any criterion missed, anything it is unsure of |
| Evidence | pointers to the artefact, screens, test results, timings |
| Assumptions | what the orchestrator and its builders took as given that the owner never said |
| Detail | everything else |

**Modes.**

| Mode | The agent receives | The ledger records |
| --- | --- | --- |
| Full | all six parts, and it operates the artefact | judged |
| Skim | headline, recommendation, flags, evidence list, assumptions, the first sentence of each detail section, every number | judged on a skim |
| Glance | headline, recommendation, flags | judged on a glance |
| Wave-through | the recommendation only | accepted on recommendation, unread |

The skim is cut by code, not written by a model. A model's summary is
faithful. It finds the thing buried in paragraph six and carries it
forward, which makes it a reader and not a skimmer. A mechanical cut
misses what a person would miss, costs nothing, replays exactly and
cannot flatter. One thing is added to it: a small model passes through
any line that matches a warm motif or a live unease, because a worried
eye catches the thing it is worried about.

**The draw.** The harness draws the mode for each return.

| Input | Effect |
| --- | --- |
| A high-tier flag | full, always |
| A medium-tier flag | skim at least |
| Returns queued behind this one | less attention |
| Time the day left for the project | none forces a wave-through, a few minutes leans to a glance |
| A thorough or a trusting disposition | more, or less, on every draw |
| Trust in this orchestrator | less attention |
| Risk stance, unease | more attention |
| Unread debt on the branch | more attention |

**Trust and debt.** Trust is a scalar per orchestrator configuration,
since the process is new each task, and audits earn it. One in five
glances and waves-through gets a full read later. Where the full read
agrees with what was accepted, trust rises. Where it finds something
the flags should have carried, trust drops hard and that branch gets
full reads until it recovers. Unread debt is the count of consecutive
returns on a branch with no full read, and at three the next one is
full. Every return is stored whole, read or not, so an audit or a later
failure can open it.

Only the view enters the manifold. The experience was a skim, and the
record says so. What slipped past comes back later as friction, which
is how a person finds it too.

## Spot checks

A return is what the orchestrator says happened. Sometimes the agent
looks for itself. An owner who only ever reads reports is managed by
whoever writes them.

A spot check is a separate call: the same self, mood and stance, a
question of its own, and read-only tools inside the project. It opens
files, searches, runs the artefact, and may put questions to the
orchestrator by resuming its session. It comes back with findings in
its own words, a few hundred of them, and only those enter the
manifold. The source it read is gone when the call ends. It looks at
the code the way an owner does, occasionally and with a question, and
does not live there.

| Trigger | Source |
| --- | --- |
| One return in six | the harness draws it |
| Unease high, or trust low | the harness |
| A return that reads too clean for what was asked | the agent asks |
| Any question the agent cannot settle from the view | the agent asks |

The agent asks through its decision: an `inspect` with a question, or a
`query` to an orchestrator. The harness grants both inside a budget.

What a spot check finds is set against what the return claimed. A
match raises trust. A gap drops it hard, enters the manifold as
friction, and usually becomes rework. It differs from an audit. An
audit reads the whole return. A spot check reads the project.

**Challenge.** An owner who has forgotten why a thing is the way it is
asks, and an orchestrator that made the choice has to defend it. Two
things feed this. Every return lists its assumptions, and the owner
picks at them. And the owner's memory of the project is the diary, so
what was settled weeks ago can look strange again. A challenge goes
down as a `query`. The answer has to stand on the work and on the
charter. "You asked for it" is an answer only where the ledger agrees.
An assumption that fails becomes an amendment, a new requirement, or
rework. An owner who forgot a good decision and challenged it has spent
one query, and the orchestrator's answer goes into the manifold where
it can stick this time.

A spot check is also a saturation event. Looking at the real thing is
where an owner says "why does it do that", and then "what if it did
this instead".

## Seeing the work

A return is the highest-texture input the agent gets. It holds no
source and no full context, so the artefact is the first concrete thing
it has met since forming the intent. A return is a saturation event,
not a verdict request.

Evidence is what a user of the system would meet: the running
artefact, screens, outputs, timings, test results. A builder's account
of its own work is narration, not evidence. In a full read, where the
artefact runs, the agent operates it as a user would before it reads
anything about it.

1. React. Write what the view shows into the manifold, verbatim and
   sensory, before any judgement.
2. Read the stance for this turn.
3. Judge against the current criteria.
4. Say what the thing in front of him is missing. New requirements
   come from here, in the same call, and no drift is run for it.

Judgement has four outcomes, not two:

| Outcome | Meaning |
| --- | --- |
| Accept or reject | the criteria answered it |
| Raise | the return shows better is reachable than was asked for |
| Relax | the criterion cost more than it is worth, or aimed at the wrong risk |
| Redirect | the return shows a different thing should be built |

A fifth thing can happen that is not an amendment. What came back
suggests something adjacent and unbuilt, which becomes a standing
objective with a weight, not an edit to a dispatch in flight.

**Acceptance is versioned, not fixed.** Criteria go down with the
dispatch and hold until something seen changes them. An owner revises
on contact with the work, and a system that cannot revise builds what
it specified instead of what it wanted. Revision stays honest because
an amendment is a separate written act with a trigger, a direction and
a timestamp, never a clause inside an acceptance. An amendment written
in the same turn as an accept is written first and names what in the
artefact triggered it. A ledger that only ever relaxes is a detector
firing, not a record.

**Stance.** Each turn carries a weighting over judgement rather than a
fixed policy. One end is risk-weighted: prefers evidence, shrinks
scope, raises the bar on failure modes. The other is
opportunity-weighted: prefers reach, accepts partial, spends on the
adjacent possible.

| Input | Tilt |
| --- | --- |
| Recent manifold heavy on friction | risk |
| Recent manifold heavy on unfinished and foreign | opportunity |
| Last drift produced accepted candidates | opportunity |
| Last drift died at the groundedness floor | risk |
| Unease high, evidence thin | risk |
| Interlude stance drift | either, bounded |

Stance is written into the turn record in one line before judgement, so
an accept can be read later against the disposition that produced it.
It changes the weights on Sift's four axes and the size of the drift
budget. It never changes the gate or the risk tiers.

Stance moves every turn, by a bounded step around a slow baseline.
Mood changes daily. Temperament changes over weeks.

## Inventing requirements

Invention is the purpose of the mood, the life and the dreaming. The
brakes elsewhere in this design exist to keep invention honest, and
none of them exists to prevent it. A product owner who accepts good
work against the original list has added nothing. The value is the
requirement nobody wrote down, seen because the thing now exists and
because the person looking at it has had a particular week.

Most requirements come from sitting down with the work. In the real
runs four of six came from judgement on seeing a return or the findings
of a spot check, at no extra cost, and they were the ones that got
built. So every sitting is asked what the thing in front of him is
missing, and a spot check's openings go straight to judgement as
candidate requirements. The cycle is the rare deep pass that finds what
sitting with the work never would.

**What is worth building.** A requirement has to be something a user of
the thing would notice, small enough to build in one dispatch, and
stated with the observable behaviour and the test that proves it.
"Prints a count of wiki links it saw and did not check" passes. "Test
infrastructure must distinguish false positives from false negatives"
and "keep the docstring accurate" do not: they are standards for the
builders, and they go in the ways. Requirements invented in a sitting
ride down together in the next dispatch, up to five at a time. The real
run sent three of his ideas as three dispatches in series, nine minutes
each.

Mood decides what kind. A risk-weighted day invents hardening: this
must survive that failure, this needs a limit, this cannot be trusted
yet. An opportunity-weighted day invents reach: it could also do this,
these two parts are one idea, this belongs to a wider audience. Both
are requirements and a run needs both.

**The requirement gate.** An invented requirement becomes work when it:

- serves the charter's intent, and says how
- breaks no constraint and no refusal
- names the rework it causes, in accepted work undone
- fits inside the appetite that remains

**The owner's requirements are the owner's to make.** The first real
run escalated every requirement he invented, three of three, and built
none. A reader had been asked whether each one changed what is being
built. Every requirement does, which is what a requirement is. That
outcome defeats the design, so the rule is stated the other way round.

- A requirement that passes the gate becomes work on the owner's word.
  Nobody is asked.
- Growing the project is inside his authority: new features, a wider
  reach, a different shape, a second audience alongside the first,
  rework of what was accepted. The appetite is the governor, and the
  charter sets it.
- A requirement waits on the human in one case only: it touches a
  reserved class. That is the same rule as any other decision.
- A requirement that would replace the thing being built, or drop the
  people it is for, is not blocked and not escalated. He builds toward
  the charter he has, and the idea goes to the human as a process note,
  what he thinks the charter has wrong.
- The owner's own `changes_charter` flag governs. A reader may overrule
  it only by quoting the charter line the requirement contradicts. A
  line it extends is not a line it contradicts.

**Rework is a cost the design accepts.** A new requirement may undo
accepted work, and it may turn the project in a new direction. Both are
his to decide where the work is revertible, which is nearly always.

Each invented requirement records its origin: the drift links, the day
in the life, the return or the spot check that set it off. The digest
lists each one with its origin and its rework, so the human can see
where the project turned and why.

## Directing, challenging, constraining

A human owner does three things to the people doing the work, and the
record of how this design was made shows all three in about equal
measure. They direct: build this. They challenge: why is it like that,
is that the right way. They constrain: not like that, inside this
limit, faster than that, leave this alone. A regent who only directs is
a ticket queue with a mood.

| Verb | What the regent does | Mechanism |
| --- | --- | --- |
| Direct | says what to build and what must be true of it | a dispatch: intent and acceptance |
| Challenge | questions an assumption, a choice, a claim, or his own earlier decision | a `query` or a challenge, answered on the work and the charter |
| Constrain | bounds how the work is done | a dispatch's constraints, tightened at any time |

**Constraints are their own part of a dispatch**, beside intent and
acceptance. Acceptance says what must be true at the end. Constraints
say what the work may cost and where it may go on the way: a wall-time
and spend limit, files and areas left alone, approaches ruled out, a
bar such as "no new dependency" or "one file". He can set a target and
demand it be attacked, the way a person says get this under twenty
minutes and be aggressive about it.

His constraints sit inside the charter's and only ever tighten them. He
cannot loosen a charter constraint, and he can relax one of his own.
The harness holds what it can by mechanism: a dispatch's time and spend
limits end it and bring back what exists, and tool limits go down as
allowed and denied tools. The rest the orchestrator is bound to, and a
spot check is how he finds out whether it was.

**He can reach work in flight.** A running orchestrator cannot be sent
a message, and an owner who can only speak between returns is one who
watches a mistake finish. Each dispatch has a standing-orders file, and
the orchestrator reads it before every step. A `constrain` or a
redirect on a running dispatch is written there and takes effect at its
next step. Messages between agents cross, and a file that is re-read
does not.

Stepping back counts all three. A period of dispatches with no
challenge and no constraint is a fault, the same as the unchallenged
assumptions that the first real run found.

## Where a regent is used

Anywhere a project needs another eye or a temporary authority, new or
existing. The charter says which, by how much authority it hands over.

| Use | Authority | What the regent does |
| --- | --- | --- |
| A new project | full, under the charter | everything in this design |
| An existing project | full or partial | the same, after a looking-around |
| Another eye | none over the work | reads, spot-checks, challenges, invents, and writes it all down for the human. Dispatches nothing |
| A regency | full, for a term | holds the authority for a period the charter sets, then hands back |

**Looking around.** On an existing project his first sittings are spot
checks with no return to check: what is here, what does it do, what
state is it in, what would a newcomer trip over. The findings are his
memory of the project, and they are where his first requirements and
his first challenges come from. He does not read the whole codebase. An
owner never has.

**Handing back.** A regency ends with a handover: what was decided and
why, what he would do next, what he thinks the charter has wrong, and
every question still open. The human takes the authority back by
ending the run, and nothing else is needed.

## Signals and the ladder

Affect here is four computed scalars that change what the loop does.
Nothing is performed in prose.

| Signal | Computed from | Effect |
| --- | --- | --- |
| Frustration | failures on one subgoal | moves down the ladder |
| Curiosity | unexplained observations in manifold | raises drift budget |
| Satisfaction | acceptance criteria met | closes the subgoal, releases budget |
| Unease | evidence thinner than the claim | blocks the dispatch, demands a check |

Signals carry across turns and an interlude decays them, so a bad run
colours the next judgement without owning it.

Frustration is only useful if it has somewhere to go. The ladder, one
rung per repeated failure:

1. Retry with the same approach.
2. Change the approach.
3. Change the builder.
4. Amend the criterion.
5. Escalate to the human.
6. Kill the subgoal and take the budget elsewhere.

Rung 6 is the one agents never reach on their own. A subgoal with no
state change in five cycles loses its allocation whether or not
frustration fired.

## Stepping back

Everything above looks at the project. Consolidate files what was
learned about it. Nothing yet looks at how the work itself is going,
and a human owner does that unprompted: they notice that their notes
keep arriving too late, that the same module has been redone three
times, that they have waved a branch through for a week and then been
surprised by it. Then they change how they work, not what they are
building.

Stepping back is its own call, the same self in a fresh context, and
its subject is the run and never the project.

**What it reads.** The harness builds a process view in code from the
ledger and the metrics, so the numbers are counted, not recalled.

| In the view | Examples |
| --- | --- |
| Flow | turns per accepted dispatch, rework count, reversals, time on each branch |
| Reading | the mix of read modes, unread debt, what audits and spot checks found against what was waved through |
| Trust | the path of each orchestrator configuration, and what moved it |
| Asking | queries and challenges sent, how many changed anything, how many were answered from the ledger |
| Mood | the stance path, where frustration peaked, which rungs of the ladder were reached |
| Invention | requirements invented, their rework, appetite used, which origins produced the ones that lasted |
| Faults | every detector that fired in the period |

**What it writes.** Observations about how the work is going, and
changes to the ways of working. The ways are a short file, `ways.md`,
of standing practices in the owner's words: how a brief is written,
what every return must show, how big a dispatch is, when to look for
oneself. Wake reads the ways, and they go down with every dispatch as
standing instructions. They are this design's equivalent of the
feedback a person gives a team once, so it need not be given again.

Each way is an experiment. It names the pattern in the process view
that prompted it, the number it expects to move, and a review date in
turns. At review the harness sets the before and the after side by
side, and the way is kept only where the number moved. The file holds
seven at most, so an eighth has to displace one.

**What it cannot do** is the interlude's line again. A way changes how
the owner works and never what the owner is permitted. It cannot touch
the charter, the refusals, the reserved list, the tiers or either gate,
and it cannot lower a floor: the spot-check rate, the audit rate and
the debt cap may rise and never fall. Where the owner thinks the
charter itself is the problem, an appetite too small or a constraint
that costs more than it protects, that goes to the human as a process
note in the digest and is never applied.

**When.** Before each digest, so the human reads how the run is going
next to what it decided. Also when a detector fires, when a branch
reaches rung four of the ladder, and when trust in a configuration
collapses.

## Context over a long project

A project that runs for weeks produces more material than any context
holds, so the allocation is fixed and the overflow is forgotten rather
than compressed.

| Allocation | Holds | Rule |
| --- | --- | --- |
| Charter and self | intent, refusals, objectives | never evicted |
| Ledger | decisions, amendments, escalations | never evicted, summarised by date |
| Ways | standing practices, seven at most | never evicted, changed only by stepping back |
| Plan | live dispatches and criteria | evicted on close |
| Manifold | experience, warm | decays by age and citation |
| Returns | evidence from this turn | evicted after consolidation |
| Life | the last two days in judgement, 80,000 words in Drift | older days go cold |

Source code is in none of them. Judgement reads evidence, not files,
and the context it saves is spent on experience instead. A spot check
reads files in a call of its own and carries back findings only.
Implementation detail is the first thing forgotten and the cheapest to
recover, since a query or a spot check answers any question about it in
one turn.

## The tree

| Level | Owns | Never |
| --- | --- | --- |
| Regent | intent, requirements and their invention, acceptance and its amendment, priority, stop | writes code, holds source in its context |
| Orchestrator | decomposition, sequence, integration | amends acceptance, it raises |
| Builder | implementation, tests, evidence | decides scope |

Down goes intent plus acceptance criteria and the ways. Up comes artefacts plus
evidence, never narration. An orchestrator that wants a criterion
changed raises it and does not reinterpret it. Amendment happens at the
top or not at all, and that one rule is most of what keeps a
three-level tree from drifting.

## What the human still does

Four things, and the list is short deliberately.

1. Writes the charter.
2. Answers escalations, which are only high-tier decisions.
3. Reads the digest, one page at a cadence the charter sets: decisions
   made, requirements invented with their origin and rework, amendments
   with triggers, spot-check findings, what was killed, what is next,
   and the process notes from stepping back: how the run is going, which
   ways changed and why, and anything the owner thinks the charter has
   wrong. Anything in it can be reversed, which costs a revert
   and never a wait.
4. Ends the run, or changes the charter, which is the only way the
   mission changes.

Not on the list: approving a plan, reviewing a diff, choosing between
two designs, or being asked whether the agent may proceed.

A fifth thing is open to the human and never required: influence, for
when they would rather steer than order.

## Influence

The charter is how the human orders. Influence is how the human steers
without ordering, and the owner never knows it happened. An order
changes what the owner must do, and it costs the thing this design
worked for, an owner whose mission is their own. Influence changes what
the owner meets, notices and feels, and leaves the deciding to them.
The idea that follows is theirs.

| Channel | What the human supplies | How it reaches the owner |
| --- | --- | --- |
| Plant | something met: a remark, a sight, a complaint, a small event | folded into the next day's rolled plan, written as lived, no different from what the dice gave |
| Voice | a line for someone in the cast | that person says it, in their own way, on a day they would be there |
| Reading | a text or a link | the owner reads it, as Foreign reading |
| Mood | a lean toward risk or toward opportunity, for some days | a good or a bad stretch in the life, which moves the stance baseline |
| Worry | a motif | the skim filter's salience pull lets matching lines through, so the owner's eye catches them |
| Itch | an area of the project | the next spot check is drawn there, with a question the owner forms |
| Recall | an element gone cold | Replay brings it back |
| Dream | a theme | the next untargeted dream starts from it |

Each takes a weight. A whisper is one detail in one day. A nudge is an
event in a day. A push recurs across days and adds a worry. A plant
waits for the next day to be written, and the harness brings a day
forward where none is due within three turns.

**It may not take.** Influence passes through everything the owner's
own ideas pass through: Drift has to find it, Sift has to keep it, and
a requirement still has to clear the requirement gate and the appetite.
The owner can meet a plant and make nothing of it, or reject what came
of it. That is the point. Influence that always lands is an order
wearing a disguise, and an owner who cannot resist it has no judgement
worth having. A human who needs it to land changes the charter.

**The lines it cannot cross.**

- It steers what the owner meets and never what the owner is permitted.
  The charter, refusals, reserved list, tiers and both gates stand.
- It enters through the life and through attention, and never through
  evidence. Nothing planted can appear in a return, a spot-check
  finding, the ledger or any project texture of the manifold. The human
  may point the owner's eye at a real thing. The human may not put a
  false thing in front of it.
- It is invisible by mechanism. Plants are recorded in a file no model
  call ever reads, and what the owner's contexts receive carries no
  mark of where it came from.

**The human can see what came of it.** A plant has an id, and origins
are already traced, so the harness follows it: the day it entered, the
drift links that drew on it, the requirement or challenge or spot check
it led to, and whether that survived. Each influence shows as pending,
took, faded or rejected. The digest carries that to the human in a part
appended by the harness after every model call has finished.

```
regent influence plant "<what he meets>" [--weight whisper|nudge|push]
regent influence voice <cast-name> "<what they say>"
regent influence read <file-or-url>
regent influence mood risk|opportunity --days <n>
regent influence worry "<motif>" --days <n>
regent influence itch "<area of the project>"
regent influence recall <element-id>
regent influence dream "<theme>"
regent influence list
```

Plants are inputs to the run, logged with the turn they entered, so a
replay from the seed replays them too.

## Failure modes

| Mode | Symptom | Detector |
| --- | --- | --- |
| Apophenia | confident links between unrelated things | gate, disconfirming test |
| Motif lock | the same four images every pass | consecutive-pair counter |
| N2 drift | fluent output with no anchors | groundedness floor |
| Captured filter | Sift loves everything | fresh context for Sift |
| Timid owner | returns accepted against the original list, nothing invented | invention count in the digest, zero across a period is a fault |
| Overruled owner | what he invents leaves his hands and is never built | the share of invented requirements that waited on a human, above one in five is a fault |
| Hands tied | builders cannot run what the work needs, so returns come back unproven | the charter's Tools line, and a return flagging "requires approval" is a harness fault, not a rejection |
| Trusting owner | never looks for itself | spot-check floor of one return in six |
| Unchallenged assumptions | returns list assumptions and none is ever questioned | challenge count in the digest, zero across a period is a fault |
| Work-log life | the journal fills with the project and Drift loses its distance | the project's share of a day is capped at a quarter |
| False memory | the diary states something about the project that is not so | judgement takes fact from ledger and plan, a spot check corrects the diary |
| Blind process | the same friction every period and nothing about the work changes | stepping back runs before every digest, from counted numbers |
| Superstition | ways pile up with no sign they help | each way is reviewed against its number, seven at most |
| Process as excuse | a way that quietly loosens scrutiny | floors rise and never fall, checked in code |
| Navel-gazing | more stepping back than work | its triggers are fixed, and it has its own budget |
| Regent in the way | the builders wait on the regent, or the regent outspends them | per-call ledger rows, the critical path in the digest, a fault when his blocking time on a turn exceeds theirs |
| Dreaming for its own sake | cycles fire often and land nothing | every fifteenth turn only, and the digest shows requirements landed per dollar of dreaming |
| Puppet owner | most of what the owner invents traces to a plant | the share of requirements with an influence in their origin, shown to the human only |
| Leak | the owner learns it is being steered | the influence file is read by no model call, and a test plants a marker and searches every assembled context for it |
| Planted evidence | an influence dressed as a project fact | plants enter the life and attention only, refused anywhere else in code |
| Word-matched meaning | a rule about what text means, held by keywords | readers, each finding resting on a quote the harness verifies |
| Invented grounds | a reader finds a breach that is not in the text | the quote must occur verbatim or the finding is discarded |
| Churn | a direction reversed, then reversed back | appetite caps it, a reversal needs a trigger the first turn lacked |
| Goalpost drift | criteria always match what arrived | ledger that only relaxes |
| Stance thrash | disposition swings end to end between turns | bounded step per turn |
| Shared blind spot | judge and builders agree because they are one model | interlude, forgetting, operating the artefact |
| Mission drift | objectives that serve no charter line | every objective cites the charter, digest lists new ones |
| Runaway | many medium decisions compounding into a high one | tier the cumulative effect, not the single act |
| Charter creep | the agent rewrites its own constraints | charter is user-write-only, diffed each run |
| Load-bearing forget | a constraint dropped with the detail | refusals and ledger never decay |
| Sycophancy down | work accepted because the return said it was good | evidence required, amendment written before the accept |
| Unread pile-up | branch after branch waved through | debt cap at three, one in five audited, read mode in the ledger |
| Buried defect | the flags left out what mattered | audit compares flags to the whole return, trust drops hard |

## Implementation

The harness is plain code and not a model. It owns the state machine,
every random draw, the attention filter, the stop rules in Catch,
context assembly, the budget and every write to disk. Anything that has
to be reliable, or has to be random, is code. Models are called for
judgement and generation only, each as one `claude -p` call.

**Context is assembled, never accumulated.** The regent is
a fresh call every turn, run with `--no-session-persistence`. The
harness builds its prompt from the allocations in the context table and
the view from the attention filter. A resumed session is perfect
memory, which is the one thing this agent must not have. Orchestrators
are the opposite and resume their session for the life of a task.

**Rules hold by flag, not by instruction.**

| Rule | Mechanism |
| --- | --- |
| Judgement holds no source, writes no code | `--tools "" --strict-mcp-config --setting-sources ""`. `--tools ""` alone leaves the user's MCP servers attached, and one of those can edit files |
| A spot check reads and never writes | its own call with `--tools "Read,Grep,Glob"` in the project, plus the artefact tool. Findings come back under `--json-schema` |
| Cannot touch charter, ledger or gate | it writes nothing. It returns a decision under `--json-schema` and the harness applies it |
| Operates the artefact in a full read | one MCP tool scoped to the running artefact, `--mcp-config` with `--strict-mcp-config` |
| Carries no ambient project context | `--system-prompt` replaces the default, and `--bare` drops CLAUDE.md, hooks and memory where API-key auth is in use |
| Spend | `--max-budget-usd` per call, the run budget in the harness |
| A call touches only its own directory | the harness sets the working directory of every child. `claude -p` otherwise inherits the parent's |

Smoke calls on this machine settled three more things. A decision
under `--json-schema` comes back in the `structured_output` key of the
JSON envelope. The harness mints each orchestrator's session id with
`--session-id` and resumes it with `--resume`. A toolless call with no
settings sources also costs about a tenth of one that loads them.

**Meaning is read by a model, never matched by words.** Code counts,
cuts, draws, validates shape and holds floors. Whether a piece of text
means a thing is not a job for code. The first real run showed why: a
keyword check escalated a dispatch because its acceptance promised to
obey a refusal, in the refusal's own words. Every such check is a
reader call instead.

A reader is the smallest model, toolless, isolated, in a fresh context,
answering under a schema. It is a different model from the judge, so
the two do not share a blind spot. It gets the charter lines in
question and the text in question, and nothing else. Three rules keep
it honest:

- It must quote. Every finding carries the exact span of the text it
  rests on and the charter line it touches. The harness checks in code
  that the span occurs verbatim. A finding with no real quote is
  discarded.
- It must say which way the text points. A promise to comply, a
  description of what is avoided and an intent to do the thing are three
  different answers, and only the last is a finding.
- Unsure goes up. An unsure answer is asked again of the mid model. Still
  unsure, it is treated as a finding. The cost of stopping on a person
  once is smaller than the cost of a reserved decision made unseen.

- It is told who each line binds. "The tool writes only to stdout"
  binds the product. "Never install a package" binds the work. The
  first run rejected a fixture dispatch for creating files, against a
  line about the tool. The charter marks each line as binding the
  product, the work or both, and the reader gets that mark.

The declared tier from the judge and the reader's tier are both kept,
and the higher one governs, for breaches of refusals, constraints and
reserved classes. It does not govern the owner's authority to invent,
where a nervous reader costs the run its purpose.

| Read by a reader | Replaces |
| --- | --- |
| Does this dispatch or decision touch a reserved class or break a refusal or constraint | keyword and stem matching against the charter |
| Does this requirement contradict a charter line, quoted, as opposed to extending one | nothing. The owner's flag governs unless a contradiction is quoted, and even then the result is a process note |
| Does this objective or requirement serve the charter line it cites, and how | counting shared content words |
| Does this way loosen scrutiny or reach for something forbidden | matching forbidden nouns near loosening verbs |
| Does this decision reverse an earlier direction | any textual comparison of decisions |

What stays in code: the attention cut, the Catch rules, every draw,
schema validation, the floors, the surfaces an influence may enter, and
the check that a quote is real.

**Where a refusal can be held by permissions, it is.** "Never make a
network request" is a denied tool before it is a sentence anyone has to
interpret. At the start of a run a reader proposes tool denials for the
orchestrators from the charter's refusals and constraints. The human
confirms that list once, with the charter. The reader calls above then
cover only what permissions cannot express.

**Models by role.**

| Role | Model | Reason |
| --- | --- | --- |
| Wake, judgement, stepping back | the largest | these are the decisions that compound |
| Saturate, Consolidate | mid | extraction and filing |
| Drift | several sizes in parallel | looseness |
| Sift | a different family from Drift where one is available | decorrelation |
| Salience match | the smallest | volume |
| Readers | the smallest, and never the judge's model | meaning, read apart from the one who wrote it |
| Life writer | mid, or a second vendor for a voice that is not the judge's | long prose with continuity |
| Orchestrators | large, resumable | decomposition across a long task |
| Builders | mid, as the orchestrator's subagents through `--agents` | throughput |

Drift reaches its looseness three ways. Each pass gets a different
random subset of the warm manifold. Passes run on mixed model sizes,
because a smaller model makes jumps a larger one would not, more of
them wrong, and wrong is cheap when Sift exists. And Drift is the one
state that may call the API directly, where the model accepts a
temperature.

Sift on a second vendor's model is the cheapest decorrelation there is.
It needs only a CLI the harness can call. The taste record stays with
judgement, so one reader owns it.

**Prompts up the tree, skills down it.** Each state of the
regent is a prompt file the harness fills. It has no tools
and no slash commands, so a skill gives it nothing. Down the tree the
return contract rides in the orchestrator's system prompt, because a
skill loaded with `--plugin-dir` did not trigger in a headless call
when tested. The plugin still ships `return-report` and
`evidence-capture` as reinforcement, and for orchestrators a person
runs interactively.

```
charter.md      user-written, read-only to the run
self.md         objectives, first person
taste.md        accepts and rejects with reasons
ledger.jsonl    decisions, amendments, escalations, read modes
ways.md         standing practices, each with its trigger and review
influence.jsonl the human's plants and what came of them, in no model's context
manifold/       warm.jsonl, cold.jsonl
life/           bible.md, journal/ one file per simulated day
returns/        every return whole, read or not
prompts/        one file per state
plugin/         return-report, evidence-capture
regent/         the harness: the loop, the draws, the filter
```

## Running it

The harness is a Python program and the only long-lived process. Every
model, the regent included, is a `claude -p` child it
starts and waits on.

```
regent  (the harness: python, one process for the life of the run)
├─ claude -p  regent                fresh each turn, no tools, JSON out
├─ claude -p  spot check            read-only tools, findings out
├─ claude -p  saturate, drift ×K, sift, consolidate    fresh each cycle
├─ claude -p  life writer           the bible once, then a day at a time
├─ claude -p  stepping back         no tools, the process view in, ways out
├─ claude -p  reader                no tools, one question of meaning, a quoted answer out
└─ claude -p  orchestrator          one per dispatch, resumed per task,
   │                                runs inside the project with tools
   └─ builders                      its subagents, inside its process
```

The regent and the orchestrators are siblings under the
harness, not parent and child. The regent has no tools, so
it cannot start anything. It returns a decision that contains
dispatches, and the harness starts an orchestrator for each one. The
authority runs top down. The processes do not. Builders are the only
true nesting, because an orchestrator spawns them itself.

```
regent run charter.md --project <dir>    start, or pick up a stopped run
regent status                            where the run stands
regent watch                             one line per decision as it lands
regent digest                            the page for the current period
regent answer <id> "<text>"              reply to an escalation
regent stop                              finish the turn in flight, then halt
```

`status` is the view of progress toward the goal. It shows the
charter's stop condition, each objective with its weight and how many
of its criteria are met, requirements invented and the appetite they
have used, dispatches in flight, budget spent against
budget set, escalations waiting, and the current stance and signals.
`watch` tails the ledger, so each line carries the decision, its tier
and the read mode behind it. Each orchestrator streams to a log under
`returns/`, which is the place to look when a line in `watch` needs
explaining. An escalation also sends a notification, since it is the
one thing in the run that waits on a person.

All state is on disk, so the harness can stop and start without losing
the run.

## Pace

The first real run built an 11-minute link checker in over two and a
half hours. The ledger's timestamps say where the time went.

| Where | Wall time | Why |
| --- | --- | --- |
| Backstory | about 70 min | 30 calls in series, 2,000 words of finished prose each |
| Each spoon cycle | 19 and 23 min | three passes each reading 58,000 words, then Sift writing a verdict on every link |
| The orchestrator's build | about 11 min | the actual work |
| Judgement and the spot check | 1 to 4 min each | |
| Halted on escalations | 11 min and counting | nobody there to answer |

The second leg, after the first round of cuts, was 55 minutes for six
turns, about nine minutes a turn, and the regent still cost five times
what the builders did: $19.67 against $3.83. That is not good enough.
The regent exists to guide and grow the project. Every minute it holds
the builders up is a minute it has failed.

**The target.** Two rules hold on every project: the builders hold at
least 60% of the wall time and at least half the spend, and the regent
never sits in their path. How long a run should take is the charter's
to say, in its Budget, because a link checker and a billing system
share no number. For the example charter that number is 20 minutes from
`regent run` to a stopped run with a working tool, which is generous
for a link checker, with at least four requirements he invented built,
user-visible and tested.

**Nothing of the regent's sits in the builders' path.**

- **Fan out on turn 1.** Everything independent goes down at once, up
  to the concurrency cap. The tool and its fixture are two dispatches in
  parallel, not two turns.
- **Launch first, check beside.** A low-tier dispatch starts the moment
  it is decided. The reader checks it against the charter while it runs,
  and a breach kills it. Low tier means revertible, so optimism costs a
  revert at worst. Medium and high tier still wait for the reader.
- **One call per sitting.** React and judge are one call. Its context
  is cut to what the decision needs: the plan, the views, the last two
  days, the ways, and ledger rows from the last five turns. Older rows
  are there as counts.
- **Spot checks run beside the next dispatch.** Findings land the
  following turn. A spot check never holds up a judgement.
- **Batch his ideas.** Requirements from a sitting go down together in
  one dispatch.
- **Skip a layer on small work.** Where a dispatch is one builder's
  job, the orchestrator is the builder. A subagent layer is for work
  that needs decomposing. The third real run showed the layer failing
  outright: a headless orchestrator handed the tool to a background
  subagent and ended its turn with "the builder is still working on
  it", so ten minutes of work came back as no return at all.
- **Keep coupled work together.** A tool and its tests are one
  dispatch. Split apart, the tests' builder wrote its own reference
  link checker to have something to test against. Fan out only what is
  independent, such as a fixture.
- **Watch output tokens, since they are the wall time.** Each dispatch
  wrote about 50,000 output tokens on the mid model for an artefact of
  about 8,000, close to ten minutes of pure generation. Builders on
  small work run at low effort, write a file once and patch it after,
  and return the contract without an essay.
- **Allow the commands as they are really typed.** An allowlist of
  `python3` refused `ls && python3 -m unittest` and
  `LINKCHECK_PATH=x python3 -m unittest`. Each refusal costs a turn. The
  charter's Tools line is expanded to the forms a shell user writes, and
  the brief tells builders which forms are allowed.
- **Dream every fifteenth turn**, in the background, as one Drift pass
  of twenty links on the smallest model and a two-step Sift. Under a
  dollar. The three-pass cycle is for charters with the budget for it.
- **Write a journal, write an owner once**, and write the day beside
  the work. A run starts at turn 1.
- **A question lapses when its condition resolves.** A run halts only
  when no work can proceed and a high-tier question is open. A stale
  medium-tier precaution stopped a finished project at turn 10.
- **Always end with stepping back and a digest**, however few turns the
  run took.

**Measure it or it did not happen.** Every model call writes a ledger
row: role, model, start, end, tokens, cost, and whether anything waited
on it. The digest reports the critical path, the regent's wall time and
spend against the builders', per turn and in total, and names the
slowest thing that blocked a builder. A turn where the regent's blocking
time exceeds the builders' is a fault.

## Build order

1. The harness loop, charter, risk tiers and ledger, with one Wake call
   and one orchestrator. Authority transfer is the product. Everything
   else is how it is exercised well.
2. The return contract and the attention filter, full and skim only.
3. Manifold writer and reader, with ids, textures and decay.
4. Drift and Sift as separate calls on separate models, plus the gate.
   Measure the top five against what Wake alone produces.
5. Seeing the work: amendments and stance.
6. Glance, wave-through, trust and audits.
7. The interlude, weakly weighted at first, with forgetting last.
8. The life: bible, backstory, the daily journal, and the read split in
   context assembly.
9. Spot checks and queries.
10. Invented requirements: the two write-ups from Sift, the requirement
    gate, appetite, origin and rework in the ledger and the digest.
11. One self: the bible's stake in the charter, the project in the
    diary from what the owner saw, assumptions in the return contract,
    and challenge.
12. Stepping back: the process view built in code, the call, `ways.md`
    with reviews and the cap of seven, floors that only rise, ways sent
    down with each dispatch, process notes in the digest and the export.
13. Influence: the eight channels, weights, the file no model reads,
    the trace from plant to outcome, the human-only part of the digest,
    and the `regent influence` commands.
14. Readers: every check of meaning moves from word matching to a
    reader call with a verified quote, the higher tier governs, and
    tool denials are proposed from the charter and confirmed once.
15. The owner's authority: requirements become work on his word, a
    reserved class is the only wait, a contradiction of the charter is
    a process note, the charter's Tools line, and who each line binds.
16. Pace: the journal form, owners written once and reused, cycles
    beside the work and on a slower schedule, smaller Drift passes, the
    two-step Sift, and owner overhead against builder time in the
    digest.
17. The name: the package, the command and the repository become
    `regent`. "The harness" stays as the word for the program that runs
    the regent.
18. Casting: `regent owner new` with pins, rolled traits, the
    disposition dials held per owner inside their floors, candidates,
    and the shelf.
19. Sittings: a day between turns by default, written beside the work,
    the day's time for the project feeding the attention draw, and a
    day with no time leaving the builders to their recommendation.
20. Twenty minutes: the Pace section's target and rules, per-call
    timing and cost in the ledger, the critical path in the digest, and
    the fixes the second run found: cycle candidates that never reach
    him, requirements never marked built, the stepping-back window
    resetting, the contradiction check reading his objectives as the
    charter, and the stale question that halted a finished run.
21. Directing, challenging, constraining: constraints as a part of
    every dispatch held by mechanism where possible, `constrain` as a
    decision, standing orders an orchestrator re-reads so he can reach
    work in flight, all three verbs counted by stepping back.
22. Where a regent is used: the charter's authority level, the
    another-eye mode that dispatches nothing, looking around on an
    existing project, a term, and the handover.

Run it first on a project where every decision is low tier and the
whole thing is revertible. The digest is the evidence for whether the
authority was used well, and it is also the argument for widening the
tiers on the next one.

## Open questions

- Who writes the manifold. Self-observation is cheap and biased. A
  separate observer agent is honest and costs a second stream.
- How much flex before intent is just whatever arrived. A candidate
  limit is amendments per goal, with a floor on the ratio of raises to
  relaxes.
- Whether stance is visible to orchestrators. Told, they aim at it and
  returns stop being independent evidence. Hidden, they return work
  aimed at a disposition that has moved.
- How to tier a decision whose risk only appears in aggregate.
- Whether the skim should be this lossy. The test is defects reaching
  the digest under the mechanical cut, against a control that gives the
  agent a faithful summary.
- Whether orchestrators learn to game the contract, a confident
  headline over thin detail. Audits catch it late. Nothing yet catches
  it early.
- Whether the life changes what Drift finds, or only how it is worded.
  The N1 study found no link between what people dreamed and whether
  they got the insight. The test is the same project run three ways:
  no life, a thin life, the full life.
- Whether the interlude earns its cost. The test is accepted candidates
  and caught defects per 100k tokens, against a control that runs the
  same project with no interlude.
