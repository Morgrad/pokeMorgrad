"""Foe Mega prediction: candidates from memory, rate table, speed/damage mixtures."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import battle_memory as B  # noqa: E402
from src import mega_model as M  # noqa: E402
from src import speed_model as S  # noqa: E402


def feed(text):
    m = B.BattleMemory()
    for line in text.strip().split("\n"):
        m.feed(line.strip().split("|"))
    return m


LEADS = """
|switch|p2a: Garchomp|Garchomp, L50, M|100/100
|switch|p2b: Incineroar|Incineroar, L50, M|100/100
|switch|p1a: X|Tyranitar, L50|100/100
|switch|p1b: Y|Sableye, L50|100/100
|turn|1"""


def test_active_tracking_and_candidates():
    m = feed(LEADS)
    assert [r.name for r in m.active_mons("p2")] == ["Garchomp", "Incineroar"]
    cs = M.candidates(m, "p2")
    assert [c["name"] for c in cs] == ["Garchomp"] and cs[0]["k"] == 0 and cs[0]["lead"]
    both = M.candidates(m, "p1")           # Tyranitar and Sableye both have Mega forms
    assert [c["name"] for c in both] == ["X", "Y"] and both[0]["ncand"] == 2


def test_k_grows_and_switch_in_resets():
    m = feed(LEADS + "\n|turn|2\n|turn|3")
    assert M.candidates(m, "p2")[0]["k"] == 2
    m = feed(LEADS + "\n|turn|2\n|switch|p2a: Charizard|Charizard, L50|100/100\n|turn|3")
    c = [x for x in M.candidates(m, "p2") if x["name"] == "Charizard"][0]
    assert c["k"] == 0 and not c["lead"]


def test_no_candidates_after_mega_or_when_fainted():
    m = feed(LEADS + "\n|detailschange|p2a: Garchomp|Garchomp-Mega-Z, L50\n|-mega|p2a: Garchomp|Garchomp|Garchompite Z\n|turn|2")
    assert M.candidates(m, "p2") == [] and M.foe_mega_probs(m, "p2") == {}
    m = feed(LEADS + "\n|faint|p2a: Garchomp")
    assert M.candidates(m, "p2") == []


def test_probability_shape():
    p0 = M.p_mega_now("", 0, 1, True)
    assert 0.5 < p0 < 0.8
    assert M.p_mega_now("", 1, 1, True) < p0 and M.p_mega_now("", 3, 1, True) < M.p_mega_now("", 1, 1, True)
    assert M.p_mega_now("", 0, 2, True) < p0
    assert M.p_mega_now("Garchomp", 0, 1, True, item="sitrusberry") == 0.0
    assert M.p_mega_now("Garchomp", 0, 1, True, consumed=True) == M.CONSUMED_P
    assert M.p_mega_now("Excadrill", 0, 1, True) < 0.2 < M.p_mega_now("Blastoise", 0, 1, True)


def test_side_probabilities_sum_to_at_most_one():
    m = feed("""
|switch|p2a: A|Charizard, L50|100/100
|switch|p2b: B|Blastoise, L50|100/100
|turn|1""")
    ps = M.foe_mega_probs(m, "p2", rates={"cells": {"k0_lead|2": 0.9}, "species_rel": {}, "hold_floor": 0.8})
    assert abs(sum(ps.values()) - 1.0) < 1e-9


def test_conditional_q_and_speed_mixture():
    assert M.conditional_q(0.5, 1.0) == 0.5 and M.conditional_q(0.9, 0.6) == 1.0 and M.conditional_q(0.3, 0) == 0.0
    b = S.belief_for("Garchomp")
    mass = sum(h.weight for h in b.hypotheses if h.mega_stat)
    assert 0.3 < mass <= 1.0
    pre, post = b.p_faster(170, mega=0.0), b.p_faster(170, mega=True)
    assert post < pre                      # Mega Garchomp-Z is faster than 170 on some sets
    mid = b.p_faster(170, mega=0.5 * mass)
    assert min(pre, post) < mid < max(pre, post)
    assert abs(sum(w for w, _ in b.speeds(mega=0.4)) - 1.0) < 1e-9


def test_mega_gain():
    off, spe = M.mega_gain("Garchomp", "garchompitez")
    assert off == 11 and spe == 49          # best offence 130 -> 141; Spe 102 -> 151
    assert M.mega_gain("Garchomp", "lifeorb") is None
    assert M.mega_gain("Charizard", "charizarditex")[0] > 0


def _foe(species, q):
    from types import SimpleNamespace as NS

    from poke_env.battle import Pokemon

    from src.doubles_pilot import DoublesPilot
    return DoublesPilot._foe(NS(_mega_prob=lambda mon: q), Pokemon(gen=9, species=species))


def test_foe_hypotheses_carry_mega_types_and_ability_immunity():
    pre, half, full = _foe("garchomp", 0.0), _foe("garchomp", 0.5), _foe("garchomp", 1.0)
    assert all(h.types is None for h in pre.hyps) and pre.types == ["Dragon", "Ground"]
    assert pre.immune_prob.get("Ground", 0.0) < 0.05          # pre-Mega Garchomp is not a Levitator
    assert abs(sum(h.weight for h in half.hyps) - 1.0) < 1e-9
    mega_w = sum(h.weight for h in half.hyps if h.types == ["Dragon"])
    assert abs(mega_w - 0.5) < 1e-6                            # marginal P(Mega now) is preserved by the split
    assert full.immune_prob["Ground"] > half.immune_prob["Ground"] > pre.immune_prob.get("Ground", 0.0)
    assert any(h.types == ["Dragon"] for h in full.hyps)


def test_hypothesis_types_change_the_damage_roll():
    from src import doubles_eval as DE
    stats = {"hp": 180, "atk": 100, "def": 110, "spa": 90, "spd": 110, "spe": 80}
    atk = DE.Attacker(stats={"hp": 200, "atk": 200, "def": 115, "spa": 100, "spd": 105, "spe": 130}, types=["Normal"])
    tgt = DE.Combatant([DE.Hypothesis(0.5, stats, 180, 180), DE.Hypothesis(0.5, stats, 180, 180, types=["Fairy"])],
                       ["Normal"])
    ev = DE.Evaluator({0: atk}, {"o0": tgt})
    act = DE.Action(0, "dragonclaw", ("o0",))
    assert ev.rolls(act, "o0", 0).max() > 0
    assert ev.rolls(act, "o0", 1).max() == 0                  # Dragon cannot hurt the Fairy-typed Mega hypothesis


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print(f"PASS {n}")

