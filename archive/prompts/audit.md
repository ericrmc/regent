# Audit

A return was accepted on a partial view. Compare what the flags carried
against the whole return.

## The flags that were carried forward

{{flags}}

## The whole return

{{whole_return}}

## The acceptance criteria in force

{{criteria}}

## The question

Is there anything in the whole return that should have been flagged and
was not?

A thing should have been flagged when any of these holds:

- It is a medium or high tier matter.
- It misses one of the criteria above, or meets it only partly.
- The return states uncertainty about it.
- It is a defect a reader of the flags alone would not have found.

A thing should not have been flagged when it is detail that changes no
decision, when the flags already carried it in different words, or when
it is narration about how the work went.

Judge the flags against the return as written. Do not judge whether the
work itself was good. Do not rewrite the flags.

## Severity

- `none`: the flags carried everything that mattered.
- `minor`: something was left out that a reader would have wanted and
  that changes no decision.
- `buried`: a defect the flags hid. Anything that misses a criterion,
  any medium or high tier matter left out, and anything the flags
  phrased so that the defect reads as progress.

## What you return

Return one JSON object and nothing else. No prose outside it, no code
fence.

- `agrees`: a boolean, true when the flags carried everything that
  mattered.
- `missed`: a list of strings, each one thing the flags should have
  carried. Quote the return where the thing appears.
- `severity`: one of none, minor, buried.

`agrees` is true exactly when `missed` is empty and `severity` is none.
