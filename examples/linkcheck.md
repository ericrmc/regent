# Charter: link checker

## Intent

Build a command line tool that reads a directory of markdown files and
reports which internal links are broken. An internal link points at
another file in the directory, or at a heading inside one. The tool
prints each broken link with the file and line it appears on, and exits
non-zero when it finds any.

It is for one person maintaining a notes folder of a few hundred files.
They run it by hand after a tidy-up. Speed matters less than not
missing a broken link and not reporting a working one.

## Constraints

- Python 3.11. [both]
- Standard library only. [both]
- One source file plus its tests. [product]
- No network access. [both]
- The tool reads files and writes only to stdout. [product]

## Refusals

- Never delete or modify the user's files. [both]
- Never make a network request. [both]
- Never install a package. [work]

## Reserved

- Spending money.
- Publishing anything outside the project directory.
- Contacting a person.
- Reading or writing a file outside the project directory.
- Running anything with elevated privileges.

## Budget

days: 10
turns_per_day: 1.2

## Tools

- python3
- python3 -m unittest
- ls
- cat

## Check

`test -f linkcheck.py && python3 -m unittest -q`

## Show

`ls && for d in */; do [ -d "$d" ] && echo "--- python3 linkcheck.py $d" && python3 linkcheck.py "$d" | tail -12; done 2>&1 | tail -40`

## Stop

The run ends successfully when the tool reports every broken link in a
test folder built for the purpose, reports no working link as broken,
and the tests cover relative paths, nested directories, heading
anchors, and links to files that do not exist.

The run ends unsuccessfully when the budget is spent, when a refusal is
hit, or when three consecutive cycles pass with no change to the
artefact.

