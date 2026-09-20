---
name: evidence-capture
description: Record the running artefact as evidence a reader can open and check. Use while building or verifying anything that will be reported back, whenever you run a command, start a server, open a page, run tests, or measure performance, and whenever you are about to claim that something works. Triggers on capturing output, saving test results, taking a screenshot, timing a run, or proving a change.
---

# Evidence capture

Your reader cannot read the source. They judge the artefact by what it
does. Your account of your own work is narration. Evidence is something
a reader can open and check.

Run the thing. Capture its real output. Save each capture to a file
under the directory the caller names. Reference each file by path in
the return's `evidence` list.

Never edit a capture. A trimmed log is not evidence. Where output is
long, save it whole and say in the note which line matters.

## A command line tool

Record the exact command, its verbatim stdout and stderr, and its exit
code.

```
{ echo "$ python linkcheck.py fixtures/notes"; python linkcheck.py fixtures/notes 2>&1; echo "exit: $?"; } > evidence/run-01.txt
```

The command in the file must be the command that ran, including every
flag and path.

## A web page

Save a screenshot and record the URL that produced it. Both go in the
evidence entry: the screenshot path as `ref`, the URL in the note, with
the state the page was in. A screenshot with no URL cannot be
reproduced.

## Tests

Record the runner command, the pass and fail counts as numbers, and the
verbatim text of every failure.

```
pytest -q > evidence/pytest-01.txt 2>&1; echo "exit: $?" >> evidence/pytest-01.txt
```

"Tests pass" is narration. "24 passed, 0 failed" is evidence. A skipped
test is not a passing test and the count says so separately.

## Performance

Record the measurement, how it was measured and how many runs. One run
is an anecdote. State the number, the tool, the run count and the
machine's state.

```
for i in 1 2 3 4 5; do /usr/bin/time -p python linkcheck.py fixtures/notes; done > evidence/timing-01.txt 2>&1
```

Report the median and the spread, not the best run.

## The check before reporting

For each claim you are about to make, name the file that shows it. A
claim with no file behind it is either removed or moved into `flags` as
something you are unsure of.
