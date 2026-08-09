"""Turn WoW icon filenames into Stable Diffusion training captions.

The parse is deliberately mechanical and table driven so its output is
predictable and easy to correct by hand:

1. Strip the extension and split the stem on ``_`` (also ``-`` and spaces).
2. Split each token on CamelCase boundaries, keeping acronyms together
   (``PowerWordShield`` -> ``power word shield``, ``winWSG`` -> ``win wsg``).
3. Drop purely numeric words, so ``INV_Sword_04`` and ``Spell_Fire_Fireball02``
   both lose their trailing counter.
4. Pick a category from the ``INV_`` / ``Spell_`` / ``Ability_`` / ``Trade_`` /
   ``Achievement_`` prefix, refined by the words that follow.
5. Drop words already implied by the category, so the caption does not repeat
   itself (``Spell_Fire_Fireball02`` -> ``fire spell, fireball``).
6. Apply ``overrides.json`` on top, so anything the tables get wrong can be
   fixed without touching code.

The result is rendered as ``"wowicon, <category>, <subject terms>"``.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass, replace
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "Caption",
    "OverrideRule",
    "DEFAULT_INSTANCE_TOKEN",
    "split_words",
    "parse_filename",
    "load_overrides",
    "apply_overrides",
    "caption_for",
]

DEFAULT_INSTANCE_TOKEN = "wowicon"

#: Words that carry no visual meaning and are dropped from the subject terms.
NOISE_WORDS = frozenset({"inv", "misc", "icon"})

#: Whole tokens rewritten before word splitting, where CamelCase splitting
#: would otherwise mangle them.
TOKEN_SYNONYMS: Mapping[str, str] = {
    "1h": "one handed",
    "2h": "two handed",
    "offhand": "off hand",
    "bg": "battleground",
}

#: Filename prefix -> base category.
PREFIX_CATEGORIES: Mapping[str, str] = {
    "inv": "item",
    "spell": "spell",
    "ability": "ability",
    "trade": "profession",
    "achievement": "achievement",
    "racial": "racial ability",
    "classicon": "class icon",
}

#: ``Spell_<school>_...`` -> "<school> spell".
SPELL_SCHOOLS = frozenset(
    {"arcane", "fire", "frost", "holy", "nature", "shadow"}
)

#: ``Ability_<class>_...`` -> "<class> ability".
ABILITY_CLASSES = frozenset(
    {
        "warrior",
        "paladin",
        "hunter",
        "rogue",
        "priest",
        "shaman",
        "mage",
        "warlock",
        "druid",
        "deathknight",
    }
)

#: ``Ability_<group>_...`` -> a category of its own.
ABILITY_GROUPS: Mapping[str, str] = {
    "mount": "mount",
    "racial": "racial ability",
    "creature": "creature ability",
    "seal": "paladin ability",
}

#: Word -> category for ``INV_`` items. The first word that matches wins, so
#: ``INV_Chest_Cloth_17`` is armor (``chest``) rather than fabric (``cloth``).
ITEM_CATEGORIES: Mapping[str, str] = {
    # weapons
    "sword": "weapon",
    "axe": "weapon",
    "mace": "weapon",
    "hammer": "weapon",
    "staff": "weapon",
    "stave": "weapon",
    "dagger": "weapon",
    "blade": "weapon",
    "knife": "weapon",
    "spear": "weapon",
    "polearm": "weapon",
    "halberd": "weapon",
    "bow": "weapon",
    "crossbow": "weapon",
    "rifle": "weapon",
    "gun": "weapon",
    "musket": "weapon",
    "wand": "weapon",
    "weapon": "weapon",
    # armor
    "helmet": "armor",
    "helm": "armor",
    "crown": "armor",
    "chest": "armor",
    "shirt": "armor",
    "robe": "armor",
    "shoulder": "armor",
    "pauldrons": "armor",
    "bracer": "armor",
    "gauntlets": "armor",
    "glove": "armor",
    "gloves": "armor",
    "belt": "armor",
    "boots": "armor",
    "pants": "armor",
    "cape": "armor",
    "cloak": "armor",
    "shield": "armor",
    "buckler": "armor",
    "armor": "armor",
    "armour": "armor",
    # jewelry
    "jewelry": "jewelry",
    "ring": "jewelry",
    "necklace": "jewelry",
    "amulet": "jewelry",
    "talisman": "jewelry",
    "trinket": "jewelry",
    # consumables
    "potion": "consumable",
    "elixir": "consumable",
    "flask": "consumable",
    "drink": "consumable",
    "food": "consumable",
    "bandage": "consumable",
    "poison": "consumable",
    # crafting reagents
    "ore": "reagent",
    "ingot": "reagent",
    "bar": "reagent",
    "herb": "reagent",
    "fabric": "reagent",
    "leather": "reagent",
    "pelt": "reagent",
    "hide": "reagent",
    "gem": "reagent",
    "dust": "reagent",
    "essence": "reagent",
    "shard": "reagent",
    "enchant": "reagent",
    "rune": "reagent",
    "bone": "reagent",
    "feather": "reagent",
    "scale": "reagent",
    "mushroom": "reagent",
    # containers and ammunition
    "bag": "container",
    "box": "container",
    "crate": "container",
    "barrel": "container",
    "quiver": "container",
    "pouch": "container",
    "ammo": "ammunition",
    "arrow": "ammunition",
    "bullet": "ammunition",
    # paper-ish props
    "scroll": "document",
    "letter": "document",
    "book": "document",
    "note": "document",
    "map": "document",
    "parchment": "document",
    # misc but worth counting separately
    "coin": "currency",
    "banner": "banner",
    "tabard": "banner",
    "gizmo": "gadget",
}

#: Extra words a category already implies, dropped from the subject terms the
#: same way the category's own words are (``ammunition`` implies ``ammo``).
IMPLIED_WORDS: Mapping[str, frozenset] = {
    "ammunition": frozenset({"ammo"}),
    "armor": frozenset({"armour"}),
    "jewelry": frozenset({"jewellery"}),
}

#: Category used when an ``INV_`` name matches nothing in ``ITEM_CATEGORIES``.
FALLBACK_ITEM_CATEGORY = "misc item"

#: Category used when the prefix itself is unknown.
FALLBACK_CATEGORY = "misc"

_SPLIT_TOKENS = re.compile(r"[_\-\s]+")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+")


@dataclass(frozen=True)
class Caption:
    """A parsed caption for one icon."""

    stem: str
    category: str
    terms: Tuple[str, ...]
    instance_token: str = DEFAULT_INSTANCE_TOKEN

    @property
    def text(self) -> str:
        """The caption written to the ``.txt`` sidecar file."""
        return ", ".join([self.instance_token, self.category, *self.terms])

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.text


@dataclass(frozen=True)
class OverrideRule:
    """One hand-written correction from ``overrides.json``."""

    pattern: str
    category: Optional[str] = None
    terms: Optional[Tuple[str, ...]] = None
    add_terms: Tuple[str, ...] = ()
    drop_terms: Tuple[str, ...] = ()

    def matches(self, stem: str, filename: str = "") -> bool:
        pattern = self.pattern.lower()
        if fnmatch.fnmatchcase(stem.lower(), pattern):
            return True
        return bool(filename) and fnmatch.fnmatchcase(filename.lower(), pattern)


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------


def split_words(token: str) -> List[str]:
    """Split one underscore-delimited token into lowercase words.

    ``"PowerWordShield"`` -> ``["power", "word", "shield"]``;
    ``"winWSG"`` -> ``["win", "wsg"]``; ``"Fireball02"`` -> ``["fireball"]``.
    Purely numeric runs are dropped, which is what strips the trailing counter
    from names like ``INV_Sword_04``.
    """
    expanded = TOKEN_SYNONYMS.get(token.lower(), token)
    words: List[str] = []
    for part in _SPLIT_TOKENS.split(expanded):
        for word in _CAMEL.findall(part):
            if word.isdigit():
                continue
            words.append(word.lower())
    return words


def _tokenize(stem: str) -> List[List[str]]:
    """Split a filename stem into tokens, each already split into words."""
    tokens = []
    for token in _SPLIT_TOKENS.split(stem):
        if not token:
            continue
        words = split_words(token)
        if words:
            tokens.append(words)
    return tokens


def _detect_category(prefix: str, tokens: Sequence[Sequence[str]]) -> str:
    """Pick a category from the prefix, refined by the following words."""
    base = PREFIX_CATEGORIES.get(prefix, FALLBACK_CATEGORY)
    words = [word for token in tokens for word in token]

    if base == "item":
        for word in words:
            category = ITEM_CATEGORIES.get(word)
            if category:
                return category
        return FALLBACK_ITEM_CATEGORY

    if base == "spell":
        for word in words:
            if word in SPELL_SCHOOLS:
                return f"{word} spell"
        return "spell"

    if base == "ability":
        for word in words:
            if word in ABILITY_CLASSES:
                return f"{word} ability"
            group = ABILITY_GROUPS.get(word)
            if group:
                return group
        return "ability"

    return base


def _subject_terms(
    tokens: Sequence[Sequence[str]], category: str
) -> Tuple[str, ...]:
    """Render tokens as subject terms, minus noise and category repetition."""
    category_words = set(category.split()) | set(IMPLIED_WORDS.get(category, ()))
    terms: List[str] = []
    fallback: List[str] = []

    for token in tokens:
        kept = [word for word in token if word not in NOISE_WORDS]
        if not kept:
            continue
        fallback.append(" ".join(kept))
        trimmed = [word for word in kept if word not in category_words]
        if not trimmed:
            continue
        term = " ".join(trimmed)
        if term not in terms:
            terms.append(term)

    if not terms:
        # Everything collapsed into the category (e.g. "INV_Weapon_01"); keep
        # the original words rather than emitting a caption with no subject.
        terms = list(dict.fromkeys(fallback))

    return tuple(terms)


def parse_filename(
    name: str, instance_token: str = DEFAULT_INSTANCE_TOKEN
) -> Caption:
    """Parse an icon filename (with or without extension) into a caption."""
    stem = os.path.basename(name)
    stem = os.path.splitext(stem)[0]

    tokens = _tokenize(stem)
    if not tokens:
        return Caption(
            stem=stem,
            category=FALLBACK_CATEGORY,
            terms=("icon",),
            instance_token=instance_token,
        )

    prefix = tokens[0][0] if len(tokens[0]) == 1 else "".join(tokens[0])
    if prefix in PREFIX_CATEGORIES:
        rest = tokens[1:]
    else:
        prefix = ""
        rest = tokens

    category = _detect_category(prefix, rest)
    terms = _subject_terms(rest or tokens, category)

    return Caption(
        stem=stem, category=category, terms=terms, instance_token=instance_token
    )


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def _as_terms(value) -> Tuple[str, ...]:
    """Accept either ``"a, b"`` or ``["a", "b"]`` for a term list."""
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple)):
        parts = [str(part).strip() for part in value]
    else:
        raise ValueError(f"expected a string or list of terms, got {value!r}")
    return tuple(part for part in parts if part)


def _rule_from_mapping(pattern: str, body) -> OverrideRule:
    if isinstance(body, (str, list, tuple)):
        return OverrideRule(pattern=pattern, terms=_as_terms(body))
    if not isinstance(body, dict):
        raise ValueError(f"override for {pattern!r} must be a string, list or object")

    unknown = set(body) - {"match", "pattern", "category", "terms", "add_terms", "drop_terms"}
    if unknown:
        raise ValueError(
            f"override for {pattern!r} has unknown keys: {sorted(unknown)}"
        )

    return OverrideRule(
        pattern=pattern,
        category=body.get("category"),
        terms=_as_terms(body["terms"]) if "terms" in body else None,
        add_terms=_as_terms(body.get("add_terms")),
        drop_terms=_as_terms(body.get("drop_terms")),
    )


def parse_overrides(document) -> List[OverrideRule]:
    """Build rules from already-loaded JSON.

    Three hand-friendly shapes are accepted:

    * ``{"INV_Sword_*": "sword, blade"}`` -- pattern to replacement terms.
    * ``{"INV_Sword_*": {"category": "weapon", "add_terms": ["blade"]}}``
    * ``{"rules": [{"match": "INV_Sword_*", "add_terms": ["blade"]}]}`` or a
      bare list of such rule objects, when order needs to be explicit.

    Rules are applied in document order; later matches win.
    """
    if isinstance(document, dict) and "rules" in document:
        document = document["rules"]

    rules: List[OverrideRule] = []
    if isinstance(document, list):
        for entry in document:
            if not isinstance(entry, dict):
                raise ValueError(f"rule entries must be objects, got {entry!r}")
            pattern = entry.get("match") or entry.get("pattern")
            if not pattern:
                raise ValueError(f"rule entry is missing 'match': {entry!r}")
            rules.append(_rule_from_mapping(str(pattern), entry))
    elif isinstance(document, dict):
        for pattern, body in document.items():
            if pattern.startswith("_") or pattern in ("version", "comment"):
                continue  # room for hand-written notes in the file
            rules.append(_rule_from_mapping(pattern, body))
    else:
        raise ValueError("overrides must be a JSON object or list")

    return rules


def load_overrides(path) -> List[OverrideRule]:
    """Load and validate an ``overrides.json`` file."""
    with open(path, "r", encoding="utf-8") as handle:
        document = json.load(handle)
    return parse_overrides(document)


def apply_overrides(
    caption: Caption, rules: Iterable[OverrideRule], filename: str = ""
) -> Caption:
    """Apply every matching rule, in order, to an automatically parsed caption."""
    category = caption.category
    terms = list(caption.terms)

    for rule in rules:
        if not rule.matches(caption.stem, filename):
            continue
        if rule.category:
            category = rule.category
        if rule.terms is not None:
            terms = list(rule.terms)
        for term in rule.add_terms:
            if term not in terms:
                terms.append(term)
        if rule.drop_terms:
            dropped = {term.lower() for term in rule.drop_terms}
            terms = [term for term in terms if term.lower() not in dropped]

    return replace(caption, category=category, terms=tuple(terms))


def caption_for(
    name: str,
    rules: Iterable[OverrideRule] = (),
    instance_token: str = DEFAULT_INSTANCE_TOKEN,
) -> Caption:
    """Parse ``name`` and apply ``rules`` -- the entry point the pipeline uses."""
    caption = parse_filename(name, instance_token=instance_token)
    return apply_overrides(caption, rules, filename=os.path.basename(name))
