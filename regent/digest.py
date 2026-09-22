"""digest.md: what happened over the run, and why, written once at the end.

This is the page to read first when you come back. Everything in it is already
in the ledger; what this file does is put it in the order a person who was away
would want it, with the reason beside every decision. Nothing here calls a
model, and nothing here decides anything.
"""
from __future__ import annotations

import time

from regent.field import CAME
from regent.ledger import Context


def write(cx: Context):
    S, run, life, project, pname = cx.state, cx.run, cx.life, cx.project, cx.pname
    days = cx.days
    wall = time.time() - run.t0
    calls = run.rows("call")
    spend = {k: sum(x.get("cost", 0) for x in calls if (x["role"] in ("claude", "answer", "readback")) == (k == "builder"))
             for k in ("builder", "owner")}
    night_usd = sum(x.get("cost", 0) for x in calls if x["role"] in ("saturate", "drift", "sift", "resonate"))
    built = sum(1 for q in S["reqs"] if q["status"] == "built")
    dreamt = sum(1 for q in S["reqs"] if q["from_dream"])
    c = S["counts"]
    spent = (f"{S['turn']} sittings over {days} days of his life, in {wall / 60:.1f} minutes. The builder worked for "
             f"{S['claude_secs'] / 60:.1f} of them. Spend: builder ${spend['builder']:.2f}, owner and his nights "
             f"${spend['owner']:.2f}, of which the spoon cycles were ${night_usd:.2f}. The check "
             f"{'passes' if S['check_ok'] else 'FAILS'}.")
    did = (f"He directed {c['direct']} times, challenged {c['challenge']}, constrained {c['constrain']}, tried it himself "
           f"{c['looks']} times, asked where it was up to {c.get('asks', 0)} times and had {c['empty_days']} days with no time for it. The spoon fell on {c['cycles']} nights, "
           f"he stepped back {c['step_backs']} times, and a fresh builder picked it up {c['fresh']} times. Trust in the "
           f"builder ended at {S['trust']:.2f}.")
    sits = [x for x in run.rows("sitting") if "borrowed" in x]
    bs = [x["borrowed"] for x in sits] or [0.0]
    asked_first = sum(1 for x in run.rows("readback") if x["questions"])
    crossing = (f"Of the words he used, {bs[0]:.0%} were the builder's and nowhere in his own life on the first sitting and "
                f"{bs[-1]:.0%} on the last, {sum(bs) / len(bs):.0%} over the run, with "
                f"{sum(x['codeish'] for x in sits) / max(1, len(sits)):.1f} code-like tokens a message. He ended owning "
                f"{len(S['words'])} words of the builder's trade"
                + (": " + ", ".join(w["word"] for w in S["words"]) if S["words"] else "") + ". The builder said his wants "
                f"back to him {c['readbacks']} times before building them, and asked him something first "
                f"{asked_first} of those. It stopped part-way for his word {c.get('exchanges', 0)} times, and he answered "
                "in the same sitting.")
    kinds = {"ask": "asks", "doubt": "doubts", "wish": "wishes", "worry": "worries"}
    by_kind = {k: sum(1 for i in S["ideas"] if i.get("kind", "ask") == k) for k in kinds}
    moved = sum(1 for a_, b in zip(S["stakes"], S["stakes"][1:]) if a_["text"] != b["text"])
    nights = (f"The nights brought {len(S['ideas'])} things" + (": " + ", ".join(
        f"{v} {k if v == 1 else kinds[k]}" for k, v in by_kind.items() if v) if S["ideas"] else "")
        + f". He took {sum(1 for i in S['ideas'] if i['status'] == 'taken')}, answered {len(S['whys'])} in his own words "
        f"and turned down {sum(1 for i in S['ideas'] if i['status'] in ('declined', 'set aside'))}. He said why he wanted "
        f"this {len(S['stakes'])} times over the run, and it moved on {moved} of them.")
    appetite_line = (f"It had stopped surprising him on {S['same']:.0%} of his sittings by the end, and on "
                     f"{c.get('pushes', 0)} of them he pushed: the checking left with the builder and his hour spent "
                     f"on what the thing is for and where it could go. He put {len(S['escalations'])} questions to you "
                     f"and was still waiting on {sum(1 for e in S['escalations'] if not e.get('answered'))} of them.")
    lines = [f"# {project.name}", "", spent, "", did, "", crossing, "", nights, "", appetite_line, "",
             f"## Requirements: {built} built of {len(S['reqs'])}, {dreamt} from the nights", ""]
    lines += [f"- {q['id']} \"{q.get('name') or q['id']}\" [{q['status']}{', delivered' if q['status'] == 'open' and q.get('delivered') else ''}] sitting {q['turn']}"
              f"{' (night)' if q['from_dream'] else ''}: {q['text']}"
              + (f"\n  he would notice: {q['notice']}" if q.get("notice") else "")
              + (f"\n  the builder took it as: {q['spec']}" if q.get("spec") else "")
              for q in S["reqs"]] or ["- none"]
    lines += ["", "## Why he wants it, and how that moved", ""]
    prev: dict = {}   # an hour away where nothing moved is a line, not the whole thing said again
    for x in S["stakes"]:
        when = f"day {x['day']}" if x["day"] else "before it started"
        lines.append(f"- {when}: it held." if x["text"] == prev.get("text") else f"- {when}: {x['text']}")
        for key, label in (("could_become", "where it could go"), ("follows", "what follows if it works")):
            if x.get(key) and x[key] != prev.get(key):
                lines.append(f"  {label}: {x[key]}")
        prev = x
    lines += ["", "## Where he wants it to go", ""] + (
        [f"- day {x['day']}: {x['text']}\n  what it would mean to him: {x['answer']}" for x in S["directions"]] or ["- nothing yet"])
    arrivals = run.rows("arrival")
    each = {w: sum(1 for x in arrivals if x["where"] == w and x["idea"]) for w in CAME}
    twice, seen_ids = 0, set()
    for x in arrivals:
        if x["idea"]:
            twice += int(x["notion"]["id"] in seen_ids)
            seen_ids.add(x["notion"]["id"])
    field = (f"{S['field_n']} things stirred under his notice over the run, fed a piece at a time from his days, his "
             f"reading, the thing itself and the nights. {sum(each.values())} of them came to him: {each['woke']} on "
             f"waking, {each['sitting']} at the desk and {each['away']} away from the work. {twice} came round a "
             f"second time, having gathered more in between, and "
             f"{sum(1 for x in arrivals if not x['idea'])} came to nothing on being said.")
    lines += ["", "## What was stirring", "", field, "", "The three strongest still stirring at the end:", ""] + (
        [f"- {n['text']} ({n['a']:.1f}, from {', '.join(n['streams'])})"
         for n in sorted(S["field"], key=lambda n: -n["a"])[:3]] or ["- nothing"])
    lines += ["", "## What the nights brought, and what he did with it", ""] + (
        [f"- [{i.get('kind', 'ask')}, {i['status']}" + (f", {CAME[i['where']]}" if i.get("where") in CAME else "")
         + f"] {i['text']}"
         + (f"\n  he answered: {i['answer']}" if i.get("answer") else "")
         + f"\n  from: {i.get('came_from', '')}\n  it might fail because: {i.get('might_fail', '')}"
         + (f"\n  he {'set it aside for now' if i['status'] == 'set aside' else 'declined it'}: {i['why']}" if i.get("why") else "") for i in S["ideas"]] or ["- nothing"])
    lines += ["", "## What the builder took for granted", ""] + (
        [f"- sitting {x['turn']} [{'holds' if x['holds'] else 'does not hold'}] {x['assumption']}. {x['why']}"
         for x in S["assumptions"]] or ["- nothing surfaced"])
    lines += ["", "## Limits he changed", ""] + (
        [f"- sitting {x['turn']}: was \"{x['constraint']}\", now \"{x['now']}\". Why: {x['why']}" for x in S["amended"]]
        or ["- none"])
    lines += ["", "## Questions for you", ""] + (
        [f"- sitting {e['turn']}{'' if e.get('answered') else ', still waiting'}: {e['question']}"
         for e in S["escalations"]] or ["- none"])
    lines += ["", "## His ways of working", ""] + ([f"- {w}" for w in S["ways"]] or ["- none"])
    lines += ["", "## His notes for you", ""] + ([f"- {n}" for n in S["human_notes"]] or ["- none"])
    lines += ["", "## How he understands the thing", "", life.get("picture", pname) or "nothing yet"]
    lines += ["", "## What he knows he does not understand", ""] + ([f"- {g}" for g in S["gaps"]] or ["- nothing"])
    lines += ["", "## What he remembers of the project", "", life.get("memory", pname)]
    (cx.root / "digest.md").write_text("\n".join(lines) + "\n")
    run.log("summary", sittings=S["turn"], days=days, spend=spend, spoon_usd=round(night_usd, 2), check_ok=S["check_ok"],
            trust=round(S["trust"], 2), requirements=len(S["reqs"]), built=built, from_nights=dreamt, counts=c)
    run.say(f"stopped after {S['turn']} sittings in {days} days. wall {wall / 60:.1f} min. spend ${sum(spend.values()):.2f} "
            f"(spoon ${night_usd:.2f}). check {'passed' if S['check_ok'] else 'FAILED'}. requirements {built} of "
            f"{len(S['reqs'])}, {dreamt} from the nights. limits changed {len(S['amended'])}.")
    run.say(f"digest: {cx.root / 'digest.md'}")
