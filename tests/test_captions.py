"""Tests for the filename -> caption parser.

The fixture list is deliberately made of real ``Interface/Icons`` filenames
from a WoW client, covering every prefix the parser claims to handle plus the
awkward cases: CamelCase runs, acronyms, trailing counters, and counters glued
to the end of a word.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wowicons.captions import (
    Caption,
    OverrideRule,
    apply_overrides,
    caption_for,
    load_overrides,
    parse_filename,
    parse_overrides,
    split_words,
)

# (filename, expected category, expected subject terms)
REAL_ICON_NAMES = [
    # --- INV_ weapons -------------------------------------------------
    ("INV_Sword_04", "weapon", ("sword",)),
    ("INV_Axe_02", "weapon", ("axe",)),
    ("INV_Mace_01", "weapon", ("mace",)),
    ("INV_Hammer_16", "weapon", ("hammer",)),
    ("INV_Staff_13", "weapon", ("staff",)),
    ("INV_Wand_01", "weapon", ("wand",)),
    ("INV_Weapon_Bow_07", "weapon", ("bow",)),
    ("INV_Weapon_Rifle_01", "weapon", ("rifle",)),
    ("INV_Weapon_ShortBlade_05", "weapon", ("short blade",)),
    ("INV_ThrowingAxe_03", "weapon", ("throwing axe",)),
    # --- INV_ armor and jewelry ---------------------------------------
    ("INV_Shield_06", "armor", ("shield",)),
    ("INV_Helmet_03", "armor", ("helmet",)),
    ("INV_Chest_Cloth_17", "armor", ("chest", "cloth")),
    ("INV_Boots_Chain_05", "armor", ("boots", "chain")),
    ("INV_Gauntlets_04", "armor", ("gauntlets",)),
    ("INV_Bracer_02", "armor", ("bracer",)),
    ("INV_Belt_09", "armor", ("belt",)),
    ("INV_Pants_Mail_04", "armor", ("pants", "mail")),
    ("INV_Jewelry_Ring_03", "jewelry", ("ring",)),
    ("INV_Jewelry_Necklace_07", "jewelry", ("necklace",)),
    # --- INV_ consumables, reagents, containers -----------------------
    ("INV_Potion_51", "consumable", ("potion",)),
    ("INV_Drink_05", "consumable", ("drink",)),
    ("INV_Misc_Food_15", "consumable", ("food",)),
    ("INV_Misc_Bandage_01", "consumable", ("bandage",)),
    ("INV_Ore_Copper_01", "reagent", ("ore", "copper")),
    ("INV_Fabric_Linen_01", "reagent", ("fabric", "linen")),
    ("INV_Misc_Herb_01", "reagent", ("herb",)),
    ("INV_Misc_Gem_Bloodstone_01", "reagent", ("gem", "bloodstone")),
    ("INV_Misc_Rune_01", "reagent", ("rune",)),
    ("INV_Box_01", "container", ("box",)),
    ("INV_Bag_08", "container", ("bag",)),
    ("INV_Scroll_03", "document", ("scroll",)),
    ("INV_Letter_15", "document", ("letter",)),
    ("INV_Misc_Coin_01", "currency", ("coin",)),
    ("INV_Ammo_Arrow_01", "ammunition", ("arrow",)),
    ("INV_Ammo_Bullet_01", "ammunition", ("bullet",)),
    ("INV_Misc_QuestionMark", "misc item", ("question mark",)),
    ("INV_Misc_Head_Dragon_01", "misc item", ("head", "dragon")),
    # --- Spell_ --------------------------------------------------------
    ("Spell_Fire_Fireball02", "fire spell", ("fireball",)),
    ("Spell_Frost_FrostBolt02", "frost spell", ("bolt",)),
    ("Spell_Frost_FrostArmor02", "frost spell", ("armor",)),
    ("Spell_Shadow_ShadowBolt", "shadow spell", ("bolt",)),
    ("Spell_Shadow_DeathCoil", "shadow spell", ("death coil",)),
    ("Spell_Holy_HolyBolt", "holy spell", ("bolt",)),
    ("Spell_Holy_PowerWordShield", "holy spell", ("power word shield",)),
    ("Spell_Holy_SealOfMight", "holy spell", ("seal of might",)),
    ("Spell_Nature_HealingTouch", "nature spell", ("healing touch",)),
    ("Spell_Nature_Lightning", "nature spell", ("lightning",)),
    ("Spell_Arcane_Blink", "arcane spell", ("blink",)),
    # --- Ability_ ------------------------------------------------------
    ("Ability_Warrior_Charge", "warrior ability", ("charge",)),
    ("Ability_Warrior_Cleave", "warrior ability", ("cleave",)),
    ("Ability_Rogue_Sprint", "rogue ability", ("sprint",)),
    ("Ability_Hunter_AimedShot", "hunter ability", ("aimed shot",)),
    ("Ability_Druid_CatForm", "druid ability", ("cat form",)),
    ("Ability_Backstab", "ability", ("backstab",)),
    ("Ability_Stealth", "ability", ("stealth",)),
    ("Ability_Mount_RidingHorse", "mount", ("riding horse",)),
    ("Ability_Racial_Avatar", "racial ability", ("avatar",)),
    # --- Trade_ --------------------------------------------------------
    ("Trade_Alchemy", "profession", ("alchemy",)),
    ("Trade_BlackSmithing", "profession", ("black smithing",)),
    ("Trade_Engineering", "profession", ("engineering",)),
    ("Trade_Herbalism", "profession", ("herbalism",)),
    ("Trade_Mining", "profession", ("mining",)),
    ("Trade_Fishing", "profession", ("fishing",)),
    ("Trade_Tailoring", "profession", ("tailoring",)),
    # --- Achievement_ ---------------------------------------------------
    (
        "Achievement_Character_Human_Male",
        "achievement",
        ("character", "human", "male"),
    ),
    ("Achievement_Zone_Silithus", "achievement", ("zone", "silithus")),
    ("Achievement_Boss_Ragnaros", "achievement", ("boss", "ragnaros")),
    ("Achievement_BG_winWSG", "achievement", ("battleground", "win wsg")),
]


@pytest.mark.parametrize("name,category,terms", REAL_ICON_NAMES)
def test_real_icon_names(name, category, terms):
    caption = parse_filename(name)
    assert caption.category == category
    assert caption.terms == terms


@pytest.mark.parametrize("name,category,terms", REAL_ICON_NAMES)
def test_caption_text_shape(name, category, terms):
    """Every caption is 'wowicon, <category>, <subject terms>'."""
    text = parse_filename(name).text
    assert text.startswith("wowicon, ")
    parts = [part.strip() for part in text.split(",")]
    assert parts[0] == "wowicon"
    assert parts[1] == category
    assert tuple(parts[2:]) == terms


def test_at_least_twenty_real_fixtures():
    assert len({name for name, _, _ in REAL_ICON_NAMES}) >= 20


# ---------------------------------------------------------------------------
# Word splitting details
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token,expected",
    [
        ("PowerWordShield", ["power", "word", "shield"]),
        ("Fireball02", ["fireball"]),
        ("winWSG", ["win", "wsg"]),
        ("QuestionMark", ["question", "mark"]),
        ("04", []),
        ("Sword", ["sword"]),
        ("INV", ["inv"]),
        ("SealOfMight", ["seal", "of", "might"]),
        ("2H", ["two", "handed"]),
        ("BG", ["battleground"]),
    ],
)
def test_split_words(token, expected):
    assert split_words(token) == expected


def test_extension_and_path_are_stripped():
    caption = parse_filename("/mnt/wow/Interface/Icons/INV_Sword_04.blp")
    assert caption.stem == "INV_Sword_04"
    assert caption.text == "wowicon, weapon, sword"


def test_trailing_numbers_do_not_reach_the_caption():
    for name in ("INV_Sword_04", "INV_Sword_2", "Spell_Fire_Fireball02"):
        assert not any(char.isdigit() for char in parse_filename(name).text)


def test_unknown_prefix_falls_back_to_misc():
    caption = parse_filename("Temp_Widget_03")
    assert caption.category == "misc"
    assert caption.terms == ("temp", "widget")


def test_category_words_are_not_repeated_in_terms():
    assert parse_filename("INV_Weapon_Bow_07").terms == ("bow",)
    assert parse_filename("Spell_Fire_Fireball02").terms == ("fireball",)


def test_subject_survives_when_every_word_is_the_category():
    caption = parse_filename("INV_Weapon_01")
    assert caption.category == "weapon"
    assert caption.terms == ("weapon",)
    assert caption.text == "wowicon, weapon, weapon"


def test_instance_token_is_configurable():
    caption = parse_filename("INV_Sword_04", instance_token="wowicon2")
    assert caption.text == "wowicon2, weapon, sword"


def test_duplicate_tokens_collapse():
    caption = parse_filename("INV_Misc_Bone_Bone_01")
    assert caption.terms == ("bone",)


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_override_shorthand_replaces_terms():
    rules = parse_overrides({"Trade_BlackSmithing": "blacksmithing, anvil"})
    caption = caption_for("Trade_BlackSmithing.blp", rules)
    assert caption.text == "wowicon, profession, blacksmithing, anvil"


def test_override_list_shorthand():
    rules = parse_overrides({"INV_Sword_04": ["longsword", "steel"]})
    assert caption_for("INV_Sword_04", rules).terms == ("longsword", "steel")


def test_override_can_change_category_and_add_terms():
    rules = parse_overrides(
        {"INV_Misc_QuestionMark": {"category": "ui", "add_terms": ["placeholder"]}}
    )
    caption = caption_for("INV_Misc_QuestionMark", rules)
    assert caption.category == "ui"
    assert caption.terms == ("question mark", "placeholder")


def test_override_can_drop_terms():
    rules = parse_overrides({"INV_Chest_Cloth_*": {"drop_terms": ["cloth"]}})
    assert caption_for("INV_Chest_Cloth_17", rules).terms == ("chest",)


def test_override_wildcards_match_and_extension_is_ignored():
    rules = parse_overrides({"Spell_Fire_*": {"add_terms": ["flames"]}})
    assert "flames" in caption_for("Spell_Fire_Fireball02.blp", rules).terms
    assert "flames" not in caption_for("Spell_Frost_FrostBolt02.blp", rules).terms


def test_override_patterns_are_case_insensitive():
    rules = parse_overrides({"inv_sword_*": {"add_terms": ["blade"]}})
    assert "blade" in caption_for("INV_Sword_04", rules).terms


def test_overrides_apply_in_document_order():
    rules = parse_overrides(
        {
            "INV_Sword_*": {"category": "weapon", "add_terms": ["blade"]},
            "INV_Sword_04": {"category": "artifact weapon"},
        }
    )
    caption = caption_for("INV_Sword_04", rules)
    assert caption.category == "artifact weapon"
    assert caption.terms == ("sword", "blade")


def test_rules_list_form_keeps_explicit_order():
    rules = parse_overrides(
        {
            "rules": [
                {"match": "INV_*", "add_terms": ["item art"]},
                {"match": "INV_Sword_04", "add_terms": ["hero sword"]},
            ]
        }
    )
    assert caption_for("INV_Sword_04", rules).terms == (
        "sword",
        "item art",
        "hero sword",
    )


def test_add_terms_does_not_duplicate():
    rules = parse_overrides({"INV_Sword_*": {"add_terms": ["sword"]}})
    assert caption_for("INV_Sword_04", rules).terms == ("sword",)


def test_comment_keys_are_ignored():
    rules = parse_overrides({"_comment": "notes", "INV_Sword_*": "blade"})
    assert len(rules) == 1


def test_unknown_override_key_is_rejected():
    with pytest.raises(ValueError, match="unknown keys"):
        parse_overrides({"INV_Sword_*": {"catagory": "weapon"}})


def test_rule_without_match_is_rejected():
    with pytest.raises(ValueError, match="missing 'match'"):
        parse_overrides({"rules": [{"add_terms": ["x"]}]})


def test_apply_overrides_is_a_no_op_without_rules():
    caption = parse_filename("INV_Sword_04")
    assert apply_overrides(caption, []) == caption


def test_shipped_overrides_file_loads():
    """The overrides.json committed at the repo root must stay valid."""
    path = Path(__file__).resolve().parent.parent / "overrides.json"
    rules = load_overrides(path)
    assert rules
    assert all(isinstance(rule, OverrideRule) for rule in rules)
    # And it must actually change something.
    caption = caption_for("Trade_Engraving", rules)
    assert "enchanting" in caption.terms


def test_load_overrides_round_trip(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"INV_Sword_*": "blade"}), encoding="utf-8")
    rules = load_overrides(path)
    assert caption_for("INV_Sword_04", rules) == Caption(
        stem="INV_Sword_04", category="weapon", terms=("blade",)
    )
