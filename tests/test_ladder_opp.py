"""Tests for src/ladder_opp.py (real poke_env Pokemon / orders, no server).

Run: pytest tests/test_ladder_opp.py   (or: python tests/test_ladder_opp.py)
"""
import random
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from poke_env.battle import Move, Pokemon  # noqa: E402
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder  # noqa: E402

from src import opp_actions  # noqa: E402
from src.battle_memory import BattleMemory  # noqa: E402
from src.ladder_opp import LadderOpponent  # noqa: E402

STATS = dict(hp=180, atk=150, spa=90, spd=100, spe=100, **{"def": 110})


def mon(species, moves, first_turn=False):
    m = Pokemon(gen=9, species=species)
    m._stats, m._max_hp, m._current_hp = dict(STATS), 180, 180
    for mv in moves:
        m._add_move(mv)
    m._active_turns = 1 if first_turn else 3
    return m


def order(mid, code=0, mega=False):
    return SingleBattleOrder(Move(mid, gen=9), move_target=code, mega=mega)


def opp(fakeout=0.0, protect=0.0, seed=1):
    o = LadderOpponent.__new__(LadderOpponent)
    o.rng, o.stats_counter, o.memories = random.Random(seed), {"turns": 0, "protect": 0, "fakeout": 0, "errors": 0}, {}
    o.probs = opp_actions.ActionProbs(fakeout, protect)
    return o


def run(o, mons, valid, base):
    mem = BattleMemory()
    mem.turn = 3
    o.memories["tag"] = mem
    b = NS(battle_tag="tag", player_role="p1", active_pokemon=mons, valid_orders=valid)
    real, opp_actions.action_probs = opp_actions.action_probs, lambda ctx, rates=None: o.probs
    try:
        return o._humanise(b, base)
    finally:
        opp_actions.action_probs = real


def test_protect_replaces_the_heuristic_move_when_the_rate_says_so():
    m0, m1 = mon("garchomp", ["earthquake", "protect"]), mon("incineroar", ["flareblitz"])
    valid = [[order("earthquake", 1), order("protect")], [order("flareblitz", 1)]]
    base = DoubleBattleOrder(valid[0][0], valid[1][0])
    out = run(opp(protect=1.0), [m0, m1], valid, base)
    assert out.first_order.order.id == "protect" and out.second_order is base.second_order
    assert run(opp(protect=0.0), [m0, m1], valid, base) is base


def test_only_mons_that_carry_the_move_can_use_it():
    m0 = mon("garchomp", ["earthquake"])
    valid = [[order("earthquake", 1)], [order("earthquake", 2)]]
    base = DoubleBattleOrder(valid[0][0], valid[1][0])
    assert run(opp(protect=1.0, fakeout=1.0), [m0, None], valid, base) is base


def test_fake_out_only_on_the_first_turn_out():
    valid = [[order("closecombat", 1), order("fakeout", 1)], [order("flareblitz", 1)]]
    base = DoubleBattleOrder(valid[0][0], valid[1][0])
    fresh = [mon("lopunny", ["closecombat", "fakeout"], first_turn=True), mon("incineroar", ["flareblitz"])]
    old = [mon("lopunny", ["closecombat", "fakeout"], first_turn=False), mon("incineroar", ["flareblitz"])]
    assert run(opp(fakeout=1.0), fresh, valid, base).first_order.order.id == "fakeout"
    assert run(opp(fakeout=1.0), old, valid, base) is base


def test_switch_orders_are_left_alone_and_mega_flag_is_kept():
    m0 = mon("garchomp", ["earthquake", "protect"])
    switch = SingleBattleOrder(mon("rillaboom", []))
    base = DoubleBattleOrder(switch, order("earthquake", 1))
    assert run(opp(protect=1.0), [m0, mon("incineroar", [])], [[switch], [order("earthquake", 1)]], base) is base
    valid = [[order("earthquake", 1, mega=True), order("protect", mega=True), order("protect")], [order("earthquake", 2)]]
    out = run(opp(protect=1.0), [m0, None], valid, DoubleBattleOrder(valid[0][0], valid[1][0]))
    assert out.first_order.order.id == "protect" and out.first_order.mega


def test_rate_matches_the_fitted_probability_over_many_draws():
    m0 = mon("garchomp", ["earthquake", "protect"])
    valid = [[order("earthquake", 1), order("protect")], [order("earthquake", 2)]]
    base = DoubleBattleOrder(valid[0][0], valid[1][0])
    o = opp(protect=0.25, seed=7)
    n = sum(run(o, [m0, None], valid, base) is not base for _ in range(4000))
    assert abs(n / 4000 - 0.25) < 0.03


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print(f"PASS {n}")

