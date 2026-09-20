"""Seed material for day fragments and foreign reading.

Day fragments are seeded from random draws over this corpus, or every day is a
rainy morning with coffee. The harness makes the draw and the model only writes
the sentences.
"""

from __future__ import annotations

SCENES = [
    "a bus that arrives eleven minutes late",
    "a hardware shop with three people ahead in the queue",
    "a public pool at six in the morning",
    "a kitchen where the extractor fan has stopped working",
    "a train platform in heavy rain",
    "a second-hand bookshop with no order to the shelves",
    "a laundrette at closing time",
    "a hospital waiting room with a broken vending machine",
    "a market stall packing up in the wind",
    "a car park where the ticket machine takes coins only",
    "a school sports day that runs over",
    "a ferry terminal with a delayed sailing",
    "a garden after a hard frost",
    "a barber shop where the radio is too loud",
    "a hotel corridor at two in the morning",
    "a fishing pier at low tide",
    "a village hall set up for a meeting nobody attends",
    "a supermarket the night before a public holiday",
    "a bicycle repair on a verge",
    "a borrowed flat with unfamiliar light switches",
    "a bakery that sells out by nine",
    "a bird hide in fog",
    "a swimming carnival with a faulty timing board",
    "an airport gate change announced twice",
    "a locksmith working on a jammed door",
    "a museum room being rehung",
    "a printing shop with one machine down",
    "a tram stop where the display shows nothing",
    "a beach with a rip marked by red flags",
    "a community garden after a week of rain",
]

WORDS = [
    "hinge", "gravel", "queue", "steam", "ledger", "socket", "kerb", "drawer",
    "ferry", "thermos", "rivet", "awning", "clamp", "sediment", "beacon",
    "rota", "pallet", "gutter", "slipway", "flask", "spool", "batten",
    "tarpaulin", "brine", "ratchet", "trestle", "lantern", "bollard", "sieve",
    "scaffold", "cairn", "furrow", "latch", "gasket", "pulley", "tide",
    "bracket", "shutter", "grate", "wheelbarrow", "compost", "moth", "starling",
    "kestrel", "chalk", "sandbag", "stanchion", "mooring", "lintel", "flint",
    "copper", "tannin", "yeast", "resin", "bramble", "frost", "ballast",
    "capstan", "pennant", "abrasive", "shim", "detent", "cam", "spline",
]

MOODS = [
    ("flat", -0.4), ("restless", -0.2), ("patient", 0.1), ("irritated", -0.6),
    ("curious", 0.5), ("tired", -0.5), ("light", 0.6), ("watchful", 0.0),
    ("stubborn", -0.1), ("generous", 0.4), ("blunt", -0.3), ("easy", 0.5),
]

# Foreign reading pulls material from an unrelated domain. Each entry is a
# domain and one mechanism from it, stated plainly so a link can carry the
# mechanism rather than the image.
FOREIGN = [
    ("marine navigation", "A ship under way gives way to a ship constrained by draught, because manoeuvrability and not right of way decides who can act."),
    ("beekeeping", "A colony that loses its queen raises several replacements at once and kills the surplus, spending on redundancy before it knows which one works."),
    ("bridge inspection", "An inspector taps the steel and listens, because a dull note means a void that no visual check would show."),
    ("wine making", "Malolactic fermentation is allowed or blocked deliberately, because the softer acid is a choice and not a stage."),
    ("commercial fishing", "Quota is set by biomass estimate and landed catch is weighed against it, so the measurement and the limit are separate instruments."),
    ("orchestral rehearsal", "The conductor rehearses the transitions and not the passages, because the passages are already learnt and the joins are not."),
    ("cave rescue", "The first team in lays a line, so everyone after moves at speed on a route already proved."),
    ("timber framing", "A drawbore pin pulls the joint tight as it is driven, so the fastening and the clamping are one action."),
    ("air traffic control", "Separation is maintained in three dimensions and one of them is time, which is the cheapest to spend."),
    ("cheese ageing", "The rind is washed on a schedule, because the surface culture is the control surface for what happens inside."),
    ("railway signalling", "A block is occupied or clear, and the system prefers a false occupied over a false clear every time."),
    ("glassblowing", "The piece is reheated constantly, because the working window is short and reopening it costs less than losing the piece."),
    ("hydrology", "A catchment's response is measured as lag between rainfall and peak flow, which tells you about the ground and not the rain."),
    ("printmaking", "The proof is pulled before the edition, and the plate is corrected between them, because the edition has to be identical."),
    ("falconry", "The bird is flown at a weight, and the weight is the control, because a bird that is not hungry does not return."),
    ("bookbinding", "The grain of the paper runs parallel to the spine, or the book fights itself every time it opens."),
    ("avalanche forecasting", "A weak layer is buried and remembered, so the hazard is a history and not a condition."),
    ("brewing", "The mash temperature picks which enzyme works, so one number chooses the body of the finished beer."),
    ("surveying", "A traverse is closed back onto its start, and the misclosure is the error budget made visible."),
    ("anaesthesia", "Depth is titrated against response and not against dose, because the dose that works varies by a factor of three."),
]


def draw_day_seed(rng, word_count: int = 6) -> dict:
    scene = rng.choice(SCENES)
    words = rng.sample(WORDS, word_count)
    mood, valence = rng.choice(MOODS)
    return {"scene": scene, "words": words, "mood": mood, "valence": valence}


def draw_foreign(rng) -> dict:
    domain, mechanism = rng.choice(FOREIGN)
    return {"domain": domain, "text": f"{domain}: {mechanism}"}
