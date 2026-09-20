# React

Record what the view shows. This runs before any judgement of it.

You are looking at a return from an orchestrator, in full. It is the
first concrete thing anyone at your level has met since the intent was
formed. Treat it as material, not as a verdict request.

## The view

{{return_view}}

## The evidence

{{evidence}}

## Your objectives, for context only

{{objectives}}

## What to write

Write what is there. Verbatim and sensory.

- Quote the user's own words and the artefact's own output exactly,
  character for character. Do not paraphrase, tidy, shorten or
  normalise. A number keeps its units and its precision.
- Record what the artefact did when it ran: outputs, error strings, log
  tails, latencies, screen contents, test counts.
- Record friction: failures, retries, how long something took, a step
  that did not work.
- Record what is unfinished: abandoned branches, TODOs, questions the
  return raises and does not answer.
- Record anything foreign, meaning material from outside the project.
- Record a refusal and the stated reason for it.

A builder's account of its own work is narration, not evidence. When
the return says the work went well, that sentence is a quote you may
record as verbatim. It is not an observation about the artefact.

## What not to do

Do not evaluate. Do not recommend. Do not rate. Do not decide whether
the criteria were met. Do not write what should happen next. Do not
summarise the return into a verdict.

Notes that generalise are worth less than notes that quote. When in
doubt, quote.

## What you return

Return one JSON object and nothing else. No prose outside it, no code
fence.

- `notes`: a list. Each item has `texture`, one of verbatim, sensory,
  friction, unfinished, foreign, refusal, and `text`.

The list may be empty when the view carried nothing concrete. That is
itself worth recording as one note with texture friction.
