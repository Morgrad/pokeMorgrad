"""Behavioural tests for src/speed_model.py (and opp_model.ability_distribution).

Run: pytest tests/test_speed_model.py   (or: python tests/test_speed_model.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import opp_model as O  # noqa: E402
from src import speed_model as S

M = S.SpeedMods


def belief(*pairs):
    return S.SpeedBelief([S.SpeedHypothesis(w, stat, ab) for w, stat, ab in pairs])


def test_effective_speed_modifiers():
    assert S.effective_speed(100) == 100
    assert S.effective_speed(100, M(stage=1)) == 150
    assert S.effective_speed(100, M(stage=-2)) == 50
    assert S.effective_speed(100, M(tailwind=True)) == 200
    assert S.effective_speed(100, M(paralyzed=True)) == 50
    assert S.effective_speed(100, M(scarf=True)) == 150
    assert S.effective_speed(100, M(tailwind=True, paralyzed=True)) == 100


def test_speed_abilities_need_their_condition():
    assert S.effective_speed(100, M(weather="rain"), "swiftswim") == 200
    assert S.effective_speed(100, M(weather="sun"), "swiftswim") == 100
    assert S.effective_speed(100, M(weather="sun"), "chlorophyll") == 200
    assert S.effective_speed(100, M(terrain="electric"), "surgesurfer") == 200
    assert S.effective_speed(100, M(weather="rain"), None) == 100


def test_p_faster_certain_tie_and_trick_room():
    b = belief((1.0, 100, None))
    assert b.p_faster(101) == 1.0
    assert b.p_faster(99) == 0.0
    assert b.p_faster(100) == 0.5
    assert b.p_faster(101, trick_room=True) == 0.0
    assert b.p_faster(99, trick_room=True) == 1.0
    assert b.p_faster(100, trick_room=True) == 0.5


def test_p_faster_mixture_is_weighted():
    b = belief((0.7, 150, None), (0.3, 90, None))
    assert abs(b.p_faster(100) - 0.3) < 1e-9
    assert abs(b.p_faster(100, trick_room=True) - 0.7) < 1e-9


def test_p_faster_applies_opponent_mods_and_ability_branches():
    b = belief((0.5, 100, "swiftswim"), (0.5, 100, None))
    assert abs(b.p_faster(150) - 1.0) < 1e-9
    assert abs(b.p_faster(150, M(weather="rain")) - 0.5) < 1e-9
    assert abs(b.p_faster(150, M(tailwind=True)) - 0.0) < 1e-9


def test_empty_belief_is_a_coin_flip():
    assert not S.SpeedBelief([])
    assert S.SpeedBelief([]).p_faster(100) == 0.5


def test_belief_for_real_species():
    b = S.belief_for("incineroar")
    assert b and abs(sum(h.weight for h in b.hypotheses) - 1.0) < 1e-9
    assert all(h.stat > 0 for h in b.hypotheses)
    assert not S.belief_for("definitely-not-a-mon")
    fast = S.effective_speed(500)
    assert S.belief_for("incineroar").p_faster(fast) == 1.0


def test_known_ability_collapses_distribution():
    assert O.ability_distribution("incineroar", "Intimidate") == {"intimidate": 1.0}
    dist = O.ability_distribution("incineroar")
    assert abs(sum(dist.values()) - 1.0) < 1e-9
    assert all(h.ability == "swiftswim" for h in S.belief_for("pelipper", "Swift Swim").hypotheses)


def test_mega_form_gets_its_mega_ability_not_the_paste_ability():
    assert O.ability_distribution("Golisopod-Mega") == {"toughclaws": 1.0}
    assert O.ability_distribution("Golisopod") == {"emergencyexit": 1.0}


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
