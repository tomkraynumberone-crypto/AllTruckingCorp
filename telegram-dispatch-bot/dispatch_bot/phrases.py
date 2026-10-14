"""Words and phrases the bot recognises.

This is the file to edit if your drivers use words the bot does not understand yet.
Everything is lower-case. Add a new word inside quotes, separated by a comma.
(Apostrophes are normalised, so "bo'shman" also matches "bo‘shman".)
"""

# The driver is EMPTY / ready to take a load.
AVAILABLE_WORDS = [
    "available", "avail", "avl", "empty",
    "i'm open", "im open", "i am open", "open for load", "open for a load",
    "i'm free", "im free", "i am free",
    # Turkish / Uzbek
    "boşum", "bosum", "boş", "boshman", "bo'shman", "bo'sh", "bosh",
    # Russian
    "свободен", "свободна", "свободны", "пустой", "порожний", "порожняк",
]

# The driver HAS a load (so is NOT available).
LOADED_WORDS = [
    "loaded", "booked", "covered",
    "загружен", "на грузе", "занят",
]

# The driver is not empty YET (the bot then asks for an expected time).
NOT_NOW_PHRASES = [
    "not yet", "not available", "unavailable", "not empty", "not ready", "not free",
    "still loaded", "still on a load", "still on the load", "still on load",
    "still delivering", "still unloading", "still rolling", "still waiting",
    "not empty yet", "not now",
]

# The driver is unsure -> the bot asks a short clarifying question.
HEDGE_WORDS = [
    "maybe", "might", "not sure", "probably", "perhaps", "possibly", "depends",
    "idk", "i think", "i guess",
]

# Short "yes" / "no" answers (only used right after the bot asked a yes/no question).
YES_WORDS = ["yes", "yeah", "yep", "yup", "yea", "sure", "ok", "okay", "correct",
             "right", "da", "ha", "xa", "да", "ага"]
NO_WORDS = ["no", "nope", "nah", "нет", "yo'q", "yoq", "yok"]
