"""How alike two gadget names are, from 0 (different items) to 1 (the same).

Models name the same item many ways: "Portable Bluetooth Speaker",
"Bluetooth Speaker", "Wireless Speaker"; "Power Bank 20,000mAh" and
"Portable Charger"; "Type D/G Travel Plug Adapter" and "Universal Travel
Adapter". Exact matching let these through as separate items -- in a
traveller's list and in the coordinators' catalog.

A name is first reduced to canonical words:
- lowercase, parentheticals dropped ("(SPF 50)", "(Type D/G)"), hyphens
  read as spaces ("Quick-Dry" = "Quick Dry");
- specs dropped: numbers and number+unit ("20,000mAh", "10W", "2L"),
  "spf", "type" and stray single letters (plug types);
- phrases and words mapped to one form, from app/data/gadget_terms.json
  ("portable charger" -> "power bank", "wireless" -> "bluetooth");
- plurals made singular.

Two names are then compared on their main noun -- the last word that is not
a filler ("speaker", "bag", "adapter") -- which must agree, or they are
different items however many other words they share ("Dry Bag" is not a
"Dry Shampoo"). The score is a weighted overlap of the remaining words,
where fillers ("portable", "travel", "waterproof") count for little.

SAME (>= 0.8) is treated as the same item automatically; POSSIBLE
(0.5 - 0.8) is shown to a coordinator to decide. Deterministic and free: no
model call, so it can run on every list.
"""

import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path


SAME = 0.8
POSSIBLE = 0.5
FILLER_WEIGHT = 0.2

TERMS_PATH = Path(__file__).resolve().parents[2] / "data" / "gadget_terms.json"

_PAREN = re.compile(r"\(.*?\)")
_TOKEN = re.compile(r"[a-z0-9]+")
_SPEC = re.compile(r"^\d[\d,.]*[a-z]*$")
_SPEC_WORDS = {"spf", "type", "mah", "w", "v", "l", "ml", "mm", "cm", "gb", "tb", "inch", "in", "x"}


@lru_cache(maxsize=1)
def _terms() -> tuple[list[tuple[str, str]], dict[str, str], frozenset[str]]:
    data = json.loads(TERMS_PATH.read_text(encoding="utf-8"))
    # Longest phrases first, so "portable charger" wins over shorter overlaps.
    phrases = sorted(data.get("phrases", {}).items(), key=lambda kv: -len(kv[0]))
    return phrases, data.get("words", {}), frozenset(data.get("fillers", []))


def _singular(word: str) -> str:
    if len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith(("shes", "ches", "xes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


@lru_cache(maxsize=4096)
def canonical(name: str) -> tuple[str, ...]:
    """The comparable words of a name, in order. Cached: the duplicates
    view compares every pair of catalog names."""
    phrases, words, _ = _terms()
    text = " " + " ".join(_TOKEN.findall(_PAREN.sub(" ", name.lower()).replace("_", " "))) + " "

    for phrase, replacement in phrases:
        text = text.replace(f" {phrase} ", f" {replacement} ")

    out: list[str] = []
    for token in text.split():
        if len(token) == 1 or _SPEC.match(token) or token in _SPEC_WORDS:
            continue
        token = words.get(token, token)
        for part in token.split():  # a word may map to a phrase
            out.append(_singular(part))
    return tuple(out)


def _head(tokens: tuple[str, ...], fillers: frozenset[str]) -> str | None:
    meaningful = [t for t in tokens if t not in fillers]
    return (meaningful or tokens or [None])[-1]


def similarity(a: str, b: str) -> float:
    ta, tb = canonical(a), canonical(b)
    if not ta or not tb:
        return 0.0

    _, _, fillers = _terms()
    ha, hb = _head(ta, fillers), _head(tb, fillers)
    # The main noun must agree -- allowing a typo ("sunglases").
    if ha != hb and SequenceMatcher(None, ha, hb).ratio() < 0.85:
        return 0.0

    def weights(tokens):
        return {t: (FILLER_WEIGHT if t in fillers else 1.0) for t in tokens}

    wa, wb = weights(ta), weights(tb)
    # Typo-tolerant heads count as the same word.
    if ha != hb:
        wb[ha] = wb.pop(hb)

    union = wa.keys() | wb.keys()
    shared = sum(min(wa.get(t, 0), wb.get(t, 0)) for t in union)
    total = sum(max(wa.get(t, 0), wb.get(t, 0)) for t in union)
    return round(shared / total, 3) if total else 0.0


def is_same(a: str, b: str) -> bool:
    return similarity(a, b) >= SAME
