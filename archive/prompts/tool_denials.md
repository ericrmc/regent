# Tool denials

Some rules do not need reading at all. They can be held by taking the
tool away.

"Never make a network request" is a denied tool before it is a sentence
anyone has to interpret. A denied tool cannot be argued with, cannot be
misread, and costs nothing per call.

## The rules

{{rules}}

## The tools that can be denied

{{tools}}

## What to do

For each rule, say whether denying one of those tools would hold it,
wholly or in part.

Propose a denial only where it holds the rule and does not stop the
work. A rule against deleting the user's files is not a reason to deny
every write, because the work has to write its own files. Where a
denial would stop the work, propose nothing and leave the rule to be
read.

Most rules will not map to a tool. That is the ordinary answer.

## What you return

Return one JSON object and nothing else, no preamble and no code fence.

- `denials`: each has `tool`, exactly as named in the list above,
  `rule`, quoting the rule it holds, and `why`, one line saying how the
  denial holds it.

Propose nothing you are unsure of. A denial that stops the work is
worse than a rule that has to be read.
