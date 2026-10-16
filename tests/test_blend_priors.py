"""Tests for the pure helpers in tools/blend_priors.py (no data files written)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import blend_priors as B  # noqa: E402
from src import regmc_db as DB  # noqa: E402

NATURES = {n["name"] for n in DB.all_natures()}


def test_canon_nature_fixes_case_accents_and_typos():
    assert B.canon_nature("timid", NATURES) == "Timid"
    assert B.canon_nature("Naïve", NATURES) == "Naive"
    assert B.canon_nature("Adament", NATURES) == "Adamant"
    assert B.canon_nature("Relax", NATURES) == "Relaxed"
    assert B.canon_nature("Zzzzz", NATURES) is None


def test_canon_item_resolves_misspelled_mega_stone_only_for_own_species():
    assert B.canon_item("Excadrillite", DB.get_species("Excadrill"))["name"] == "Excadrite"
    assert B.canon_item("Excadrillite", DB.get_species("Garchomp")) is None
    assert B.canon_item("Sitrus Berry", DB.get_species("Garchomp"))["name"] == "Sitrus Berry"


def test_blend_builds_corpus_dominates_with_many_teams_metavgc_with_few():
    mv = [{"name": "Jolly 0/32/0/0/2/32", "pct": 100.0, "spread": "0/32/0/0/2/32"}]
    few = [{"nature": "Modest", "evs": {"spa": 32}, "count": 1}]
    many = [{"nature": "Modest", "evs": {"spa": 32}, "count": 100}]
    log = {"bad_spread": 0}
    assert B.blend_builds(few, mv, NATURES, log)[0]["nature"] == "Jolly"
    assert B.blend_builds(many, mv, NATURES, log)[0]["nature"] == "Modest"
    assert abs(sum(e["count"] for e in B.blend_builds([], mv, NATURES, log)) - B.N0) < 1e-6


def test_blend_abilities_mega_accepts_pre_mega_and_regional_form_rejects_base_abilities():
    log = {"corpus_ability_illegal": 0, "ability_distrusted": []}
    mega = B.blend_abilities([], [{"name": "Emergency Exit", "pct": 100.0}], DB.get_species("Golisopod-Mega"), log)
    assert [e["ability"] for e in mega] == ["Emergency Exit"]
    alola = B.blend_abilities([], [{"name": "Drought", "pct": 96.0}, {"name": "Flash Fire", "pct": 4.0}],
                              DB.get_species("Ninetales-Alola"), log)
    assert alola == [] and log["ability_distrusted"]


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
