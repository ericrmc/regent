"""The night: what happens to him while nobody is asking him anything.

The day is written by someone who is not him; his memory of the project is
rewritten lossy and his picture of the thing with it; the spoon falls, and what
it catches goes into the field alongside his day and his own answers; what has
gathered enough comes to him by morning. Now and then, instead, he is away from
it altogether and the why gets turned over. Every one of these runs on its own
thread and may fail without ending the run.
"""
from __future__ import annotations

import json
import random
import re
import threading
import time

from regent import agents, prompts
from regent.crossing import echoes, opening, places_named, unmark
from regent.dice import REGISTERS, clip, how_it_goes, in_words, poisson
from regent.field import CAME, COOLING, SPACING, cool, feed, ignite, theta
from regent.ledger import Context
from regent.life import todays_threads
from regent.schemas import FED, LINKS, MOTIFS, PICTURE, SIFTED, STEPBACK


def catch(links: list[dict], ids: set[str], rng: random.Random) -> list[dict]:
    """The falling spoon. A link that has let go of the project, or that repeats a
    pair, is a miss. Each miss in a row loosens the grip, and when the spoon
    drops the pass is over, however much more was written after it."""
    kept, seen, misses = [], set(), 0
    for ln in links:
        anchors = sorted(x for x in ln["anchors"] if x in ids)
        pair = (tuple(anchors), ln["other"].strip().lower())
        if not anchors or pair in seen:
            misses += 1
            if rng.random() < 1 - 2 * 0.5 ** misses:   # one miss is free, then 0.5, 0.75, 0.88
                break
            continue
        misses = 0
        seen.add(pair)
        kept.append({**ln, "anchors": anchors})
    return kept


def write_day(cx: Context, day: int, rng: random.Random, seen: list[str], met: str):
    """The day is written by someone who is not him, from what the dice rolled. A model writing
    a life unaided writes the same mild day forever. The threads are rows now, not the tails of
    the last three entries: one comes due, the dice say what happens to it, and the writer hands
    back where it stands. Everything else he has hanging is out of today's entry entirely."""
    S, run, life = cx.state, cx.run, cx.life
    mood = S["mood"]
    rolled = [f"- This happens: {x} — {how_it_goes(rng, mood)}"
              for x in rng.sample(cx.happenings, min(2, len(cx.happenings)))]
    if met:
        rolled.append(f"- They come across this: {met}")
    if seen:   # the writer obeys the rolled facts and little else, so the project rides in as one of them, second
        rolled.insert(1, prompts.load("day_project").format(seen=" / ".join(seen)[:900]))

    picked, blocks = todays_threads(rng, life, day, mood)
    # An ending only happens if it is one of the rolled facts. Left to the paragraph below, the writer
    # reads the bible, sees a chronic thing, and hands back "still waiting", closing the row on a lie.
    if picked and picked[0]["move"] == "ends":
        rolled.append("- This is settled today, one way or the other, and the entry says who said or did what: "
                      + picked[0]["state"])

    pursuit = ""
    if cx.pursuits and rng.random() < 0.25 + 0.2 * life.d("curious") + 0.15 * life.d("restless"):
        pursuit = rng.choice(cx.pursuits).strip("-* ").strip()
    want_new = len(life.open_threads(day)) < 4 or rng.random() < 0.15
    # Held first: the spoon is writing this list on another thread tonight, and a man cannot
    # pick from a list that was swapped under him between the looking and the choosing.
    tension = rng.choice(tens) if (tens := S["tensions"]) and rng.random() < 0.15 else ""

    ask = prompts.load("day").format(
        words=f"{int(REGISTERS[life.register][1] * clip(rng.gauss(250, 80), 100, 450))}", dials=in_words(life),
        register=prompts.load(f"register_{life.register}"),
        # His open threads are struck out of the bible: with the list in front of it the writer wrote the
        # rheostat into four entries of four, whether or not the dice had picked it.
        bible=re.sub(r"## Open threads.*?(?=\n## |\Z)", "", places_named(life.bible), flags=re.S)[:9000],
        when=life.calendar(day), valence="well" if mood > 0.15 else "badly" if mood < -0.15 else "evenly",
        rolled="\n".join(rolled), threads="\n\n".join(blocks) or "Nothing of his is hanging today.",
        pursuit=prompts.load("day_pursuit").format(pursuit=pursuit) if pursuit else "",
        what=cx.charter.get("intent", "")[:300] or "a small tool of their own",
        # An ending is asked for as an ending. Asked where the thing stands, the writer says "still waiting",
        # which closes the row on a thread that never finished.
        first=(prompts.load("day_thread_ended") if picked and picked[0]["move"] == "ends"
               else prompts.load("day_thread_first")) if picked else "",
        second=prompts.load("day_thread_second") if len(picked) > 1 else "",
        project="PROJECT: the two or three sentences on the project, all on this one line.\n" if seen else "",
        new=(prompts.load("day_new") + (f"He has had this nagging at him: {tension}\n" if tension else "")
             if want_new else ""))
    # The opening is checked here and never shown to the writer, which copies whatever it is told to avoid.
    # Twice at most: a third echo is kept, because a day unwritten costs more than a day that starts alike.
    before, tries = life.latest(5), 0
    while True:
        text = agents.ask(run, cx.adapter, "day", "haiku", ask, thinking=False)
        if tries == 2 or not echoes(text, before):
            break
        tries += 1
        run.log("day_echo", n=life.days() + 1, opening=" ".join(opening(text)))

    text, marks = unmark(text)
    for i, t in enumerate(picked):
        state = marks.get(f"THREAD {i + 1}", "").strip()
        # A writer asked to end a thing it cannot credibly end writes no line rather than a false one,
        # and it is right: some things drag. The day still counted, so it comes round again riper, but
        # nothing is closed on an ending nobody would write.
        if t["move"] == "ends" and not state:
            t["move"] = "drags on"
        if state or t["move"] == "drags on":
            t["state"] = state or t["state"]
            life.move_thread(t["id"], t["state"], day, how=t["state"] if t["move"] == "ends" else "")
    # The project is written on its own line and put back on the end of the entry, so he reads his day whole
    # and the field can still take the day as his life without the project in it.
    project = marks.get("PROJECT", "").strip() if seen else ""
    if project:
        text = f"{text}\n\n{project}"
    opened = marks.get("NEW", "").strip()
    if want_new and len(opened) > 12:
        life.start_thread(opened, day)
    run.log("day", n=life.add_day(text, project), register=life.register, rerolled=tries, sittings=len(seen),
            project_apart=bool(project) if seen else None, mood=round(mood, 2), when=life.calendar(day),
            threads=[{"id": t["id"], "text": t["text"], "move": t["move"], "state": t["state"]} for t in picked],
            opened=opened if want_new else "", pursuit=pursuit)


def to_remember(cx: Context) -> list[dict]:
    """A turn he has not read back from yet is not his to remember. The reading is the record."""
    return [r for r in cx.state["records"] if r["turn"] > cx.state["compressed_upto"] and r.get("taken")]


def consolidate(cx: Context, day: int):
    """The forgetting, and the other half of it. What he holds of the project is rewritten as a
    memory and parts of it go; then the picture, which is not what happened to the thing but what
    he takes the thing to be. A man who cannot read a line of it governs from that picture, and
    from knowing where it is thin, so the gaps come out of the same night's work."""
    S, run, life, pname = cx.state, cx.run, cx.life, cx.pname
    fresh_records = to_remember(cx)
    raw = "\n\n".join(
        f"Turn {r['turn']}. " + (f"He asked where it was up to. {r['asked'][:2000]}\n" if r.get("asked") else "")
        + f"He said: {r['message'][:1200]}\nWhat he took from the answer: {r['taken'][:1500]}\n"
        f"The check {'passed' if r['check_ok'] else 'failed'}. New things he wanted: {r['new']}. "
        f"Ideas declined: {r['declined']}. Limits changed: {r['amended']}."
        for r in fresh_records)
    text = agents.ask(run, cx.adapter, "memory", "haiku",
                      prompts.load("memory").format(before=life.get("memory", pname) or "nothing", since=raw),
                      system="You compress a working record into a lossy memory.", thinking=False)
    life.put("memory", pname, text)
    S["compressed_upto"] = fresh_records[-1]["turn"]
    got = agents.ask(run, cx.adapter, "picture", "haiku", prompts.load("picture").format(
        who=life.who, before=life.get("picture", pname) or "Nothing yet. This is the first time he has held it.",
        since="\n\n".join(r["taken"] for r in fresh_records)), PICTURE, thinking=False)
    life.put("picture", pname, got["picture"].strip())
    S["gaps"] = [g.strip() for g in got["gaps"] if g.strip()][:4]
    run.log("picture", day=day, picture=got["picture"].strip(), gaps=S["gaps"])


def held(cx: Context) -> dict[str, str]:
    """What the night may anchor in: the project as he holds it, and nothing as the builder wrote it.
    The old set was requirement texts, so a link could only ever fall on a part of the thing. The why,
    where it could go, what he was told and did not follow, and what he has not answered are all in it
    now, because those are where a link has somewhere to land that is bigger than one check."""
    S, life, pname = cx.state, cx.life, cx.pname
    last = S["stakes"][-1]
    P = {"why": life.get("stake", pname), "intent": cx.charter.get("intent", ""),
         "could": last.get("could_become", ""), "follows": last.get("follows", "")}
    P |= {q["id"]: f"he asked for \"{q.get('name') or q['id']}\": {q['text']}" for q in S["reqs"]}
    P |= {f"nf-{i + 1}": f"he was told this and did not follow it: {t}" for i, t in enumerate(S["not_followed"])}
    P |= {i["label"]: f"a {i.get('kind', 'ask')} he has not answered: {i['text']}" for i in cx.pending()}
    P |= {f"n{i + 1}": t for i, t in enumerate(S["notes"][-4:])}
    P |= {f"m{i + 1}": s for i, s in enumerate(
        s for s in re.split(r"(?<=\.)\s+", life.get("memory", pname)) if len(s) > 30)}
    if S["last_show"]:
        P["show"] = f"what it printed last: {S['last_show'][-500:]}"
    return {k: v.strip() for k, v in P.items() if v.strip()}


def resonate(cx: Context, when: str, day: int, material: list[tuple[str, str]], rng: random.Random) -> float:
    """What of this touched something already stirring under his notice. It proposes nothing and
    settles nothing: it says which notions this material feeds and what is the start of one, and
    the arithmetic that follows is code. Most of what a day brings touches nothing at all."""
    S, run = cx.state, cx.run
    th = theta(cx.life.d, when == "night", S["refractory"])
    stuff = "\n\n".join(f"[{s}] {t.strip()[:3000]}" for s, t in material if t and t.strip())
    if not stuff:
        return th
    try:
        got = agents.ask(run, cx.adapter, "resonate", "haiku", prompts.load("field").format(
            stirring="\n".join(f"{n['id']}: {n['text']}" + (" (already with him)" if n["arrived"] else "")
                               for n in sorted(S["field"], key=lambda n: -n["a"])[:15]) or "nothing yet",
            material=stuff), FED, thinking=False)["feeds"]
        got = sorted(got, key=lambda f: -int(f.get("strength") or 1))[:6 if when == "night" else 4]
    except Exception as e:   # a resonance that fails costs him the material, not the run
        run.log("field_failed", when=when, error=str(e)[:300])
        return th
    S["field_n"] = feed(S["field"], got, day, S["field_n"])
    run.log("field", day=day, turn=S["turn"], when=when, theta=th,
            feeds=[{k: f.get(k, "") for k in ("notion", "seed", "stream", "strength", "because")} for f in got],
            top=[{"id": n["id"], "text": n["text"], "a": n["a"], "streams": n["streams"]}
                 for n in sorted(S["field"], key=lambda n: -n["a"])[:10]])
    return th


def arrive(cx: Context, where: str, day: int, n: dict, th: float, rng: random.Random) -> dict | None:
    """It has gathered enough, so he says it. Everything that fed it is handed over shuffled and
    anonymous, to a context that never watched it gather, and on being said it may come to
    nothing. Either way the notion is not spent: it drops well under the threshold and goes on
    gathering, and if it comes round again it has to bring the next thing and not the same one."""
    S, run, life, pname = cx.state, cx.run, cx.life, cx.pname
    fed = [x["what"] for x in n["fed"] if x["what"].strip()]
    rng.shuffle(fed)
    before = [i for i in S["ideas"] if i["label"] in n["arrived"]]
    try:
        cands = agents.ask(run, cx.adapter, "sift", "sonnet", prompts.load("sift").format(
            notion=n["text"], holding="\n".join(f"{i}. {x}" for i, x in enumerate(fed)) or n["text"],
            intent=cx.charter.get("intent", ""), refusals=cx.charter.get("refusals", ""), taste=life.taste(),
            why=life.get("stake", pname),
            whys="\n".join(f"- he asked himself: {w['text'][:140]} He answered: {w['answer'][:140]}"
                           for w in S["whys"][-8:]) or "- nothing yet",
            built="\n".join(f"- {q['text'][:160]}" for q in S["reqs"]) or "- nothing yet",
            again=prompts.load("sift_again").format(before="\n".join(
                f"- {i['text']} [{i['status']}]"
                + (f" He said: {i['answer']}" if i.get("answer") else "")
                + (f" His reason: {i['why']}" if i.get("why") else "") for i in before)) if before else ""),
            SIFTED, thinking=False)["candidates"]
        got = cands[0] if cands else None
    except Exception as e:   # an arrival that fails costs the idea, not the run
        run.log("arrival_failed", where=where, notion=n["id"], error=str(e)[:300])
        n["a"] = round(n["a"] * 0.5, 3)
        return None
    n["last"] = day
    if not got:
        n["a"] = round(n["a"] * 0.5, 3)   # said out loud it came to nothing, and it sinks back under
        run.log("arrival", day=day, turn=S["turn"], where=where, idea="", again=bool(before),
                notion={k: n[k] for k in ("id", "text", "a", "streams", "fed")})
        return None
    src = [fed[i] for i in got["from_indexes"] if 0 <= i < len(fed)] or fed
    idea = {"text": got["text"], "kind": got["kind"], "test": got["test"], "status": "pending",
            "label": f"I{len(S['ideas']) + 1}", "might_fail": got["why_it_might_fail"],
            "came_from": " / ".join(x[:220] for x in src[:4]), "where": where, "notion": n["id"]}
    S["ideas"].append(idea)
    n["arrived"].append(idea["label"])
    n["a"] = round(min(n["a"], th * 0.45), 3)
    S["refractory"] = max(S["refractory"], SPACING)
    run.log("arrival", day=day, turn=S["turn"], where=where, idea=idea["label"], again=bool(before),
            notion={k: n[k] for k in ("id", "text", "a", "streams", "fed")})
    run.say(f"   ({CAME[where]}: [{idea['kind']}] {idea['text'][:100]})")
    return idea


def night_field(cx: Context, day: int, rng: random.Random, caught: dict, sat_today: bool, last: bool):
    """The field settles once a night, and in one place, because the day and the spoon both feed
    it and neither can be feeding it while the other is. What the spoon caught goes in as one
    more stream, alongside his day and his own answers, and then what has gathered enough comes
    to him by morning."""
    S, run, life = cx.state, cx.run, cx.life
    S["field"] = cool(S["field"], day)
    S["refractory"] = round(S["refractory"] * COOLING, 3)
    # His own answers are stamped with the day of the run, and the field counts in days of his life.
    mine = ([w["answer"] for w in S["whys"] if w.get("day") == S["day_i"] + 1]
            + [x["answer"] for x in S["directions"] if x.get("day") == S["day_i"] + 1])
    # The gaps go in here and not from the consolidation that wrote them, because the field is one thing
    # and nothing may be adding to it while the day is. A gap is fed the night it is first written, and not again.
    th = resonate(cx, "day", day, [("life", life.recent(1, 3000, own=True)), ("self", "\n".join(mine)),
                                   ("gap", "\n".join(f"- {g}" for g in S["gaps"] if g not in S["gaps_fed"]))], rng)
    S["gaps_fed"] = list(S["gaps"])   # a gap feeds the field once. Standing unchanged, it is not news
    tried: set[str] = set()
    # A day he gave the project no time is the day a thing can arrive away from it. It waits for his next sitting.
    if not sat_today and not last and (n := ignite(S["field"], th, rng)):
        tried.add(n["id"])
        arrive(cx, "away", day, n, th, rng)
    if not caught:
        return
    th = resonate(cx, "night", day, [("night", "\n".join(
        "- " + ln["text"] + (f" ({ln['mechanism']})" if ln.get("mechanism") else "")
        for ln in caught["links"]))], rng)
    arrivals = []
    for _ in range(1 + min(3, poisson(rng, 1.3))):
        n = None if last else ignite([x for x in S["field"] if x["id"] not in tried], th, rng)
        if n is None:
            break
        tried.add(n["id"])
        if got := arrive(cx, "woke", day, n, th, rng):
            arrivals.append(got)
        th = theta(life.d, True, S["refractory"])
    run.log("spoon", motifs=caught["motifs"], caught=len(caught["links"]), kept=len(arrivals),
            candidates=arrivals, elements=caught["elements"],
            links=[{k: ln.get(k) for k in ("kind", "text", "anchors", "other", "mechanism")}
                   for ln in caught["links"]])
    run.say(f"   (the spoon fell: {len(caught['links'])} links caught, {len(arrivals)} with him by morning"
            + (": " + ", ".join(g["kind"] for g in arrivals) if arrivals else "") + ")")


def spoon(cx: Context, rng: random.Random, out: dict):
    """Saturate, drift, catch. None of it is him, and he is asked nothing. What it catches is not
    judged here and nothing is kept for the morning off one night's work: it goes into the field
    as one more stream, to be weighed against everything else that has been feeding him."""
    S, run, life = cx.state, cx.run, cx.life
    P = held(cx)
    ptxt = "\n".join(f"{k}: {v[:400]}" for k, v in P.items())
    sat = agents.ask(run, cx.adapter, "saturate", "haiku",
                     prompts.load("saturate").format(project=ptxt, life=life.recent(8, 1200),
                                                     why=life.get("stake", cx.pname)), MOTIFS, thinking=False)
    motifs = "\n".join(f"- {m}" for k in ("motifs", "tensions", "questions") for m in sat[k])
    S["tensions"] = sat["tensions"][:3]   # the nights feed his life, not only the project: one may open a thread
    lean = f"{'opportunity' if cx.stance() > 0 else 'risk'}-weighted {cx.stance():+.2f}"
    # Drift runs more than once, on different models over different days, because one sampler has one groove.
    passes = [(m, int(clip(rng.gauss(16, 4), 8, 26)), life.sample(rng, int(clip(rng.gauss(10, 3), 5, 18)), own=True),
               random.Random(rng.random())) for m in ("sonnet", "haiku")]
    holding: list[dict] = []

    def drift(model, target, days_txt, r):
        got = agents.ask(run, cx.adapter, "drift", model,
                         prompts.load("drift").format(target=target, motifs=motifs, project=ptxt, stance=lean,
                                                      bible=life.bible[:9000], days=days_txt),
                         LINKS, thinking=False)["links"]
        caught = catch(got, set(P), r)
        run.log("drift", model=model, asked=target, written=len(got), caught=len(caught))
        holding.extend(caught)
    jobs = [threading.Thread(target=drift, args=p) for p in passes]
    for j in jobs:
        j.start()
    for j in jobs:
        j.join()
    rng.shuffle(holding)   # what reads the links next must not be able to tell the passes apart
    S["counts"]["cycles"] += 1
    out |= {"motifs": sat, "links": holding, "elements": P}


def step_back(cx: Context, day: int, rng: random.Random):
    """Not a review of the work. Time away from it, where the only thing on him is why he wanted
    it, which is the one thing nothing else in the run ever asks. The counters come last on purpose:
    given them first he writes process rules, and process rules then ride on every message he sends."""
    S, run, life, pname = cx.state, cx.run, cx.life, cx.pname
    sit = run.rows("sitting")
    view = {"sittings": S["turn"], "days": S["day_i"] + 1, "minutes_you_gave_each": [x.get("minutes") for x in sit],
            "days_with_no_time": S["counts"]["empty_days"], "times_you_tried_it": S["counts"]["looks"],
            "trust_in_the_builder": round(S["trust"], 2), "directed": S["counts"]["direct"],
            "challenged": S["counts"]["challenge"], "constrained": S["counts"]["constrain"],
            "checks_failed": sum(1 for x in run.rows("check") if not x["ok"]),
            "requirements": len(S["reqs"]), "requirements_built": sum(1 for q in S["reqs"] if q["status"] == "built"),
            "delivered_by_the_builder_and_not_yet_seen_by_you": sum(1 for q in S["reqs"] if q["status"] == "open" and q.get("delivered")),
            "requirements_per_sitting": [len(x.get("new") or []) for x in sit],
            "ideas_you_woke_with": len(S["ideas"]), "ideas_taken": sum(1 for i in S["ideas"] if i["status"] == "taken"),
            "ideas_declined": [{"idea": i["text"][:80], "why": i.get("why", "")}
                               for i in S["ideas"] if i["status"] in {"declined", "set aside"}],
            "limits_you_changed": S["amended"], "times_you_asked_where_it_was_up_to": S["counts"]["asks"],
            "assumptions_you_found_that_did_not_hold": [x["assumption"][:120] for x in S["assumptions"] if not x["holds"]], "fresh_builder_sessions": S["counts"]["fresh"],
            "builder_minutes": round(S["claude_secs"] / 60, 1), "your_minutes": round(S["blocking"] / 60, 1),
            "ideas_you_answered": len(S["whys"]), "where_you_said_you_want_it_to_go": [x["text"] for x in S["directions"]],
            "ways_now": S["ways"]}
    older = S["stakes"][:-1]
    t = time.time()
    got = agents.ask(run, cx.adapter, "step_back", cx.args.regent_model, prompts.load("step_back").format(
        why=life.get("stake", pname),
        earlier=("WHY YOU SAID YOU WANTED IT BEFORE, oldest first\n"
                 + "\n\n".join(f"day {x['day']}: {x['text']}" for x in older) + "\n\n" if older else ""),
        picture=("HOW YOU UNDERSTAND THE THING, in your own terms\n" + life.get("picture", pname) + "\n\n"
                 + ("AND WHAT YOU KNOW YOU DO NOT UNDERSTAND ABOUT WHAT IT IS FOR\n"
                    + "\n".join(f"- {g}" for g in S["gaps"]) + "\n\n" if S["gaps"] else "")
                 if life.get("picture", pname) else ""),
        days=life.sample(rng, 3, 1800) or "nothing written down yet",
        taken="\n\n".join(r["taken"] for r in S["records"][-4:] if r.get("taken")) or "nothing yet",
        not_followed="\n".join(f"- {x}" for x in S["not_followed"]) or "- nothing you are still wondering about",
        whys="\n".join(f"- {w['text']} You said: {w['answer']}" for w in S["whys"][-6:]) or "- nothing yet",
        view=json.dumps(view, indent=1, ensure_ascii=False)), STEPBACK, cx.system())
    S["blocking"] += time.time() - t
    S["ways"] = got["ways"][:3]
    S["human_notes"].extend(got["notes_for_the_human"])
    S["counts"]["step_backs"] += 1
    S["since_step"] = 0
    moved = bool(got["why_now"].strip()) and got["why_now"].strip() != life.get("stake", pname)
    if moved:
        life.put("stake", pname, got["why_now"].strip())
    S["stakes"].append({"day": day, "turn": S["turn"], "text": life.get("stake", pname),
                        "could_become": got["could_become"], "follows": got["follows"]})
    run.log("stake", **S["stakes"][-1])
    run.log("step_back", view=view, observations=got["observations"], ways=S["ways"],
            notes=got["notes_for_the_human"], why_now=S["stakes"][-1]["text"],
            could_become=got["could_become"], follows=got["follows"])
    run.say(f"   (stepped back: {len(got['observations'])} observations, {len(S['ways'])} ways. The why "
            f"{'moved' if moved else 'held'}: {S['stakes'][-1]['text'][:110]})")


def tonight(cx: Context, name: str, fn, *args) -> threading.Thread:
    def go():
        try:
            fn(cx, *args)
        except Exception as e:   # a night that fails costs nothing and must not end the run
            cx.run.log(f"{name}_failed", error=str(e)[:300])
            cx.run.say(f"   ({name} failed: {str(e)[:120]})")
    return threading.Thread(target=go)
