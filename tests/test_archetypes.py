"""Tests for src/archetypes.py on a small synthetic table (no data files needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import archetypes as A  # noqa: E402

ROW = {
    "n": 30,
    "archetypes": [
        {"item": "Zstone", "nature": "Modest", "form": "Mon-Mega-Z", "count": 18,
         "spreads": [{"evs": {"spa": 32, "spe": 32}, "count": 18}],
         "moves": {"Protect": 18, "Power Gem": 17, "Earth Power": 16}, "abilities": {"Rough Skin": 18}},
        {"item": "Choice Scarf", "nature": "Adamant", "form": None, "count": 8,
         "spreads": [{"evs": {"atk": 32, "spe": 32}, "count": 8}],
         "moves": {"Dragon Claw": 8, "Rock Slide": 7, "Earthquake": 6}, "abilities": {"Rough Skin": 8}},
        {"item": "Life Orb", "nature": "Jolly", "form": None, "count": 4,
         "spreads": [{"evs": {"atk": 32, "spe": 32}, "count": 4}],
         "moves": {"Dragon Claw": 4, "Protect": 4, "Earthquake": 3}, "abilities": {"Rough Skin": 4}},
    ],
}


def _top(post):
    return post[0][1]["item"]


def test_no_evidence_is_count_weighted():
    post = A.posterior(ROW)
    assert abs(sum(w for w, _ in post) - 1.0) < 1e-9
    assert _top(post) == "Zstone" and abs(post[0][0] - 18 / 30) < 1e-9


def test_revealed_item_selects_group():
    assert _top(A.posterior(ROW, item="Choice Scarf")) == "Choice Scarf"
    assert A.posterior(ROW, item="Choice Scarf")[0][0] > 0.9
    assert abs(sum(A.item_distribution(A.posterior(ROW, item="unknown_item")).values()) - 1.0) < 1e-9


def test_revealed_moves_select_group():
    assert _top(A.posterior(ROW, moves_seen=["Power Gem"])) == "Zstone"
    assert A.posterior(ROW, moves_seen=["Power Gem"])[0][0] > 0.9
    assert _top(A.posterior(ROW, moves_seen=["Dragon Claw"])) in ("Choice Scarf", "Life Orb")
    assert A.posterior(ROW, moves_seen=["Dragon Claw"])[0][1]["item"] != "Zstone"


def test_mega_form_filters_groups_and_falls_back_when_unseen():
    post = A.posterior(ROW, form="Mon-Mega-Z")
    assert len(post) == 1 and post[0][1]["item"] == "Zstone"
    assert len(A.posterior(ROW, form="Mon-Mega")) == 3


def test_unknown_move_does_not_zero_everything():
    post = A.posterior(ROW, moves_seen=["Splash"])
    assert abs(sum(w for w, _ in post) - 1.0) < 1e-9 and _top(post) == "Zstone"


def test_move_distribution_reflects_posterior():
    z = A.move_distribution(A.posterior(ROW, item="Zstone"))
    assert z["Power Gem"] > 0.9 and z.get("Dragon Claw", 0.0) < 0.1


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e!r}")
    sys.exit(1 if failed else 0)
