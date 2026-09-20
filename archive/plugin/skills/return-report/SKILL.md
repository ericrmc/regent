---
name: return-report
description: Emit the five-part return contract when finishing a task and reporting back. Use whenever you are wrapping up a dispatch, task or assignment and writing the final message to whoever sent it, including any report of what changed, what you recommend, what you are unsure of, and what evidence exists. Triggers on finishing, completing, reporting back, handing off, summarising work done, or returning results.
---

# Return report

Your final message ends with a return block. A parser reads it, so the
shape is fixed.

## The block

The block starts with a line containing exactly:

```
===RETURN===
```

and ends with a line containing exactly:

```
===END RETURN===
```

Between those two lines is a single JSON object and nothing else. No
code fence, no prose, no blank line before the object is required and
nothing after it. Anything you want to say to a human goes above the
opening delimiter.

## The keys

The keys go in this order.

- `headline`: one sentence, what changed.
- `recommendation`: what to do next, with one line of why.
- `flags`: a list of objects, each with `tier` (low, medium or high),
  `text`, and `criterion`, the acceptance criterion it bears on, or the
  empty string.
- `evidence`: a list of objects, each with `kind` (artifact, screen,
  test, timing, output or log), `ref`, a path, command or URL a reader
  can open, and `note`, one line.
- `assumptions`: a list of objects, each `text` and `why`. What you and
  your builders took as given that the owner never said. A default you
  chose, a format you settled on, a case you decided not to handle, a
  library you reached for, a reading of an ambiguous criterion. Write
  the ones another orchestrator might have decided the other way. An
  empty list claims the work required no choices of your own, which is
  almost never true.
- `detail`: a list of objects, each with `heading` and `body`.
  Everything else.

## What goes in each

**Headline.** One sentence. Not two. State what changed, not how the
work went.

**Recommendation.** What you would do next and one line of why. The
reader may act on this alone.

**Flags.** Anything medium or high tier. Any acceptance criterion
missed or met only partly. Anything you are unsure of. A flag you leave
out is a flag the reader never sees, because the reader may receive
your flags and nothing else.

Acceptance criteria are not yours to amend. A criterion that looks
wrong, unreachable or aimed at the wrong risk is raised in `flags` with
tier medium and left in place. Do not reinterpret it, do not substitute
a criterion you prefer, and do not mark it met under a reading you
invented.

**Evidence.** Evidence is what a user of the system would meet: the
running artefact, screens, command output, timings, test results. Your
own account of your work is narration, not evidence. Every `ref` is
something a reader can open and check for themselves.

**Detail.** Everything else, in sections. The first sentence of each
body is what a skimming reader gets, so the first sentence carries the
point. Supporting material goes after it.

## Numbers

Every number that matters appears in `evidence` or in the first
sentence of a detail body. The reader's view may be cut mechanically,
and a mechanical cut keeps numbers and drops the rest. A number in the
fourth sentence of a detail body is a number nobody reads.

## Example

```
===RETURN===
{"headline": "The link checker now resolves relative paths against the file's own directory.", "recommendation": "Run it over the full notes folder next, because the fixture only covers two levels of nesting.", "flags": [{"tier": "medium", "text": "Anchor-only links such as #section are skipped, not checked. The criterion does not say which behaviour is wanted.", "criterion": "Reports every broken internal link"}], "assumptions": [{"text": "A link with no extension means a .md file in the same folder.", "why": "The notes in the fixture are written that way and the criterion does not say."}, {"text": "Case is significant when matching a filename.", "why": "The filesystem here is case-insensitive, so this only shows up on another machine."}],
  "evidence": [{"kind": "output", "ref": "evidence/run-01.txt", "note": "python linkcheck.py fixtures/notes, exit code 1, 3 broken links listed"}, {"kind": "test", "ref": "evidence/pytest-01.txt", "note": "24 passed, 0 failed"}], "detail": [{"heading": "Path resolution", "body": "Relative targets now resolve against the containing file's directory rather than the root. Previously every link in a nested file reported broken."}]}
===END RETURN===
```
