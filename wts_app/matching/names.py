"""Comparing the names the Electoral Commission publishes.

Candidate names arrive as ``LASTNAME, First Names``. Two things make matching
them awkward: people acquire and drop middle names between elections, and the
same person may be recorded with or without macrons.
"""

import difflib
import re
import unicodedata


def normalise(value):
    """Fold a name to a comparable form.

    Strips diacritics, lowercases, and drops everything that is not a letter or
    a space. The diacritic folding matters here: it lets ``Māhuta`` and
    ``Mahuta`` compare equal, which is what matching wants -- at the cost of
    never being able to tell them apart on name alone.
    """
    if not value:
        return ''
    folded = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z ]', ' ', folded.lower()).strip()


def split_name(value):
    """``LASTNAME, First Names`` -> ``('lastname', ['first', 'names'])``."""
    surname, _, given = (value or '').partition(',')
    return normalise(surname), normalise(given).split()


def is_structural_match(one, other):
    """Whether two names differ only by trailing given names.

    Same surname, and one list of given names is a prefix of the other. This
    encodes exactly one real-world fact -- that people add and drop middle names
    -- and nothing else.

    Deliberately token-level. A string prefix would match ``Jo`` to ``John``;
    whole given names have to agree.

        GREENSLADE, David   ~ GREENSLADE, David John   -> True
        McDONALD, Don S     ~ McDONALD, Don S Newt     -> True
        ANDERSON, Dion      ~ ANDERSON, Erina          -> False
        LAUDERDALE, Kathleen ~ LAUDERDALE, Kath        -> False (a judgement call,
                                                         not a mechanical one)
    """
    surname_one, given_one = split_name(one)
    surname_other, given_other = split_name(other)

    if not surname_one or surname_one != surname_other:
        return False
    if not given_one or not given_other:
        return False

    shorter, longer = sorted((given_one, given_other), key=len)
    return longer[:len(shorter)] == shorter


def similarity(one, other):
    """How alike two names look, between 0 and 1.

    Ratcliff/Obershelp, via difflib. Used only to decide what a person is shown,
    never to decide a link: a false pair can outscore a true one, so no
    threshold separates them. ``JOHNSTON, Brian`` and ``JOHNSON, Ian`` score
    0.88 while the genuine ``GREENSLADE`` pair scores 0.865.
    """
    return difflib.SequenceMatcher(None, normalise(one), normalise(other)).ratio()


def best_similar(value, candidates, minimum):
    """The most similar candidate above ``minimum``, or None.

    ``candidates`` maps a comparable name to whatever object it belongs to.
    """
    best = None
    best_score = minimum

    for name, obj in candidates.items():
        score = similarity(value, name)
        if score >= best_score:
            best, best_score = obj, score

    return (best, best_score) if best is not None else (None, 0.0)
