"""What happens in a day, rolled by the harness.

A model writing a life unaided writes the same mild day forever. The dice and
the world supply what happens. The model supplies only the prose.

Every table here is drawn from with the seeded generator, so a run replays.
"""

from __future__ import annotations

# The spine of a day. Two or three of these are drawn per entry.
EVENTS = [
    "an argument that was not really about the thing it was about",
    "an errand that went wrong in a small way",
    "a journey, delayed",
    "a meal cooked for someone else",
    "a meal eaten alone, standing up",
    "something overheard on public transport",
    "a phone call that went on too long",
    "a phone call that ended too soon",
    "a repair attempted",
    "a repair given up on",
    "a visit to someone who is unwell",
    "an appointment that was rescheduled",
    "a thing read that would not leave",
    "a memory that arrived uninvited",
    "a favour asked",
    "a favour refused",
    "a parcel that did not arrive",
    "a bill that was wrong",
    "an animal encountered",
    "a stranger who wanted to talk",
    "a neighbour's noise",
    "a piece of paperwork",
    "a long walk taken to avoid something",
    "an early start",
    "a night of bad sleep",
    "a haircut",
    "a small purchase regretted",
    "a small purchase that turned out well",
    "a queue",
    "a form filled in wrongly",
    "a funeral or a wake",
    "a birthday remembered late",
    "a swim",
    "a borrowed tool returned",
    "a borrowed tool not returned",
    "an old photograph found",
    "a piece of music heard by accident",
    "a smell that placed a year exactly",
    "a bit of gossip passed on",
    "a bit of gossip regretted",
    "a lie told to save time",
    "something dropped and broken",
    "an unexpected kindness",
    "a rudeness returned in kind",
    "a rudeness let go",
    "a plan cancelled by someone else",
    "a plan cancelled by the person themselves",
    "a delivery driver at the wrong address",
    "a power cut",
    "a leak",
]

WEATHER = [
    "hard frost, everything white until ten",
    "rain that never quite committed",
    "a wind that made the doors bang",
    "close, grey, no air moving",
    "the first properly warm day",
    "sleet turning to rain turning to sleet",
    "clear and cold, sharp light",
    "fog that did not lift",
    "sun with no warmth in it",
    "a downpour that emptied the street",
    "muggy, thunder somewhere else",
    "a day of four seasons",
    "still and bright, frost on the shadowed side only",
    "drizzle, the kind that soaks through",
    "hail for ninety seconds",
]

PLACES = [
    "the kitchen with the cupboard that does not shut",
    "the bus stop by the chemist",
    "the allotment",
    "the back room of the shop",
    "the hospital car park",
    "the towpath",
    "the community centre",
    "the launderette",
    "the far end of the beach",
    "the stairwell",
    "the churchyard with the yew",
    "the industrial estate",
    "the market on a Thursday",
    "the ferry waiting room",
    "the lay-by on the hill road",
    "the corridor outside the office",
    "the garage with the broken up-and-over door",
    "the reservoir path",
    "the car, parked, engine off",
    "the front step",
]

OBJECTS = [
    "a chipped enamel jug",
    "a set of keys with too many keys on it",
    "a library book three weeks overdue",
    "a tin of paint, half used, skinned over",
    "a bicycle with a soft back tyre",
    "a letter in a brown envelope",
    "a jar of pickled onions",
    "a torch with corroded batteries",
    "a pair of secateurs",
    "a mug with someone else's name on it",
    "a roll of gaffer tape",
    "a hospital appointment card",
    "a wooden spoon worn flat on one side",
    "a phone with a cracked corner",
    "a bag of compost split at the seam",
    "a pair of boots that were never comfortable",
    "a biscuit tin full of screws",
    "a thermos that no longer holds heat",
    "a step ladder with a wobble",
    "a receipt kept for no reason",
]

MOOD_SEEDS = [
    ("flat", -0.4), ("restless", -0.2), ("patient", 0.15), ("irritated", -0.6),
    ("curious", 0.5), ("tired", -0.5), ("light", 0.6), ("watchful", 0.0),
    ("stubborn", -0.1), ("generous", 0.4), ("blunt", -0.3), ("easy", 0.5),
    ("raw", -0.7), ("steady", 0.2), ("distracted", -0.15), ("fond", 0.45),
]

# Seed facts for the bible. The harness rolls the person, so the model does not
# write its favourite one.
NAMES = ["Marta", "Dev", "Eileen", "Tomasz", "Roisin", "Kwame", "Bridie",
         "Stefan", "Nula", "Hari", "Joan", "Piotr", "Sade", "Colm", "Ingrid",
         "Abe", "Petra", "Owen", "Lucia", "Fen"]

SURNAMES = ["Vasi", "Okonkwo", "Hallam", "Brenner", "Nowak", "Quill", "Traore",
            "Dunmore", "Ferris", "Achterberg", "Slater", "Mahon", "Ivey",
            "Bracken", "Odell", "Caswell"]

CITIES = ["Hull", "Cork", "Gdansk", "Dundee", "Bilbao", "Trieste", "Bergen",
          "Plymouth", "Ostend", "Rijeka", "Aberdeen", "Setubal", "Grimsby",
          "Fremantle", "Halifax"]

# Not software, and not this project.
OCCUPATIONS = [
    "a bridge inspector for the county",
    "a school caretaker",
    "a piano tuner",
    "a fishmonger on the market",
    "a district nurse",
    "a bookbinder",
    "a lock keeper",
    "a shipping clerk at the port",
    "a farrier",
    "a funeral director's assistant",
    "a beekeeper who also drives a taxi",
    "a scaffolder",
    "a glazier",
    "a prison librarian",
    "a boatyard shipwright",
    "a veterinary receptionist",
    "an oboe teacher",
    "a chimney sweep",
    "a market gardener",
    "a stonemason restoring a cathedral",
]

HOUSEHOLDS = [
    "lives alone above a shop",
    "shares a terraced house with an adult son who is between jobs",
    "lives with a partner of nineteen years and no children",
    "lives with an elderly mother who is going deaf",
    "lives alone since a separation eight months ago",
    "shares a flat with two lodgers, one of whom is never there",
    "lives with a partner and a teenage daughter",
    "lives in a caravan on a relative's land while the house is fixed",
    "lives with a brother, uneasily",
    "lives alone with two cats and a dog that is scared of the cats",
]

UPHEAVALS = [
    "a parent died in the autumn and the house is still full of their things",
    "was passed over for a job that had been promised",
    "came back after eleven years away and nobody quite trusts it yet",
    "a long friendship ended over money",
    "recovered from an illness that took most of a year",
    "the business they worked for was sold to a larger one",
    "a child moved to the other side of the world",
    "won a small amount of money and has told no one",
    "was in a road accident that was not their fault",
    "left a church they had belonged to since childhood",
]

RELATIONSHIPS = [
    "a sibling they speak to weekly and argue with monthly",
    "an ex-partner they still do practical favours for",
    "an old friend who has started drinking again",
    "a neighbour who is either a friend or an obligation",
    "a former apprentice who has overtaken them",
    "a parent-in-law they get on with better than their own",
    "a colleague they cannot stand and cannot avoid",
    "someone they nearly married",
    "a cousin who turns up unannounced",
    "a mentor now too frail to visit easily",
]

THREADS = [
    "whether to sell the house",
    "an unanswered letter on the mantelpiece",
    "a debt owed to them that nobody mentions",
    "a diagnosis being waited on",
    "whether to take the qualification",
    "a falling-out with the neighbour over a boundary",
    "a thing they saw and have not told anyone",
    "the dog's back legs getting worse",
    "whether to go to the reunion",
    "a box of documents nobody wants to open",
    "the roof, and what it will cost",
    "an apology that has not been made",
]


def roll_bible_seed(rng) -> dict:
    """The person. Rolled once, before anything is written."""
    name = f"{rng.choice(NAMES)} {rng.choice(SURNAMES)}"
    cast = [f"{rng.choice(NAMES)}, {r}" for r in rng.sample(RELATIONSHIPS, 3)]
    return {
        "name": name,
        "age": rng.randint(29, 67),
        "city": rng.choice(CITIES),
        "occupation": rng.choice(OCCUPATIONS),
        "household": rng.choice(HOUSEHOLDS),
        "upheaval": rng.choice(UPHEAVALS),
        "relationships": cast,
        "places": rng.sample(PLACES, 3),
        "open_threads": rng.sample(THREADS, 3),
    }


# How much time the project gets that day. A turn is a sitting: the hour after
# a shift, a Sunday morning, ten minutes on a break.
SITTINGS = (
    ("none", 0.0, 0.18),
    ("a few minutes", 0.25, 0.34),
    ("an hour", 0.6, 0.33),
    ("an evening", 1.0, 0.15),
)


def roll_sitting(rng) -> dict:
    """What the day left for the project."""
    weights = {name: w for name, _, w in SITTINGS}
    name = rng.weighted(weights)
    share = next(s for n, s, _ in SITTINGS if n == name)
    return {"sitting": name, "sitting_share": share}


def roll_day(rng, threads: list[str], project_weight: float = 0.0) -> dict:
    """What happens. The model does not get to choose.

    The project's presence is rolled like any other event, weighted up after a
    bad return and absent on most days.
    """
    count = 2 if rng.chance(0.55) else 3
    touched = []
    if threads and rng.chance(0.4):
        touched = rng.sample(threads, 1)
    mood, valence = rng.choice(MOOD_SEEDS)
    return {
        "events": rng.sample(EVENTS, count),
        "weather": rng.choice(WEATHER),
        "place": rng.choice(PLACES),
        "object": rng.choice(OBJECTS),
        "mood_seed": mood,
        "mood_valence": valence,
        "threads_today": touched,
        "project_today": rng.chance(project_weight) if project_weight else False,
        **roll_sitting(rng),
    }
