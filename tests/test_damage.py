"""Regression pins for src/damage.py.

Pinned values were captured from the implementation after confirming it was
bit-identical to the pre-refactor code across ~12k randomized cases. They guard
against accidental drift; they are not an independent Showdown oracle.

Run: pytest tests/test_damage.py   (or: python tests/test_damage.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import damage as D  # noqa: E402

GARCHOMP_EQ = dict(
    attacker_species="Garchomp", attacker_evs={"atk": 32}, attacker_nature="Jolly",
    move_name="Earthquake",
    defender_species="Incineroar", defender_evs={"hp": 32, "def": 2},
    defender_nature="Careful",
)


def test_db_path_is_repo_relative():
    assert D._DB_PATH.is_file()
    assert D._DB_PATH.parent.name == "data"


def test_spread_move_base():
    assert D.damage_rolls(**GARCHOMP_EQ) == [
        134, 138, 138, 140, 144, 144, 146, 146, 150, 150, 152, 152, 156, 156, 158, 162]


def test_spread_penalty_removed_when_single_target():
    assert D.damage_rolls(include_spread=False, **GARCHOMP_EQ) == [
        186, 186, 188, 192, 192, 194, 198, 200, 200, 204, 206, 210, 210, 212, 216, 218]


def test_crit_and_burn():
    assert D.damage_rolls(crit=True, **GARCHOMP_EQ)[0] == 204
    assert D.damage_rolls(burn=True, **GARCHOMP_EQ)[0] == 67


def test_status_move_has_no_damage():
    assert D.damage_rolls(**{**GARCHOMP_EQ, "move_name": "Protect"}) == []


def test_rain_boosts_water():
    wet = D.damage_rolls("Incineroar", {"spa": 32}, "Modest", "Surf",
                         "Garchomp", {"hp": 2}, "Jolly", weather="rain")
    dry = D.damage_rolls("Incineroar", {"spa": 32}, "Modest", "Surf",
                         "Garchomp", {"hp": 2}, "Jolly")
    assert wet[0] == 53
    assert sum(wet) > sum(dry)


def test_stats_variant_matches_pin():
    rolls = D.damage_rolls_from_stats(
        {"atk": 150, "spa": 80}, ["Ground", "Dragon"], {"atk": 1}, "earthquake",
        {"def": 100, "spd": 90, "hp": 150}, ["Fire", "Dark"], {})
    assert rolls[0] == 188 and rolls[-1] == 224


def test_type_immunities_deal_zero():
    for mv, defender in [("earthquake", ["Flying"]), ("bodyslam", ["Ghost"]),
                         ("thunderbolt", ["Ground"]), ("dragonclaw", ["Fairy"]),
                         ("sludgebomb", ["Steel"])]:
        rolls = D.damage_rolls_from_stats(
            {"atk": 150, "spa": 150}, ["Normal"], {}, mv,
            {"def": 100, "spd": 100, "hp": 150}, defender, {})
        assert rolls == [0] * 16, (mv, defender, rolls)
    assert D._effectiveness("Ground", ["Dragon", "Flying"]) == 0.0
    assert D._effectiveness("Ground", ["Fire", "Dark"]) == 2.0


def test_rolls_are_sorted_and_16_long():
    rolls = D.damage_rolls(**GARCHOMP_EQ)
    assert len(rolls) == 16 and rolls == sorted(rolls)


def test_range_and_ko_chance():
    assert D.damage_range(**GARCHOMP_EQ) == (134, 147, 162)
    assert D.ko_chance(**GARCHOMP_EQ) == 0.0


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
