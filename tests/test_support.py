"""Support-move layer (src/support_value.py + its use in doubles_eval / turn_sim / DoublesPilot).

Run: pytest tests/test_support.py   (or: python tests/test_support.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from poke_env.player.battle_order import DoubleBattleOrder  # noqa: E402

from src import doubles_eval as DE  # noqa: E402
from src import support_value as SV  # noqa: E402
from src import turn_sim as TS  # noqa: E402

STATS = {"hp": 180, "atk": 150, "def": 110, "spa": 150, "spd": 110, "spe": 100}
ALL = SV.parse_effects("all")


def hyp(**kw):
    return DE.Hypothesis(1.0, {**STATS, **kw}, 180, 180)


def foe(**kw):
    return DE.Combatant([hyp(**kw)], ["Normal"])


def mine(cur=180):
    return DE.Combatant([DE.Hypothesis(1.0, dict(STATS), 180, cur)], ["Normal"], is_ally=True)


def atk(**kw):
    return DE.Attacker(stats={**STATS, "atk": 200}, types=["Normal"], **kw)


def sim(foes, speeds=(200, 200), effects=ALL, cands=None, world=None, **kw):
    world = world or {"o0": foe(), "a0": mine(), "a1": mine()}
    ts = TS.TurnSim({0: atk(), 1: atk()}, world, dict(enumerate(speeds)), foes, effects=effects, **kw)
    if cands is not None:
        ts.set_candidates(cands)
    return ts


def fi(speed, moves=("hypervoice",), **kw):
    return TS.FoeInfo(list(moves), [(1.0, speed)], **kw)


def A(slot, move, *targets):
    return DE.Action(slot, move, tuple(targets))


# ---- pure data side ------------------------------------------------------------------------------

def test_parse_effects():
    assert SV.parse_effects("") == frozenset() and SV.parse_effects("off") == frozenset()
    assert SV.parse_effects("all") == frozenset(SV.EFFECTS)
    assert SV.parse_effects("snarl, taunt") == {"snarl", "taunt"}
    try:
        SV.parse_effects("snarl,bogus")
    except ValueError:
        return
    raise AssertionError("unknown effect accepted")


def test_move_classification_comes_from_the_db():
    assert SV.effect_of("foulplay") == "foulplay" and SV.is_foulplay("foulplay")
    assert SV.effect_of("snarl") == "snarl" and SV.pure_kind("snarl") is None
    assert SV.effect_of("charm") == "charm" and SV.pure_kind("charm") == "drop"
    assert SV.effect_of("helpinghand") == "helpinghand" and SV.effect_of("taunt") == "taunt"
    assert SV.effect_of("closecombat") is None and SV.effect_of("toxic") is None
    assert SV.foe_drop("snarl").deltas == (("spa", -1),)
    assert SV.foe_drop("charm").deltas == (("atk", -2),)
    assert SV.pure_enabled("charm", frozenset({"charm"})) and not SV.pure_enabled("charm", frozenset({"snarl"}))


def test_drop_outcomes_fold_in_abilities():
    charm = SV.foe_drop("charm")
    assert SV.drop_outcomes(charm, None) == [(1.0, -2, 0)]
    assert SV.drop_outcomes(charm, {"clearbody": 1.0}) == [(1.0, 0, 0)]
    assert SV.drop_outcomes(charm, {"hypercutter": 1.0}) == [(1.0, 0, 0)]
    assert SV.drop_outcomes(charm, {"contrary": 1.0}) == [(1.0, 2, 0)]
    assert SV.drop_outcomes(charm, {"simple": 1.0}) == [(1.0, -4, 0)]
    assert SV.drop_outcomes(charm, {"defiant": 1.0}) == [(1.0, 0, 0)]            # -2 then +2
    snarl = SV.foe_drop("snarl")
    assert SV.drop_outcomes(snarl, {"competitive": 1.0}) == [(1.0, 0, 1)]        # -1 then +2
    assert SV.drop_outcomes(snarl, {"shielddust": 1.0}) == [(1.0, 0, 0)]
    assert SV.drop_outcomes(charm, {"shielddust": 1.0}) == [(1.0, -2, 0)]        # Shield Dust only stops secondaries
    assert SV.drop_outcomes(charm, {"magicbounce": 1.0}) == [(1.0, 0, 0)]
    mix = {(a, b): p for p, a, b in SV.drop_outcomes(charm, {"clearbody": 0.25, None: 0.75})}
    assert abs(mix[(-2, 0)] - 0.75) < 1e-9 and abs(mix[(0, 0)] - 0.25) < 1e-9
    assert SV.shifted(5, 3) == 6 and SV.shifted(-5, -4) == -6


# ---- Foul Play ----------------------------------------------------------------------------------------

def test_foul_play_uses_the_targets_attack_only_when_enabled():
    world = {"o0": foe(atk=300), "a0": mine()}
    low = DE.Attacker(stats={**STATS, "atk": 50}, types=["Dark"])
    a = A(0, "foulplay", "o0")
    on = DE.Evaluator({0: low}, world, effects=frozenset({"foulplay"})).rolls(a, "o0", 0)
    off = DE.Evaluator({0: low}, world).rolls(a, "o0", 0)
    assert on.mean() > 3 * off.mean()
    world["o0"].boosts["atk"] = -2
    dropped = DE.Evaluator({0: low}, world, effects=frozenset({"foulplay"})).rolls(a, "o0", 0)
    assert dropped.mean() < on.mean() / 1.5


# ---- identity -------------------------------------------------------------------------------------------

def test_layer_is_identity_without_support_actions():
    world = {"o0": foe(), "o1": foe(), "a0": mine(), "a1": mine()}
    foes = {"o0": fi(150, fakeout=0.3, protect=0.2, trickroom=0.4), "o1": fi(80, protect=0.1)}
    pair = (A(0, "bodyslam", "o0"), A(1, "bodyslam", "o1"))
    cands = {0: [pair[0], A(0, "protect")], 1: [pair[1], None]}
    on, off = sim(foes, world=world, cands=cands), sim(foes, world=world, effects=frozenset(), cands=cands)
    for acts in (pair, (pair[0], None), (A(0, "protect"), pair[1])):
        assert abs(on.pair_value(acts) - off.pair_value(acts)) < 1e-12
    assert not on._tr_active


# ---- Snarl / Charm --------------------------------------------------------------------------------------

def test_snarl_value_grows_when_the_foe_is_special_and_we_move_first():
    world = {"o0": foe(), "a0": mine(), "a1": mine()}
    a = A(0, "snarl", "o0")
    gains = {}
    for name, spe in (("fast", 100), ("slow", 300)):
        foes = {"o0": fi(spe, ("hypervoice",))}
        on, off = sim(foes, world=world, effects=frozenset({"snarl"})), sim(foes, world=world, effects=frozenset())
        gains[name] = on.pair_value((a, None)) - off.pair_value((a, None))
    assert gains["slow"] > 0.0                                  # persistence
    assert gains["fast"] > gains["slow"] + 1e-6                 # plus the in-turn effect when we move first


def test_snarl_does_nothing_against_a_physical_foe_or_a_blocker():
    world = {"o0": foe(), "a0": mine(), "a1": mine()}
    a = A(0, "snarl", "o0")
    off = sim({"o0": fi(100, ("bodyslam",))}, world=world, effects=frozenset()).pair_value((a, None))
    on = sim({"o0": fi(100, ("bodyslam",))}, world=world, effects=frozenset({"snarl"})).pair_value((a, None))
    assert abs(on - off) < 1e-9
    blocked = sim({"o0": fi(100, ("hypervoice",), abilities={"clearbody": 1.0})}, world=world,
                  effects=frozenset({"snarl"})).pair_value((a, None))
    base = sim({"o0": fi(100, ("hypervoice",))}, world=world, effects=frozenset()).pair_value((a, None))
    assert abs(blocked - base) < 1e-9


def test_charm_is_worth_a_turn_against_a_strong_physical_foe_but_not_a_defiant_one():
    world = {"o0": foe(atk=300), "a0": mine(), "a1": mine()}
    charm = A(0, "charm", "o0")
    kw = dict(world=world, effects=frozenset({"charm"}))
    plain = sim({"o0": fi(100, ("bodyslam",))}, **kw)
    assert plain.pair_value((charm, None)) > plain.pair_value((None, None))
    defiant = sim({"o0": fi(100, ("bodyslam",), abilities={"defiant": 1.0})}, **kw)
    assert abs(defiant.pair_value((charm, None)) - defiant.pair_value((None, None)) + SV.SUPPORT_COST) < 1e-9


def test_pure_support_pays_the_tempo_cost():
    world = {"o0": foe(), "a0": mine(), "a1": mine()}
    s = sim({"o0": TS.FoeInfo([], [(1.0, 100)])}, world=world, effects=frozenset({"charm"}))
    assert abs(s.pair_value((A(0, "charm", "o0"), None)) + SV.SUPPORT_COST) < 1e-9


# ---- Helping Hand ---------------------------------------------------------------------------------------

def test_helping_hand_boosts_the_partners_attack_and_acts_first():
    world = {"o0": foe(), "a0": mine(), "a1": mine()}
    s = sim({"o0": TS.FoeInfo([], [(1.0, 100)])}, speeds=(50, 50), world=world, support_cost=0.0,
            effects=frozenset({"helpinghand"}))
    hit = A(0, "bodyslam", "o0")
    hh = A(1, "helpinghand")
    assert s.pair_value((hit, hh)) > 1.4 * s.pair_value((hit, None))          # x1.5 on ~one third of HP, also when slower
    assert abs(s.pair_value((None, hh))) < 1e-12


# ---- Taunt vs Trick Room --------------------------------------------------------------------------------

def test_taunt_denies_a_likely_trick_room_only_when_it_hurts_us():
    weak = DE.Combatant([DE.Hypothesis(1.0, dict(STATS), 180, 25)], ["Normal"])      # our hit KOs it; its hit KOs ours
    world = {"o0": weak, "a0": mine(cur=20), "a1": mine(cur=20)}
    fast_us, slow_us = (250, 250), (30, 30)
    for speeds, good in ((fast_us, True), (slow_us, False)):
        foes = {"o0": fi(100, ("bodyslam",), trickroom=0.8)}
        hit = A(1, "bodyslam", "o0")
        cands = {0: [A(0, "taunt", "o0"), None], 1: [hit]}
        s = sim(foes, speeds=speeds, world=world, cands=cands, support_cost=0.0)
        assert s._tr_active
        gain = s.pair_value((A(0, "taunt", "o0"), hit)) - s.pair_value((None, hit))
        assert (gain > 0.05) if good else (gain < 0.0)


def test_taunt_is_inert_when_trick_room_is_up_or_the_foe_cannot_set_it():
    world = {"o0": foe(), "a0": mine(), "a1": mine()}
    cands = {0: [A(0, "taunt", "o0"), None], 1: [None]}
    up = sim({"o0": fi(100, trickroom=0.8)}, world=world, cands=cands, trick_room=True)
    assert not up._tr_active
    none = sim({"o0": fi(100, trickroom=0.0)}, world=world, cands=cands, support_cost=0.0)
    assert abs(none.pair_value((A(0, "taunt", "o0"), None)) - none.pair_value((None, None))) < 1e-12


def test_a_taunted_foe_cannot_protect_or_set_trick_room():
    world = {"o0": foe(), "a0": mine(), "a1": mine()}
    cands = {0: [A(0, "taunt", "o0"), None], 1: [None]}
    free = sim({"o0": fi(100, protect=0.3, trickroom=0.5)}, world=world, cands=cands)
    assert {k for k, _, _ in free._kinds["o0"]} == {"atk", "protect", "tr"}
    held = sim({"o0": fi(100, protect=0.3, trickroom=0.5, taunt_left=2)}, world=world, cands=cands)
    assert [k for k, _, _ in held._kinds["o0"]] == ["atk"]


def test_trick_room_turns_left_is_kept_only_while_it_is_up():
    world = {"o0": foe(), "a0": mine(), "a1": mine()}
    assert sim({"o0": fi(100)}, world=world, trick_room=True, tr_left=3).tr_left == 3
    assert sim({"o0": fi(100)}, world=world, tr_left=3).tr_left == 0


def test_shortlist_keeps_every_support_candidate():
    world = {"o0": foe(), "a0": mine(), "a1": mine()}
    acts = [A(0, "bodyslam", "o0"), A(0, "charm", "o0"), A(0, "taunt", "o0"), A(0, "helpinghand")] + \
        [A(0, "hypervoice", "o0")] * 3
    s = sim({"o0": fi(100)}, world=world)
    assert {1, 2, 3} <= set(s.shortlist(acts, 1))


# ---- pilot wiring -----------------------------------------------------------------------------------------

def test_pilot_builds_support_candidates_and_counts_them():
    from poke_env.battle import Move
    from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder

    from tests.test_turn_sim import _battle, _mon, _pilot
    stats = dict(hp=180, atk=150, spa=90, spd=100, spe=100, **{"def": 110})
    fast = dict(stats, spe=250, atk=330)
    ours = [_mon("umbreon", dict(stats, atk=40)), _mon("incineroar", stats)]
    foes = [_mon("kingambit", fast), _mon("garchomp", fast)]

    def so(mid, code=0):
        return SingleBattleOrder(Move(mid, gen=9), move_target=code)
    v0 = [so("foulplay", 1), so("foulplay", 2), so("charm", 1), so("charm", 2), so("taunt", 1), so("snarl")]
    v1 = [so("closecombat", 1), so("closecombat", 2), so("helpinghand")]
    b = _battle(ours, foes, force_switch=[False, False], valid_orders=[v0, v1])
    base = DoubleBattleOrder(v0[0], v1[0])
    p = _pilot()
    p.effects = ALL
    p.stats_counter.update({f"sup_{e}": 0 for e in SV.EFFECTS})
    out = p._improve(b, base)
    assert p.stats_counter["sim_turns"] == 1 and isinstance(out, DoubleBattleOrder)
    kinds = {p._sim_kind(o) for o in v0 + v1}
    assert kinds == {"attack", "support"}
    assert p.stats_counter["sup_foulplay"] + p.stats_counter["sup_charm"] + p.stats_counter["sup_taunt"] \
        + p.stats_counter["sup_snarl"] + p.stats_counter["sup_helpinghand"] >= 1
    off = _pilot()
    assert {off._sim_kind(o) for o in v0[:-1]} == {None}                  # layer off: Foul Play / Charm / Taunt stay locked


# ---- lookahead (state-delta continuation) -----------------------------------------------------------------

def _tr_setup(foe_cur, tr_left=0, trick_room=False):
    weak = DE.Combatant([DE.Hypothesis(1.0, dict(STATS), 180, foe_cur)], ["Normal"])
    world = {"o0": weak, "a0": mine(cur=40), "a1": mine(cur=40)}
    foes = {"o0": fi(100, ("bodyslam",), trickroom=0.8)}
    hit = A(1, "bodyslam", "o0")
    taunt = A(0, "taunt", "o0")
    cands = {0: [taunt, None], 1: [hit]}
    s = sim(foes, speeds=(250, 250), world=world, cands=cands, support_cost=0.0, trick_room=trick_room, tr_left=tr_left)
    return s, taunt, hit


def test_lookahead_values_taunt_against_trick_room_without_any_ko_this_turn():
    s, taunt, hit = _tr_setup(140)                    # our hit leaves it at ~44: nobody dies this turn
    off = s.pair_value((taunt, hit)) - s.pair_value((None, hit))
    s.enable_lookahead()
    on = s.pair_value((taunt, hit)) - s.pair_value((None, hit))
    assert abs(off) < 1e-9 and on > 1.0


def test_lookahead_gives_no_trick_room_credit_to_a_foe_we_ko_first():
    s, taunt, hit = _tr_setup(60)                     # faster and KOs it before it can move
    s.enable_lookahead()
    assert abs(s.pair_value((taunt, hit)) - s.pair_value((None, hit))) < 1e-9


def test_lookahead_ignores_trick_room_that_is_about_to_end():
    s, taunt, hit = _tr_setup(140)
    s.enable_lookahead()
    fresh = s.pair_value((taunt, hit)) - s.pair_value((None, hit))
    up, taunt2, hit2 = _tr_setup(140, tr_left=1, trick_room=True)
    up.enable_lookahead()
    assert up.pair_value((taunt2, hit2)) - up.pair_value((None, hit2)) < 0.1 * fresh


def test_lookahead_snarl_pays_against_a_special_foe_and_not_a_physical_one():
    tank = DE.Combatant([DE.Hypothesis(1.0, {**STATS, "hp": 600, "def": 400, "spd": 400}, 600, 600)], ["Normal"])
    world = {"o0": tank, "a0": mine(), "a1": mine()}
    a = A(0, "snarl", "o0")
    cands = {0: [a, A(0, "bodyslam", "o0")], 1: [A(1, "bodyslam", "o0")]}
    gain = {}
    for name, mv in (("special", "hypervoice"), ("physical", "bodyslam")):
        off = sim({"o0": fi(300, (mv,))}, world=world, effects=frozenset(), cands=cands).pair_value((a, None))
        s = sim({"o0": fi(300, (mv,))}, world=world, effects=frozenset({"snarl"}), cands=cands)
        s.enable_lookahead()
        gain[name] = s.pair_value((a, None)) - off
    assert gain["special"] > 0.1 and abs(gain["physical"]) < 1e-9


def test_pilot_enables_the_lookahead_only_with_a_state_changing_candidate():
    from poke_env.battle import Move
    from poke_env.player.battle_order import SingleBattleOrder

    from tests.test_turn_sim import _battle, _mon, _pilot
    stats = dict(hp=180, atk=150, spa=90, spd=100, spe=100, **{"def": 110})
    fast = dict(stats, spe=250, atk=330)

    def so(mid, code=0):
        return SingleBattleOrder(Move(mid, gen=9), move_target=code)
    for supp, expect in ((True, 1), (False, 0)):
        ours = [_mon("umbreon", dict(stats, atk=40)), _mon("incineroar", stats)]
        foes = [_mon("kingambit", fast), _mon("garchomp", fast)]
        v0 = [so("foulplay", 1), so("charm", 1)] if supp else [so("foulplay", 1), so("closecombat", 1)]
        v1 = [so("closecombat", 1), so("closecombat", 2)]
        b = _battle(ours, foes, force_switch=[False, False], valid_orders=[v0, v1])
        p = _pilot()
        p.effects, p.lookahead = ALL, True
        p.stats_counter.update({f"sup_{e}": 0 for e in SV.EFFECTS})
        p._improve(b, DoubleBattleOrder(v0[0], v1[0]))
        assert p.stats_counter.get("sim_lookahead", 0) == expect


def test_lookahead_costs_little_extra_time():
    import time
    s, taunt, hit = _tr_setup(140)
    t0 = time.perf_counter()
    for _ in range(3):
        s._joint = {}
        s.pair_value((taunt, hit))
    base = (time.perf_counter() - t0) / 3
    s2, taunt, hit = _tr_setup(140)
    t0 = time.perf_counter()
    s2.enable_lookahead()
    s2.pair_value((taunt, hit))
    assert time.perf_counter() - t0 < base + 0.25            # one-off leaf + 2-3 coarse V1s per decision


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("PASS")
