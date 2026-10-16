"""VGCPilot Mega step on synthetic orders (no server)."""
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, ".")
from poke_env.battle import Move
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder

from src.vgc_pilot import add_mega, mega_variant


def mv(i):
    return Move(i, gen=9)


def so(i, target=0, mega=False):
    return SingleBattleOrder(mv(i), move_target=target, mega=mega)


def battle(can, valid):
    return NS(can_mega_evolve=can, valid_orders=valid)


def test_variant_matches_move_and_target():
    valid = [so("closecombat", 1), so("closecombat", 1, True), so("closecombat", 2, True)]
    assert mega_variant(so("closecombat", 1), valid).move_target == 1
    assert mega_variant(so("closecombat", 2), valid).mega
    assert mega_variant(so("protect"), valid) is None
    assert mega_variant(so("closecombat", 1, True), valid) is None


def test_mega_added_to_first_capable_slot_only():
    v0 = [so("protect"), so("protect", 0, True)]
    v1 = [so("closecombat", 1), so("closecombat", 1, True)]
    base = DoubleBattleOrder(so("protect"), so("closecombat", 1))
    out, slot = add_mega(battle([True, True], [v0, v1]), base, True)
    assert slot == 0 and out.first_order.mega and not out.second_order.mega


def test_skips_slot_that_cannot_mega_or_switches():
    v1 = [so("closecombat", 1), so("closecombat", 1, True)]
    base = DoubleBattleOrder(so("protect"), so("closecombat", 1))
    out, slot = add_mega(battle([False, True], [[so("protect")], v1]), base, True)
    assert slot == 1 and out.second_order.mega and not out.first_order.mega


def test_no_mega_when_used_or_unavailable():
    v = [[so("protect"), so("protect", 0, True)], [so("protect")]]
    base = DoubleBattleOrder(so("protect"), so("protect"))
    assert add_mega(battle([True, False], v), base, False) == (base, None)
    assert add_mega(battle([False, False], v), base, True) == (base, None)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("PASS")
