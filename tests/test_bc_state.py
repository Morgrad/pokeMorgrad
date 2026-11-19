"""Live-battle -> encoder-state conversion used by the BC pilot and the heuristic dataset tool.

Regression: commit 1788b2a (2026-10-16) removed mon_view's unused `is_opp` parameter but
left two callers passing it, so BCPlayer raised TypeError on every decision and
tools/generate_heuristic_dataset.py silently wrote 0 rows. No Showdown, no model file:
the battle is a stub. Needs torch (imported by src.bc_player). Run: python tests/test_bc_state.py
"""
import importlib.util
import os
import sys
from types import SimpleNamespace as NS

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from src.bc_player import BCPlayer  # noqa: E402


def _mon(species, hp=0.5):
    move = NS(id="protect")
    return NS(species=species, moves={"protect": move}, current_hp_fraction=hp, status=None,
              boosts={"atk": 1, "def": 0}, fainted=False, gender=None, item=None, ability=None)


def _battle():
    a, b, c, d = _mon("umbreon"), _mon("incineroar"), _mon("garchomp"), _mon("amoonguss")
    return NS(active_pokemon=[a, b], team={"a": a, "b": b, "x": _mon("sylveon")},
              opponent_active_pokemon=[c, None], opponent_team={"c": c, "d": d},
              weather={}, fields={}, side_conditions={}, opponent_side_conditions={})


def _check(state):
    assert len(state["my_active"]) == 2 and len(state["my_bench"]) == 1
    assert len(state["opp_active"]) == 2 and state["opp_active"][1] is None
    assert len(state["opp_seen"]) == 2
    assert state["opp_active"][0]["revealed_moves"] == ["Protect"]
    assert state["my_active"][0]["boosts"] == {"atk": 1}


def test_bc_player_state_to_dict():
    stub = NS(_canonical_move=lambda mid: mid.capitalize(),
              _canonical_species=lambda s: s.capitalize())
    _check(BCPlayer._state_to_dict(stub, _battle()))


def test_heuristic_dataset_state_from_battle():
    spec = importlib.util.spec_from_file_location(
        "gen_heur", os.path.join(ROOT, "tools", "generate_heuristic_dataset.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._canonical_move = lambda mid, enc: mid.capitalize()
    mod._canonical_species = lambda s, enc: s.capitalize()
    mod._canonical_item = lambda raw, enc: None
    mod._canonical_ability = lambda raw, enc: None
    _check(mod.state_from_battle(_battle(), encoder=None))


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
