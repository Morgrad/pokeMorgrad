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


def test_score_picks_the_better_mega_when_both_can():
    v = [[so("protect"), so("protect", 0, True)], [so("closecombat", 1), so("closecombat", 1, True)]]
    base = DoubleBattleOrder(so("protect"), so("closecombat", 1))
    out, slot = add_mega(battle([True, True], v), base, True, score=lambda sl: (10, 0) if sl == 1 else (5, 0))
    assert slot == 1 and out.second_order.mega and not out.first_order.mega
    out, slot = add_mega(battle([True, True], v), base, True, score=lambda sl: (5, 9) if sl == 0 else (5, 1))
    assert slot == 0


def test_pilot_reads_taunt_and_trick_room_turns_from_memory():
    from src.battle_memory import BattleMemory
    from src.vgc_pilot import VGCPilot
    mem = BattleMemory()
    for line in ("|switch|p2a: Milotic|Milotic, L50|100/100", "|turn|3", "|-start|p2a: Milotic|move: Taunt",
                 "|-fieldstart|move: Trick Room|[of] p2a: Milotic"):
        mem.feed(line.split("|"))
    pilot = VGCPilot.__new__(VGCPilot)
    pilot.memory_for = lambda battle: mem
    b = NS(player_role="p1")
    assert pilot._taunt_left(NS(name="Milotic"), b) == 3
    assert pilot._trick_room_left(b) == 5
    mem.feed("|turn|6".split("|"))
    assert pilot._taunt_left(NS(name="Milotic"), b) == 0 and pilot._trick_room_left(b) == 2


if __name__ == "__main__":
    failed = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f()
                print(f"PASS {n}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {n}: {e!r}")
    sys.exit(1 if failed else 0)
