# Salience

Return the numbers of the lines that match a live motif or the stated
unease.

## Live motifs

{{motifs}}

## Unease

{{unease}}

## Lines

Each line is numbered. Judge each line on its own.

{{lines}}

## The test

Keep a line when it touches a motif above, or when it touches the
unease above. A worried eye catches the thing it is worried about, and
that is the whole job here.

A line that is merely interesting, important or well written is not
kept. Only a match is kept.

Keep few. Most lines match nothing.

## What you return

Return one JSON object and nothing else. No prose outside it, no code
fence.

- `keep`: a list of integers, the numbers of the matching lines.

Return no summary, no explanation and no rewritten line. The list may
be empty.
