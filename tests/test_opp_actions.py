"""Foe Protect / Fake Out probabilities: foe_ctx features at both call conventions, action_probs shape."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import battle_memory as B  # noqa: E402
from src import opp_actions as O  # noqa: E402

# small hand-made tables in the shape tools/build_opp_actions.py writes
RATES = {
    "protect": {
        "cells": {"new|a0|h2": 0.10, "new|a2|h2": 0.09, "rev|c0|a1|h2": 0.24, "rev|c1|a1|h2": 0.05},
        "parents": {"new|a0": 0.10, "new|a1": 0.10, "new|a2": 0.09, "new|a3": 0.08,
                    "rev|c0|a1": 0.24, "rev|c0|a0": 0.26, "rev|c1|a1": 0.05, "rev|c2|a1": 0.2},
        "species_rel": {"Grimmsnarl": 0.02, "Gengar": 3.0}},
    "fakeout": {
        "cells": {"new|lead": 0.075, "new|back": 0.10, "rev|back": 0.53},
        "parents": {"new": 0.08, "rev": 0.53},
        "species_rel": {"Incineroar": 5.0, "Garchomp": 0.01}},
    "trickroom": {
        "cells": {"new|a0": 0.02, "new|a1": 0.01, "rev|a0": 0.21, "rev|a1": 0.14},
        "parents": {"new": 0.01, "rev": 0.15},
        "species_rel": {"Hatterene": 8.0, "Garchomp": 0.0}},
}


def ctx(**kw):
    d = dict(species="Sableye", turn=3, age=2, lead=False, known_moves=frozenset(), moves_complete=False,
             protect_chain=0, protect_uses=0, hp_frac=1.0)
    d.update(kw)
    return O.FoeCtx(**d)


def probs(**kw):
    return O.action_probs(ctx(**kw), RATES)


def test_fakeout_needs_age_zero():
    assert probs(age=0, species="Incineroar", lead=True).fakeout > 0.3
    for a in (1, 2, 5):
        assert probs(age=a, species="Incineroar", known_moves=frozenset({"fakeout"})).fakeout == 0.0


def test_moves_complete_removes_absent_moves():
    p = probs(age=0, moves_complete=True, known_moves=frozenset({"surf", "icywind"}))
    assert p.fakeout == 0.0 and p.protect == 0.0
    p = probs(age=0, moves_complete=True, known_moves=frozenset({"fakeout", "protect"}))
    assert p.fakeout > 0.3 and p.protect > 0.1
    # an unrevealed move in an incomplete set stays possible
    assert probs(age=0, known_moves=frozenset({"surf"})).protect > 0.05


def test_revealed_protect_chain_is_low_and_gap_is_high():
    after_chain = probs(known_moves=frozenset({"protect"}), protect_uses=1, protect_chain=1, age=2).protect
    gap = probs(known_moves=frozenset({"protect"}), protect_uses=1, protect_chain=0, age=2).protect
    assert after_chain < 0.08 < 0.2 < gap
    # protect_uses alone also reveals it, and the species factor is moot once revealed
    assert probs(protect_uses=2, species="Grimmsnarl", age=2).protect == gap
    assert probs(species="Grimmsnarl", age=2).protect < 0.01 < probs(species="Gengar", age=2).protect


def test_revealed_fakeout_high_and_species_factor():
    rev = probs(age=0, known_moves=frozenset({"fakeout"}), species="Garchomp").fakeout
    assert 0.4 < rev < 0.6                      # the factor does not apply once revealed
    assert probs(age=0, species="Garchomp").fakeout < 0.01
    assert probs(age=0, species="Incineroar", lead=True).fakeout > probs(age=0, species="Sableye", lead=True).fakeout * 4


def test_probabilities_are_valid_and_jointly_bounded():
    for sp in ("Incineroar", "Gengar", "Sableye", "Nobody"):
        for age in (0, 1, 3):
            for km in (frozenset(), frozenset({"fakeout"}), frozenset({"protect", "fakeout"})):
                for chain in (0, 1, 2):
                    for hp in (0.1, 0.7, 1.0):
                        p = probs(species=sp, age=age, known_moves=km, protect_chain=chain,
                                  protect_uses=1 if chain else 0, hp_frac=hp, lead=age == 0)
                        assert 0.0 <= p.fakeout <= 1.0 and 0.0 <= p.protect <= 1.0
                        assert p.fakeout + p.protect <= O.MAX_P + 1e-9
    # a huge species factor on both is renormalised, not clipped past 1
    r = {"protect": {"cells": {}, "parents": {"new|a0": 0.5}, "species_rel": {"X": 5.0}},
         "fakeout": {"cells": {}, "parents": {"new": 0.5}, "species_rel": {"X": 5.0}}}
    p = O.action_probs(ctx(species="X", age=0, lead=True), r)
    assert abs(p.fakeout + p.protect - O.MAX_P) < 1e-9 and abs(p.fakeout - p.protect) < 1e-9


def test_unknown_cell_falls_back_to_parent():
    p = probs(age=0, hp_frac=0.3)               # 'new|a0|h0' is not in the cells, its parent is
    assert abs(p.protect - 0.10) < 1e-9


TEXT = """
|switch|p1a: A|Incineroar, L50, M|100/100
|switch|p1b: B|Rillaboom, L50, M|100/100
|switch|p2a: C|Sableye, L50, M|100/100
|switch|p2b: D|Swampert, L50, M|100/100
|turn|1
|move|p1a: A|Fake Out|p2a: C
|move|p1b: B|Protect|p1b: B
|-singleturn|p1b: B|Protect
|move|p2b: D|Protect|p2b: D
|-singleturn|p2b: D|Protect
|turn|2
|move|p1b: B|Protect|p1b: B
|-singleturn|p1b: B|move: Protect
|move|p2b: D|Surf|p1a: A
|switch|p2a: E|Gengar, L50, M|100/100
|turn|3"""


def feed_to(text, stop_before_turn=None):
    m = B.BattleMemory()
    for line in text.strip().split("\n"):
        if stop_before_turn and line == f"|turn|{stop_before_turn}":
            break
        m.feed(line.strip().split("|"))
    return m


def test_foe_ctx_both_call_conventions_agree():
    fit_mem = feed_to(TEXT, stop_before_turn=3)       # fitting tool: before |turn|3, mem.turn == 2
    pilot_mem = feed_to(TEXT)                         # pilot: after |turn|3, mem.turn == 3
    assert fit_mem.turn == 2 and pilot_mem.turn == 3
    who = (("A", "p1"), ("B", "p1"), ("D", "p2"), ("E", "p2"))
    for name, side in who:
        assert O.foe_ctx(fit_mem, side, name, 3) == O.foe_ctx(pilot_mem, side, name, 3)
    c = {n: O.foe_ctx(pilot_mem, s, n, 3) for n, s in who}
    assert c["A"].age == 2 and not c["A"].lead and c["A"].known_moves == {"fakeout"}
    assert c["A"].species == "Incineroar" and c["A"].turn == 3
    assert c["B"].protect_chain == 2 and c["B"].protect_uses == 2 and c["B"].age == 2
    assert c["D"].protect_chain == 0 and c["D"].protect_uses == 1          # Surf broke the chain
    assert c["D"].known_moves == {"protect", "surf"}
    assert c["E"].age == 0 and c["E"].protect_uses == 0 and c["E"].known_moves == frozenset()
    assert O.protect_revealed(c["D"]) and not O.protect_revealed(c["E"])


def test_foe_ctx_turn_one_and_earlier_turns():
    m = feed_to(TEXT, stop_before_turn=1)
    c = O.foe_ctx(m, "p1", "A", 1)
    assert c.lead and c.age == 0 and c.known_moves == frozenset() and c.protect_chain == 0
    m = feed_to(TEXT, stop_before_turn=2)
    b2 = O.foe_ctx(m, "p1", "B", 2)
    assert b2.protect_chain == 1 and b2.age == 1 and b2.known_moves == {"protect"}
    # the chain only counts when the last Protect was on the previous turn
    full = feed_to(TEXT)
    assert O.foe_ctx(full, "p1", "B", 3).protect_chain == 2
    assert O.foe_ctx(full, "p1", "B", 4).protect_chain == 0
    # known_moves passed in (e.g. from an Open Team Sheet) is merged with what was seen
    c = O.foe_ctx(full, "p2", "E", 3, known_moves=("Fake Out", "Shadow Ball"), moves_complete=True, hp_frac=0.5)
    assert c.known_moves == {"fakeout", "shadowball"} and c.moves_complete and c.hp_frac == 0.5


def test_real_rates_file_if_present():
    if not O.RATES_PATH.exists():
        return
    r = O._rates()
    p = O.action_probs(ctx(species="Incineroar", age=0, lead=True), r)
    q = O.action_probs(ctx(species="Garchomp", age=0, lead=True), r)
    assert p.fakeout > 0.3 > 0.05 > q.fakeout
    assert O.action_probs(ctx(age=3), r).fakeout == 0.0


def test_trick_room_rate_uses_reveal_age_and_species_until_revealed():
    base = probs(species="Hatterene", age=1).trickroom
    assert base > probs(species="Sableye", age=1).trickroom * 5
    rev = probs(species="Hatterene", age=1, known_moves=frozenset({"trickroom"})).trickroom
    assert abs(rev - 0.14) < 1e-9                              # revealed: the species factor is moot
    assert probs(species="Hatterene", age=1, known_moves=frozenset({"trickroom"}), moves_complete=True).trickroom > 0
    assert probs(species="Hatterene", age=1, moves_complete=True).trickroom == 0.0     # full set without it


def test_trick_room_fits_inside_the_leftover_probability():
    p = probs(species="Hatterene", known_moves=frozenset({"trickroom", "fakeout"}), age=0)
    assert p.fakeout + p.protect + p.trickroom <= O.MAX_P + 1e-9
    legacy = {k: v for k, v in RATES.items() if k != "trickroom"}
    assert O.action_probs(ctx(), legacy).trickroom == 0.0


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("PASS")
