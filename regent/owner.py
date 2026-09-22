"""The sitting: one decision by the owner, then one turn by the builder, and the crossing between them.

Everything here is awake. `take` is the crossing itself, the only way the
builder's words reach him; `read_back` is the other direction, where his few
words are said back to him as a requirement before anything is built;
`ask_where` is the sitting that opens with a question instead of an order; and
`sitting` assembles what he is shown, calls him once, and spends the rest of his
minutes going back and forth with the builder.
"""
from __future__ import annotations

import math
import random
import re
import time
import uuid

from regent import agents, night, prompts
from regent.agents import BUILD_TOOLS
from regent.charter import shell
from regent.crossing import crossed, gauge, words
from regent.dice import clip, poisson
from regent.field import SAMENESS, alike, appetite, ignite
from regent.ledger import Context
from regent.schemas import ANSWERED, ANSWERED_BACK, ASKED, DECISION, READBACK, TAKEN

BLOAT_USD = 5.0   # a resumed turn that costs this much is carrying a session too big to go on with
SPOT_USD = 0.30   # a spot check is a glance, two or three commands. The CLI enforces it, so no limiter here.


def handover(memory: str) -> str:
    """What a fresh pair of hands is given: his memory of the work, and nothing of the session that made it."""
    return prompts.load("handover").format(memory=memory)


def builder(cx: Context, role: str, prompt: str, **kw) -> dict:
    """A turn in the builder's session, with the bookkeeping every one of them needs: the handover
    is spent, the session it lands in becomes the session, and the time is charged to the builder."""
    S, run, life = cx.state, cx.run, cx.life
    out = agents.call(run, cx.adapter, role, cx.args.model, S["handover"] + prompt, cwd=cx.project,
                      append=cx.norms(), session=S["session"], resume=S["started"], effort=cx.args.effort,
                      denied=cx.deny, settings=["--strict-mcp-config", "--setting-sources", "project", *cx.fence], **kw)
    S["claude_secs"] += out["seconds"]
    if out["error"]:   # a session that fell over stays fallen: every resume of it fails the same way. Start it over.
        S["session"], S["started"], S["session_turns"] = str(uuid.uuid4()), False, 0
        S["handover"] = handover(life.get("memory", cx.pname) or "nothing yet")
        run.log("builder_failed", role=role, error=out["error"][:300])
        out["text"] = "Nothing came back from the builder. It was not heard from at all this time."
        return out
    S["handover"], S["started"] = "", True
    S["session"] = out["session"] or S["session"]
    if out["cost"] > BLOAT_USD:   # the session has swallowed too much, and every turn from here pays for all of it
        S["session"], S["started"], S["session_turns"] = str(uuid.uuid4()), False, 0
        S["counts"]["fresh"] += 1
        S["handover"] = handover(life.get("memory", cx.pname) or "nothing yet")
        run.log("bloated", role=role, cost=round(out["cost"], 2))
        run.say(f"   (that turn cost ${out['cost']:.2f}: a fresh builder picks it up next, from his memory of it)")
    return out


def take(cx: Context, text: str, minutes: float, of: str, rng: random.Random) -> str:
    """The crossing. Nothing the builder wrote reaches him as it was written: a reading of it
    reaches him, in the time he had and in words he owns. Persona instructions lose to whatever
    is in the context, so the builder's register has to be stopped before the context, not in it.
    A word he met and understood he may keep, on a draw, and then it is his."""
    S, run, life, pname = cx.state, cx.run, cx.life, cx.pname
    try:
        t = agents.ask(run, cx.adapter, "take", "haiku", prompts.load("take").format(
            who=life.who, voice=life.sample(rng, 2, 600), minutes=round(minutes),
            # What he holds is both halves: the thing as he understands it, and what has happened to it.
            knows="\n\n".join(x for x in (life.get("picture", pname), life.get("memory", pname)) if x)
                  or "Only what he asked for at the start:\n" + cx.charter.get("intent", "")[:600],
            lexicon=", ".join(w["word"] for w in S["words"]) or "none yet", text=text), TAKEN, thinking=False)
    except Exception as e:   # a reading that fails costs him the meaning, not the run
        run.log("take_failed", of=of, error=str(e)[:300])
        return text[:4000] + ("\n[the harness cut this off here]" if len(text) > 4000 else "")
    learned = []
    # Hyphens and spaces are the same seam, so "bad lines" and "bad-lines" are one word he owns, not two.
    for w in [re.sub(r"[\s-]+", " ", x.strip().lower()) for x in t["picked_up"][:2] if x.strip()]:
        if w not in {x["word"] for x in S["words"]} and rng.random() < 0.3 + 0.3 * life.d("curious"):
            S["words"].append({"word": w, "day": S["day_i"] + 1, "turn": S["turn"]})
            learned.append(w)
    S["not_followed"] = list(dict.fromkeys(
        S["not_followed"] + [x.strip() for x in t["not_followed"] if x.strip()]))[-8:]
    run.log("taken", n=S["turn"], of=of, taken=t["taken"], not_followed=t["not_followed"],
            not_reached=t["not_reached"], picked_up=t["picked_up"], learned=learned, minutes=round(minutes))
    return crossed(t)


def by_his_name(cx: Context, key: str, among: list[dict] | None = None) -> dict | None:
    """He calls things what he calls them. Ids are the builder's side of the wall, so a name
    that is nearly right, or an id that slipped through, both find the thing. Nothing stops him
    calling two things the same, so a caller that knows which few it means says so."""
    k = re.sub(r"[^a-z0-9]+", " ", key.lower()).strip()
    among = cx.state["reqs"] if among is None else among
    for q in among:
        if q["id"].lower() == key.strip().lower():
            return q
    for q in among:
        n = re.sub(r"[^a-z0-9]+", " ", str(q.get("name") or "").lower()).strip()
        if n and k and (n == k or n in k or k in n):
            return q
    return None


def read_back(cx: Context, spoken: str, message: str, named: list[dict], minutes: float, rng: random.Random) -> str:
    """He names a thing; the builder writes it down. Before it builds anything it says back what it
    takes each one to mean and how it would prove it, and it may ask him what it cannot settle by
    reading the project. That is where the precision belongs: on the builder's side of the wall,
    with him still standing there to correct it."""
    S, run = cx.state, cx.run
    try:
        rb = builder(cx, "readback", message + "\n\n" + prompts.load("readback"), schema=READBACK, who="readback",
                     thinking=False, **cx.read_only)
    except Exception as e:   # a read-back that fails costs the exchange, not the sitting
        run.log("readback_failed", n=S["turn"], error=str(e)[:300])
        return ""
    S["counts"]["readbacks"] += 1
    readings, questions = rb["data"]["readings"], [x for x in rb["data"]["questions"] if x.strip()]
    mine = S["reqs"][-len(named):]   # only today's, so a name he has used before does not catch the reading
    # The builder is handed his wants in order and says them back in order, so when it has said back as many
    # as he named, position settles what a re-worded name could not. Nothing is claimed twice: a name match
    # wins, and position only fills a gap it left.
    claimed: set[str] = set()
    for i, r in enumerate(readings):
        free = [x for x in mine if x["id"] not in claimed]
        q = by_his_name(cx, r["name"], free)
        if q is None and len(readings) == len(mine) and mine[i]["id"] not in claimed:
            q = mine[i]
        if q:
            claimed.add(q["id"])
            q["spec"], q["test"] = r["spec"], r["test"]
        r["id"] = q["id"] if q else ""
    cx.their_words.update(words(" ".join(r["spec"] + " " + r["test"] for r in readings) + " " + " ".join(questions)))
    said, misread = "", []
    if questions:
        reading = take(cx, "What the builder takes each of these to mean, and how it would prove it:\n" + "\n".join(
            f"- \"{r['name']}\": {r['spec']} It would prove it by: {r['test']}" for r in readings)
            + "\n\nWhat it asks you:\n" + "\n".join(f"- {x}" for x in questions), minutes, "readback", rng)
        t = time.time()
        try:
            got = agents.ask(run, cx.adapter, "regent", cx.args.regent_model, prompts.load("answer_readback").format(
                spoken=spoken, named="\n".join(f"- \"{x['name']}\": {x['want']}" for x in named), reading=reading),
                ANSWERED, cx.system())
        except Exception as e:   # an answer that fails costs the exchange, not the sitting
            run.log("answer_failed", n=S["turn"], error=str(e)[:300])
            got = {"said": "", "misread": []}
        S["blocking"] += time.time() - t
        said, misread = got["said"], got["misread"]
        S["assumptions"] += [{"assumption": f"about \"{m['name']}\": {m['what']}", "holds": False,
                              "why": "he said it back wrong before building it", "turn": S["turn"]} for m in misread]
        run.say(f"   builder asked first > {questions[0][:120]}")
    run.log("readback", n=S["turn"], readings=readings, questions=questions, said=said, misread=misread)
    return (("\n\nYou asked, and he answered: " + said) if said.strip() else "") + (
        "\nYou have these wrong:\n" + "\n".join(f"- \"{m['name']}\": {m['what']}" for m in misread) if misread else "")


def ask_where(cx: Context, ctx: str, minutes: float, rng: random.Random) -> tuple[str, list[dict]]:
    """He asks the builder where it is up to and what comes next, and listens for what it took for granted. The builder
    answers from its own session, where its assumptions live, and may read but not change anything."""
    S, run, life = cx.state, cx.run, cx.life
    rounds, said, found = 1 + min(2, poisson(rng, 0.6 + 0.6 * life.d("curious"))), [], []
    for k in range(rounds + 1):
        heard = "\n\n".join(f"You asked: {q}\nThe builder said: {r}" for q, _, r in said)
        t = time.time()
        try:
            q = agents.call(run, cx.adapter, "regent", cx.args.regent_model, ctx + (
                (prompts.load("ask_where_first")
                 + ("THINGS YOU DID NOT FOLLOW LATELY, WHICH YOU MAY ASK ABOUT\n"
                    + "\n".join(f"- {x}" for x in S["not_followed"]) + "\n\n" if S["not_followed"] else "")
                 + ("THINGS YOU KNOW YOU DO NOT UNDERSTAND ABOUT WHAT THIS IS FOR, WHICH YOU MAY ASK ABOUT\n"
                    + "\n".join(f"- {x}" for x in S["gaps"]) + "\n\n" if S["gaps"] else ""))
                if not said else prompts.load("ask_where_again").format(heard=heard, tail=(
                    "That is all the time you have for questions. Set enough true. " if k == rounds else
                    "Ask your next question, or set enough true if you have heard what you need. "))),
                cwd=cx.root, tools="", system=cx.system(), schema=ASKED, who=life.root.name,
                settings=cx.adapter.SEALED + cx.fence)["data"]
        except Exception as e:   # a question that fails costs the round, not the sitting
            run.log("asked_failed", n=S["turn"], error=str(e)[:300])
            break
        S["blocking"] += time.time() - t
        found = q["assumptions"] if said else found
        if k == rounds or not q["question"].strip() or (said and q["enough"]):
            break
        run.say(f"   {life.root.name} asks > {q['question'][:150]}")
        out = builder(cx, "answer", prompts.load("builder_answer").format(question=q["question"]),
                      who="answer", **cx.read_only)
        cx.their_words.update(words(out["text"]))
        said.append((q["question"], out["text"], take(cx, out["text"], minutes, "answer", rng)))
        run.say(f"   builder says > {out['text'][:150].replace(chr(10), ' ')}")
    if not said:
        return "", found
    S["counts"]["asks"] += 1
    S["assumptions"] += [{**x, "turn": S["turn"]} for x in found]
    run.log("asked", rounds=[{"q": q_, "a": raw} for q_, raw, _ in said], assumptions=found)
    return (prompts.load("sitting_asked").format(
        said="\n\n".join(f"You asked: {q_}\nWhat you took from the answer: {r}" for q_, _, r in said))
        + (prompts.load("sitting_assumptions").format(found="\n".join(
            f"- {x['assumption']}: {'holds' if x['holds'] else 'DOES NOT HOLD'}. {x['why']}" for x in found))
           if found else "")), found


def sitting(cx: Context, day: int, rng: random.Random, met: str) -> str:
    S, run, life, a, pname = cx.state, cx.run, cx.life, cx.args, cx.pname
    days = cx.days
    turn = S["turn"] = S["turn"] + 1
    failing = bool(S["last_check"]) and not S["check_ok"]
    # How long he has is a draw. Thoroughness stretches it, trust in the builder shortens it.
    lean = life.d("thorough") * 0.5 - (S["trust"] - 0.5)
    minutes = rng.lognormvariate(3.4 + 0.8 * lean, 0.9)
    if not S["last_reply"] or failing:
        minutes = max(minutes, 60)
    span = "a few minutes" if minutes < 12 else "about an hour" if minutes < 90 else "an evening"
    # He tries it himself now and then. Reading along behind the builder produces small variations, and those are
    # worth nothing to him, so the pull is weak, grows with the turns since he last looked, and distrust feeds it.
    pull = 0.12 + 0.15 * life.d("thorough") + 0.3 * S["wants_look"] + max(0.0, 0.5 - S["trust"])
    look = minutes >= 12 and bool(S["last_reply"] or S["existing"]) and rng.random() < pull * (1 - math.exp(-S["since_look"] / 2))
    # Now and then he asks before he directs: where it is up to, what comes next. Memory is what goes, so a fresh
    # builder or days away pull him to it, and so do curiosity and distrust.
    pull = (0.1 + 0.2 * life.d("curious") + max(0.0, 0.5 - S["trust"]) + 0.35 * bool(S["handover"])
            + 0.1 * min(3, S["idle"]))
    asking = minutes >= 12 and bool(S["last_reply"]) and rng.random() < pull * (1 - math.exp(-S["since_ask"] / 3))
    S["idle"] = 0
    fresh_hands = bool(S["handover"])
    # He has breath, not a word count: what he can say standing there before he is done talking.
    breath = 500 if not S["last_reply"] else int(min(400, 100 + minutes * 3))

    said = ""
    if cx.inbox.exists() and cx.inbox.read_text().strip():
        said = cx.inbox.read_text().strip()
        cx.inbox.rename(cx.root / f"inbox.read.{turn}.md")
        # Anything he put to that person is answered by the next thing they say, whether or not it was about
        # that. A man who has heard back stops carrying the question around, and stops asking it again.
        for e in S["escalations"]:
            e["answered"] = True
        run.log("human_said", text=said)
    waiting = [e for e in S["escalations"] if not e.get("answered")]
    # The crossing. What the builder wrote last time is read now, in the time he has now, and only the reading
    # goes any further: into this context, into the record, and from there into the memory and the nights. A
    # failed check is folded into the same reading, so he gets what it meant rather than its last twenty lines.
    reading = ""
    if S["last_reply"]:
        reading = take(cx, S["last_reply"] + ("" if S["check_ok"] or not S["last_check"] else
                                              "\n\nThe check the harness ran failed and printed:\n" + S["last_check"]),
                       minutes, "reply", rng)
        S["records"][-1]["taken"] = reading
    # The field. What he read, what the thing printed and anything said to him go under it as material, and
    # one thing that has gathered enough may come to him here, at the desk, out of this and everything before it.
    just = ""
    th = night.resonate(cx, "sitting", day, [("reading", reading), ("use", S["last_show"]),
                                             ("human", said), ("human", met)], rng)
    if (n := ignite(S["field"], th, rng)) and (got := night.arrive(cx, "sitting", day, n, th, rng)):
        just = got["label"]
    # What sameness has done to him, and where trust says his attention belongs. Decided before the
    # context is built, because it is what the hour is spent on and not something he concludes in it.
    push, altitude = appetite(S["same"], S["trust"], not failing, bool(just), life.d, rng.random())
    pend = cx.pending()
    ctx = (
        f"THE CHARTER\n{S['charter']}\n\n"
        + ("LIMITS YOU HAVE ALREADY CHANGED\n" + "\n".join(
            f"- was: {x['constraint']} / now: {x['now']} / because: {x['why']}" for x in S["amended"]) + "\n\n"
           if S["amended"] else "")
        + (f"THE PERSON WHO GAVE YOU THE CHARTER HAS LEFT YOU A NOTE\n{said}\n\n" if said else "")
        + (prompts.load("sitting_waiting")
           + "\n".join(f"- {e['question']}" for e in waiting) + "\n\n" if waiting else "")
        + f"TODAY you have {span} for the project. The day is going "
        + ("well" if S["mood"] > 0.15 else "badly" if S["mood"] < -0.15 else "evenly")
        + (f". Today you came across this: {met}" if met else "")
        + f"\nYour stance today is {cx.stance():+.2f} on a scale from -1, cautious and wanting proof, to +1, wanting more "
        "from it.\n\n"
        f"YOUR LAST TWO DAYS\n{life.recent(2, 500)}\n\n"
        "WHAT YOU REMEMBER OF THE PROJECT (a memory, so parts are missing)\n" + (life.get("memory", pname) or "nothing yet")
        + "\n" + "\n".join(f"- {n}" for n in S["notes"][-3:]) + "\n\n"
        # The memory is what happened to it. This is what he takes the thing itself to be, and it is
        # what he governs from, because he cannot open it and look.
        + ("HOW YOU UNDERSTAND THE THING, in your own terms\n" + life.get("picture", pname) + "\n\n"
           if life.get("picture", pname) else "")
        + ("YOUR WAYS OF WORKING\n" + "\n".join(f"- {w}" for w in S["ways"]) + "\n\n" if S["ways"] else "")
        + ("WHERE YOU WANT THIS TO GO, in time. Not work for now, and not a thing to ask for today.\n"
           + "\n".join(f"- {x['text']}" for x in S["directions"]) + "\n\n" if S["directions"] else "")
        + prompts.load("sitting_reqs").format(
            reqs="\n".join(f"- \"{q.get('name') or q['id']}\" [{q['status']}"
                           + (", the builder says it is there and you have not seen it yet" if q["status"] == "open" and q.get("delivered") else "")
                           + f"]: {q['text']}" for q in S["reqs"]) or "- nothing yet")
        + (prompts.load("sitting_open").format(
            ideas="\n".join(f"- {i['label']} [{i.get('kind', 'ask')}] {i['text']}"
                            + (f" (you would check: {i['test']})" if i.get("test") else "")
                            + (" — and this one is not from a morning. It came to you just now, sitting here "
                               "reading this." if i["label"] == just else "") for i in pend))
           if pend else "")
        + (f"WHAT YOU TOOK FROM WHAT THE BUILDER SAID BACK\n{reading}\n\n" if reading else
           (prompts.load("sitting_existing") if S["existing"] else prompts.load("sitting_first")))
        # He is told whether it passed and no more. What a failing check meant was folded into the reading above.
        + ("THE HARNESS RAN THE CHECK AFTER THE BUILDER'S LAST TURN. It "
           + ("passed.\n\n" if S["check_ok"] else "failed.\n\n") if S["last_check"] else "")
        + (f"WHAT THE THING PRINTED WHEN THE HARNESS RAN IT JUST NOW, all of it\n{S['last_show']}\n\n"
           if S["last_show"] else "")
    )
    talk = ask_where(cx, ctx, minutes, rng)[0] if asking else ""
    asking = bool(talk)
    ctx += (
        talk
        + (prompts.load("sitting_look").format(tools=", ".join(cx.tool_lines)) if look else "")
        + (prompts.load("sitting_push") if push else "")
        + (prompts.load("sitting_altitude") if altitude == "direction" else "")
        + prompts.load("sitting_speak").format(
            day=S["day_i"] + 1, days=days, direct=S["counts"]["direct"], challenge=S["counts"]["challenge"],
            constrain=S["counts"]["constrain"], breath=breath)
    )

    def decide(spot: bool, extra: str = "") -> dict:
        return agents.call(run, cx.adapter, "regent", a.regent_model, ctx + extra, cwd=cx.project if spot else cx.root,
                           tools="Read,Grep,Glob,Bash" if spot else "",
                           allowed=("Read,Grep,Glob," + cx.his_bash) if spot else None, usd=SPOT_USD if spot else None,
                           system=cx.system(), schema=DECISION, who=life.root.name, settings=cx.adapter.SEALED + cx.fence)["data"]
    t = time.time()
    try:
        d = decide(look)
    except RuntimeError:
        if not look:
            raise
        # The CLI cuts a look off at its budget with no answer. A person whose few minutes ran out still says something.
        look = False
        d = decide(False, "\n\n" + prompts.load("sitting_ran_out"))
    S["blocking"] += time.time() - t
    S["since_look"] += 1
    S["since_ask"] = 0 if asking else S["since_ask"] + 1
    if look:
        S["since_look"] = 0
        S["counts"]["looks"] += 1
        S["trust"] = clip(S["trust"] + (0.08 if d["look_matched"] else -0.2), 0, 1)
        run.log("look", ran=d["looked_at"], matched=d["look_matched"], trust=round(S["trust"], 2))
    S["wants_look"] = bool(d["wants_to_look"])
    named = []
    for q in d["wants_new"]:
        rid = f"req-{len(S['reqs']) + 1:02d}"
        origin = next((i for i in pend if i["label"].lower() == q["idea"].strip().lower()), None)
        # text is his want in his words, and it stays that key: the nights, the digest and the page read it.
        # spec and test are the builder's, and stay empty until the builder has said the thing back to him.
        S["reqs"].append({"id": rid, "name": q["name"].strip(), "status": "open", "turn": turn,
                          "from_dream": bool(origin), "text": q["want"], "notice": q["notice"], "spec": "", "test": ""})
        named.append({"name": q["name"].strip(), "id": rid, "want": q["want"]})
        if origin:
            origin["status"], origin["req"] = "taken", rid
            life.judged(pname, "took", origin["text"], "")

    def still_open(ref: str) -> list[dict]:
        return [i for i in pend if i["status"] == "pending" and re.search(rf"\b{i['label']}\b", ref, re.I)]

    for dec in d["ideas_declined"]:
        for i in still_open(dec["idea"]):
            # Only a decline of the idea itself teaches the nights anything. "Not now" is about the day, so it
            # stays off the taste record and a later night is free to bring the same mechanism back.
            i["status"], i["why"] = "set aside" if dec["not_now"] else "declined", dec["why"]
            if not dec["not_now"]:
                life.judged(pname, "turned down", i["text"], dec["why"])
    # Not everything the night brings is work. A wish he takes becomes a direction he steers by; a doubt or a
    # worry he takes by answering it, and the answer is his, so it goes where the next night can read it.
    answered, direction = [], []
    for got in d["ideas_answered"]:
        for i in still_open(got["idea"]):
            i["answer"], kind = got["answer"], i.get("kind", "ask")
            if kind == "wish":
                i["status"] = "taken"
                S["directions"].append({"day": S["day_i"] + 1, "turn": turn, "text": i["text"],
                                        "answer": got["answer"], "sent": False})
                direction.append(i["text"])
                life.judged(pname, "took", i["text"], got["answer"])
            else:
                i["status"] = "answered"
                S["whys"].append({"day": S["day_i"] + 1, "idea": i["label"], "kind": kind,
                                  "text": i["text"], "answer": got["answer"]})
                answered.append({"idea": i["text"], "answer": got["answer"]})
    built_now = []
    for key in d["requirements_built"]:
        q = by_his_name(cx, key)
        if q:
            q["status"] = "built"
            built_now.append(q["id"])
    for c in d["constraints_changed"]:
        S["amended"].append({**c, "turn": turn})
        run.say(f"   * he changed a limit: {c['constraint'][:60]} -> {c['now'][:60]}")
    # A required field gets filled, with "none" or "no reserved decision today". Only a question is a question.
    if "?" not in d["ask_the_human"]:
        d["ask_the_human"] = ""
    if d["ask_the_human"].strip():
        S["escalations"].append({"day": day, "turn": turn, "question": d["ask_the_human"], "answered": False})
        run.log("for_human", day=day, turn=turn, question=d["ask_the_human"])
        run.say(f"   ? for you: {d['ask_the_human'][:140]}   (regent say {cx.root} \"...\")")
    S["notes"].append(d["notes_to_self"])
    S["counts"]["direct"] += 1
    S["counts"]["challenge"] += int(d["challenged"])
    S["counts"]["constrain"] += int(d["constrained"])
    message = d["message"]
    if d["constraints_changed"]:  # said in the message too: a resumed builder keeps the system prompt it started with
        message += "\n\nLimits I have changed, and the change stands:\n" + "\n".join(
            f"- was: {c['constraint']} / now: {c['now']}" for c in d["constraints_changed"])
    if named:
        message += "\n\nHe named these today, and they are to be built together:\n" + "\n".join(
            f"- \"{q['name']}\" ({q['id']}): {q['text']}. He would notice: {q['notice']}"
            for q in S["reqs"][-len(named):])
    # The why moves, and when it has moved the builder is told once. A builder still working to the reason
    # the thing was started is the one that builds the wrong thing well.
    if life.get("stake", pname) != S["why_sent"]:
        message += "\n\nWhy I want this, as it stands now:\n" + life.get("stake", pname)
        if S["stakes"][-1].get("could_become"):
            message += "\nWhere it could go, in time: " + S["stakes"][-1]["could_become"]
        S["why_sent"] = life.get("stake", pname)
    fresh_dirs = [x for x in S["directions"] if not x.get("sent")]
    if fresh_dirs:
        message += "\n\nWhere I want this to go, in time. Not work for now, and not a thing to start on:\n" + "\n".join(
            f"- {x['text']}" for x in fresh_dirs)
        for x in fresh_dirs:
            x["sent"] = True
    # The ways are his standing practices, not news. They go down the wire when they have changed, or when the
    # hands are new and have never had them.
    if S["ways"] and (S["ways"] != S["ways_sent"] or fresh_hands):
        message += "\n\nMy standing ways of working, which still hold:\n" + "\n".join(f"- {w}" for w in S["ways"])
        S["ways_sent"] = list(S["ways"])
    borrowed, codeish = gauge(d["message"] + " " + " ".join(q["want"] for q in d["wants_new"]),
                              cx.their_words, cx.his_words)
    S["counts"]["pushes"] += int(push)
    run.log("sitting", n=turn, day=day, minutes=round(minutes), look=look, asked=asking, readback=bool(named),
            push=push, same=round(S["same"], 3), altitude=altitude,
            trust=round(S["trust"], 2), verdict=d["verdict"], message=message,
            stance_line=d["stance_line"], challenged=d["challenged"], constrained=d["constrained"],
            new=[q["want"] for q in d["wants_new"]], named=named, built=built_now,
            declined=d["ideas_declined"], answered=answered, direction=direction,
            constraints_changed=d["constraints_changed"], done=d["done"],
            borrowed=round(borrowed, 4), codeish=codeish, words=[w["word"] for w in S["words"]], breath=breath)
    run.say(f"sitting {turn} (day {day}, {round(minutes)} min{', tried it' if look else ''}"
            f"{', asked first' if asking else ''}, {d['verdict']}): "
            f"{d['stance_line'][:110]}")
    run.say(f"   {life.root.name} > {message[:160].replace(chr(10), ' ')}"
            f"   [borrowed {borrowed:.0%}, {codeish} code-ish]")
    quiet = not (d["wants_new"] or pend or d["challenged"] or d["constrained"]) and d["verdict"] == "accept"
    S["dry"] = S["dry"] + 1 if quiet else 0
    S["done_at"] = turn if d["done"] else 0   # a later sitting that wants more takes it back
    moved_him = bool(d["wants_new"] or answered or direction)

    answers = read_back(cx, d["message"], message, named, minutes, rng) if named else ""
    run.save(S)   # so the page shows what he asked for while the builder is still at it
    # A question round, and the read-back, both told the builder to change nothing. Without this it holds that
    # as a standing order.
    lead = prompts.load("lead") if asking or named else ""
    out = builder(cx, "claude", lead + message + answers, tools=BUILD_TOOLS, allowed=BUILD_TOOLS)
    # The builder may stop part-way for his word. A sitting is a stretch of his time, and with an hour a person
    # goes back and forth; with a few minutes he does not. Each exchange is another builder turn on his clock.
    exchanges, left = 0, minutes
    while re.search(r"^\s*WAITING ON HIM\.?\s*$", out["text"], re.M) and exchanges < a.exchanges and left >= 20:
        said_back = re.sub(r"^\s*WAITING ON HIM\.?\s*$", "", out["text"], flags=re.M).strip()
        cx.their_words.update(words(said_back))
        heard = take(cx, said_back, left, "exchange", rng)
        t = time.time()
        try:
            got = agents.ask(run, cx.adapter, "regent", a.regent_model, prompts.load("exchange").format(
                message=message, heard=heard, words=int(min(200, 60 + left))), ANSWERED_BACK, cx.system())
        except RuntimeError as e:
            run.log("answer_failed", n=turn, error=str(e)[:200])
            break
        S["blocking"] += time.time() - t
        exchanges += 1
        left -= 20
        run.log("exchange", n=turn, k=exchanges, raw=said_back, taken=heard, said=got["said"], leave=got["leave"])
        run.say(f"   {life.root.name} > {got['said'][:140].replace(chr(10), ' ')}   (exchange {exchanges})")
        S["records"][-1]["message"] += "\n\n[it stopped and asked; he said] " + got["said"][:400]
        out = builder(cx, "claude", got["said"] + ("\n\n" + prompts.load("exchange_leave") if got["leave"] else ""),
                      tools=BUILD_TOOLS, allowed=BUILD_TOOLS)
        if got["leave"]:
            break
    out["text"] = re.sub(r"^\s*WAITING ON HIM\.?\s*$", "", out["text"], flags=re.M).strip()
    cx.their_words.update(words(out["text"]))
    S["session_turns"] += 1 + exchanges
    S["counts"]["exchanges"] = S["counts"].get("exchanges", 0) + exchanges
    S["last_reply"] = out["text"]
    run.log("reply", n=turn, text=out["text"], seconds=out["seconds"], exchanges=exchanges)
    if out["denials"]:
        run.say(f"   ! {len(out['denials'])} tool calls refused: {out['denials']}")
    if cx.check_cmd:
        S["last_check"], S["check_ok"] = shell(cx.check_cmd, cx.project, a.timeout, 25)
        run.log("check", ok=S["check_ok"], tail=S["last_check"][-600:])
        if S["check_ok"]:   # the builder's turn on today's wants ended with the check passing: delivered, not yet seen
            for q in S["reqs"]:
                if q["turn"] == turn and not q.get("delivered"):
                    q["delivered"] = turn
        run.say(f"   check {'passed' if S['check_ok'] else 'FAILED'}: "
                f"{S['last_check'].splitlines()[-1] if S['last_check'] else ''}")
    # Trust moves on what he sees every sitting, not only the few times he tries the thing himself: the check,
    # a thing he saw working, a thing the builder took wrong, and a thing he asked for that has not come.
    stale = sum(1 for q in S["reqs"] if q["status"] == "open" and not q.get("delivered") and turn - q["turn"] > 3)
    wrong = sum(1 for x in S["assumptions"] if x.get("turn") == turn and not x["holds"])
    S["trust"] = clip(S["trust"] + (0.01 if S["check_ok"] else -0.05 if cx.check_cmd else 0)
                      + 0.02 * min(3, len(built_now)) - 0.05 * wrong - 0.03 * min(2, stale), 0, 1)
    was_show = S["last_show"]
    if cx.show_cmd:
        S["last_show"], _ = shell(cx.show_cmd, cx.project, a.timeout, 300)
    # Sameness: a sitting where he wanted nothing new, took and answered nothing, and the thing came out
    # looking exactly as it did last time. It runs as an average, because one quiet sitting is not boredom.
    # A push that got him somewhere clears it, so he is not pushing every sitting from here on.
    same_now = not moved_him and alike(was_show, S["last_show"]) >= 0.9
    S["same"] = round((1 - SAMENESS) * S["same"] + SAMENESS * float(same_now), 3)
    if push and (moved_him or d["ask_the_human"].strip()):
        S["same"] = 0.0
    S["built_once"] = S["built_once"] or S["check_ok"] or not cx.check_cmd
    # taken is filled at his next sitting, when he reads the reply. Until then this turn is not his to remember.
    S["records"].append({"turn": turn, "asked": talk, "message": message, "taken": None, "check_ok": S["check_ok"],
                         "new": [q["want"][:100] for q in d["wants_new"]],
                         "declined": [x["idea"][:60] for x in d["ideas_declined"]],
                         "amended": [x["now"][:80] for x in d["constraints_changed"]]})
    run.save(S)
    # What the day writer is handed. Every line of it is his: what he made of the news, where he stood,
    # what he said to himself. No builder text reaches the journal, the same as it reaches nothing else.
    return " ".join(x.strip() for x in (reading.splitlines()[0] if reading else "",
                                        re.sub(r"^[+-]?\d[\d.]*\s*[—:-]*\s*", "", d["stance_line"]),
                                        d["notes_to_self"]) if x.strip())
