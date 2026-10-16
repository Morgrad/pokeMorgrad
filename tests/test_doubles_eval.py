"""Behavioural tests for src/opp_model.py and src/doubles_eval.py.

Run: pytest tests/test_doubles_eval.py   (or: python tests/test_doubles_eval.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import damage, opp_model as O, doubles_eval as DE  # noqa: E402

GARCH = dict(atk=200, spa=100, spe=130, **{"def": 115, "spd": 105})


def attacker(**kw):
    return DE.Attacker(stats=dict(GARCH), types=["Dragon", "Ground"], **kw)


def foe(hp, max_hp=180, immune=None, types=("Fire", "Dark")):
    stats = {"hp": max_hp, "atk": 100, "def": 110, "spa": 90, "spd": 110, "spe": 80}
    return DE.Combatant([DE.Hypothesis(1.0, stats, max_hp, hp)], list(types),
                        immune_prob=immune or {})


def ally(hp, max_hp=180):
    c = foe(hp, max_hp, types=("Grass",))
    c.is_ally = True
    return c


def one_hit_rolls(move="dragonclaw", hp=180):
    ev = DE.Evaluator({0: attacker()}, {"o0": foe(hp)})
    return ev.rolls(DE.Action(0, move, ("o0",)), "o0", 0)


def test_opp_builds_weights_and_stats():
    b = O.opponent_builds("incineroar")
    assert abs(sum(x.weight for x in b) - 1.0) < 1e-9
    assert all(x.stats["hp"] > 0 and x.stats["def"] > 0 for x in b)
    assert O.opponent_builds("definitely-not-a-mon") == []


def test_opp_mega_form_resolves_and_falls_back_to_generic():
    assert O.resolve_species("salamencemega") == "Salamence-Mega"
    assert O.opponent_builds("salamencemega")


def test_immunity_prob():
    assert O.immunity_prob("x", "Fire", "flashfire") == 1.0
    assert O.immunity_prob("x", "Water", "intimidate") == 0.0


def test_focus_fire_beats_split_when_only_the_pair_kills():
    r = one_hit_rolls()
    hp = int(r.mean() * 1.5)                 # one hit can't KO, two always do
    assert r.max() < hp <= 2 * r.min()
    atk = {0: attacker(), 1: attacker()}
    ev = DE.Evaluator(atk, {"o0": foe(hp), "o1": foe(hp)})
    a0, a1 = DE.Action(0, "dragonclaw", ("o0",)), DE.Action(1, "dragonclaw", ("o1",))
    focus = DE.Action(1, "dragonclaw", ("o0",))
    assert ev.pair_value((a0, focus)) > ev.pair_value((a0, a1)) + 0.15   # worth ~ the KO bonus


def test_overkill_redirects_second_attacker():
    r = one_hit_rolls()
    atk = {0: attacker(), 1: attacker()}
    ev = DE.Evaluator(atk, {"o0": foe(hp=int(r.min() * 0.3)), "o1": foe(hp=180)})
    a0 = DE.Action(0, "dragonclaw", ("o0",))
    same = DE.Action(1, "dragonclaw", ("o0",))
    other = DE.Action(1, "dragonclaw", ("o1",))
    assert ev.pair_value((a0, other)) > ev.pair_value((a0, same))


def test_choose_pair_prefers_baseline_on_tie_and_finds_focus_fire():
    r = one_hit_rolls()
    hp = int(r.mean() * 1.5)
    atk = {0: attacker(), 1: attacker()}
    ev = DE.Evaluator(atk, {"o0": foe(hp), "o1": foe(hp)})
    a0o0, a0o1 = DE.Action(0, "dragonclaw", ("o0",)), DE.Action(0, "dragonclaw", ("o1",))
    a1o0, a1o1 = DE.Action(1, "dragonclaw", ("o0",)), DE.Action(1, "dragonclaw", ("o1",))
    ia, ib, best, base = DE.choose_pair(ev, [a0o0, a0o1], [a1o1, a1o0])
    assert (ia, ib) == (0, 1) and best > base            # slot b switched to the same target
    ia, ib, _, _ = DE.choose_pair(ev, [a0o0, a0o1], [a1o0])  # baseline already focus-fires
    assert (ia, ib) == (0, 0)


def test_spread_move_hurts_fragile_ally():
    atk = {0: attacker()}
    spread = DE.Action(0, "earthquake", ("o0", "o1", "a1"))
    foes_only = DE.Action(0, "rockslide", ("o0", "o1"))
    plain = ("Normal",)
    healthy = DE.Evaluator(atk, {"o0": foe(180, types=plain), "o1": foe(180, types=plain),
                                 "a1": ally(hp=180)})
    fragile = DE.Evaluator(atk, {"o0": foe(180, types=plain), "o1": foe(180, types=plain),
                                 "a1": ally(hp=1)}, ko_bonus=1.0)
    # EQ (100 BP) beats Rock Slide (75 BP) when the ally is healthy, loses once it would KO the ally
    assert healthy.pair_value((spread, None)) > healthy.pair_value((foes_only, None))
    assert fragile.pair_value((spread, None)) < fragile.pair_value((foes_only, None))


def test_ally_immune_to_spread_is_not_penalised():
    atk = {0: attacker()}
    spread = DE.Action(0, "earthquake", ("o0", "o1", "a1"))
    a = ally(hp=20)
    a.immune_prob = {"Ground": 1.0}
    ev_immune = DE.Evaluator(atk, {"o0": foe(180), "o1": foe(180), "a1": a})
    ev_exposed = DE.Evaluator(atk, {"o0": foe(180), "o1": foe(180), "a1": ally(hp=20)})
    assert ev_immune.pair_value((spread, None)) > ev_exposed.pair_value((spread, None))


def test_ability_immunity_zeroes_value():
    atk = {0: attacker()}
    act = DE.Action(0, "earthquake", ("o0",))
    ev = DE.Evaluator(atk, {"o0": foe(180, immune={"Ground": 1.0})})
    assert ev.pair_value((act, None)) == 0.0


def test_status_and_none_actions_are_free():
    ev = DE.Evaluator({0: attacker()}, {"o0": foe(180)})
    assert ev.pair_value((None, None)) == 0.0
    assert not ev.modelable("protect")
    assert ev.modelable("earthquake")


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
