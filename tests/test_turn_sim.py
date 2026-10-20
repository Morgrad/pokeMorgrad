"""Behavioural tests for src/turn_sim.py (synthetic stats, no server).

Run: pytest tests/test_turn_sim.py   (or: python tests/test_turn_sim.py)
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import doubles_eval as DE  # noqa: E402
from src import speed_model as S  # noqa: E402
from src import turn_sim as TS  # noqa: E402

STATS = {"hp": 180, "atk": 150, "def": 110, "spa": 90, "spd": 110, "spe": 100}


def hyp(w=1.0, hp=180, cur=None, types=None, **kw):
    return DE.Hypothesis(w, {**STATS, "hp": hp, **kw}, hp, hp if cur is None else cur, types)


def foe(*hyps, types=("Normal",)):
    return DE.Combatant(list(hyps) or [hyp()], list(types))


def mine(cur=180, hp=180, types=("Normal",)):
    return DE.Combatant([hyp(hp=hp, cur=cur)], list(types), is_ally=True)


def atk(**kw):
    return DE.Attacker(stats={**STATS, "atk": 200}, types=["Normal"], **kw)


def sim(world, foes, speeds=(100, 100), tr=False, attackers=None):
    return TS.TurnSim(attackers or {0: atk(), 1: atk()}, world, dict(enumerate(speeds)), foes, trick_room=tr)


def fi(speed, moves=("bodyslam",), **kw):
    return TS.FoeInfo(list(moves), [(1.0, speed)], **kw)


def test_without_foe_actions_matches_the_evaluator():
    world = {"o0": foe(), "o1": foe(), "a0": mine(), "a1": mine()}
    a = DE.Action(0, "bodyslam", ("o0",))
    b = DE.Action(1, "bodyslam", ("o1",))
    ts, ev = sim(world, {}), DE.Evaluator({0: atk(), 1: atk()}, world)
    assert abs(ts.pair_value((a, b)) - ev.pair_value((a, b))) < 1e-9
    assert abs(ts.pair_value((a, None)) - ev.pair_value((a, None))) < 1e-9


def test_faster_foe_that_kos_us_stops_our_attack():
    world = {"o0": foe(), "a0": mine(cur=1)}
    a = DE.Action(0, "bodyslam", ("o0",))
    slower = sim(world, {"o0": fi(150)}, speeds=(100,), attackers={0: atk()})
    faster = sim(world, {"o0": fi(50)}, speeds=(100,), attackers={0: atk()})
    assert slower.pair_value((a, None)) < faster.pair_value((a, None)) - 0.3


def test_trick_room_flips_who_benefits():
    world = {"o0": foe(), "a0": mine(cur=1)}
    a = DE.Action(0, "bodyslam", ("o0",))
    kw = dict(speeds=(100,), attackers={0: atk()})
    assert sim(world, {"o0": fi(150)}, tr=True, **kw).pair_value((a, None)) > \
        sim(world, {"o0": fi(150)}, **kw).pair_value((a, None))


def test_priority_move_beats_a_faster_foe():
    world = {"o0": foe(hyp(cur=25)), "a0": mine(cur=1)}
    normal = DE.Action(0, "bodyslam", ("o0",))
    prio = DE.Action(0, "aquajet", ("o0",))
    s = sim(world, {"o0": fi(150)}, speeds=(100,), attackers={0: atk()})
    assert s.pair_value((prio, None)) > s.pair_value((normal, None)) + 0.5


def test_killing_a_slower_foe_prevents_its_retaliation():
    world = {"o0": foe(hyp(cur=20)), "a0": mine()}
    a = DE.Action(0, "bodyslam", ("o0",))
    first = sim(world, {"o0": fi(50)}, speeds=(100,), attackers={0: atk()}).pair_value((a, None))
    second = sim(world, {"o0": fi(150)}, speeds=(100,), attackers={0: atk()}).pair_value((a, None))
    assert first > second


def test_unknown_foe_speed_is_a_coin_flip():
    world = {"o0": foe(), "a0": mine(cur=1)}
    a = DE.Action(0, "bodyslam", ("o0",))
    kw = dict(speeds=(100,), attackers={0: atk()})
    lo = sim(world, {"o0": fi(150)}, **kw).pair_value((a, None))
    hi = sim(world, {"o0": fi(50)}, **kw).pair_value((a, None))
    mid = sim(world, {"o0": TS.FoeInfo(["bodyslam"], [(1.0, None)])}, **kw).pair_value((a, None))
    assert abs(mid - (lo + hi) / 2) < 1e-6


def test_foe_mega_speed_mixture_is_weighted_by_q():
    world = {"o0": foe(), "a0": mine(cur=1)}
    a = DE.Action(0, "bodyslam", ("o0",))
    kw = dict(speeds=(100,), attackers={0: atk()})
    belief = S.SpeedBelief([S.SpeedHypothesis(1.0, 80, None, mega_stat=130)])
    vals = [sim(world, {"o0": TS.FoeInfo(["bodyslam"], belief.speeds(mega=q))}, **kw).pair_value((a, None))
            for q in (0.0, 0.5, 1.0)]
    assert vals[2] < vals[1] < vals[0]            # Mega makes the foe outspeed us and KO us first


def test_second_attacker_retargets_when_the_first_kills():
    world = {"o0": foe(hyp(cur=10)), "o1": foe(), "a0": mine(), "a1": mine()}
    a0 = DE.Action(0, "bodyslam", ("o0",))
    ts = sim(world, {}, speeds=(150, 100))
    focus = ts.pair_value((a0, DE.Action(1, "bodyslam", ("o0",))))
    split = ts.pair_value((a0, DE.Action(1, "bodyslam", ("o1",))))
    assert abs(focus - split) < 1e-9              # the overkill hit lands on o1 either way
    slow_first = sim(world, {}, speeds=(100, 150)).pair_value((a0, DE.Action(1, "bodyslam", ("o0",))))
    assert abs(slow_first - focus) < 1e-9


def test_spread_move_still_penalised_for_hurting_the_partner():
    world = {"o0": foe(), "o1": foe(), "a0": mine(), "a1": mine()}
    ts = sim(world, {})
    eq = DE.Action(0, "bodyslam", ("o0",))
    spread = DE.Action(0, "earthquake", ("o0", "o1", "a1"))
    assert ts.pair_value((eq, None)) > 0
    ev = DE.Evaluator({0: atk()}, world)
    assert abs(ts.pair_value((spread, None)) - ev.pair_value((spread, None))) < 1e-6


def test_choose_pair_works_and_is_fast_enough():
    world = {"o0": foe(hyp(0.4), hyp(0.3, spe=130), hyp(0.2, hp=200), hyp(0.1, atk=200)),
             "o1": foe(hyp(0.5), hyp(0.5, spe=60)), "a0": mine(), "a1": mine()}
    foes = {"o0": TS.FoeInfo(["bodyslam"], [(0.5, 90), (0.3, 120), (0.2, 100)]),
            "o1": TS.FoeInfo(["bodyslam", "hypervoice"], [(0.6, 80), (0.4, 105)])}
    ts = sim(world, foes, speeds=(100, 110))
    def cands(slot):
        return [DE.Action(slot, "bodyslam", ("o0",))] + [
            DE.Action(slot, m, (t,)) for m in ("bodyslam", "aquajet", "closecombat") for t in ("o0", "o1")
            if (m, t) != ("bodyslam", "o0")]
    c0, c1 = cands(0), cands(1)
    t0 = time.time()
    ia, ib, best, base = DE.choose_pair(ts, c0, c1)
    dt = time.time() - t0
    assert best >= base
    print(f"choose_pair over {len(c0)}x{len(c1)} pairs: {dt:.2f}s")
    assert dt < 8


def test_mirror_foes_focus_fire_when_only_the_pair_kills():
    one = DE.Evaluator({0: atk()}, {"o0": mine()})
    r = one.rolls(DE.Action(0, "bodyslam", ("o0",)), "o0", 0)
    hp = int(r.mean() * 1.5)                      # one hit cannot KO the target, two always do
    world = {"o0": foe(), "o1": foe(), "a0": mine(cur=hp), "a1": mine()}
    ts = sim(world, {"o0": fi(100), "o1": fi(100)})
    plan = ts._plan({})
    assert set(plan) == {"o0", "o1"} and plan["o0"].targets == plan["o1"].targets == ("a0",)


def test_mirror_foe_avoids_a_spread_move_that_hurts_its_partner():
    world = {"o0": foe(), "o1": foe(), "a0": mine(), "a1": mine()}
    ts = sim(world, {"o0": fi(100, ("earthquake", "bodyslam")), "o1": TS.FoeInfo([], [(1.0, 100)])})
    assert ts._plan({})["o0"].move == "bodyslam"
    alone = sim({"o0": foe(), "a0": mine(), "a1": mine()}, {"o0": fi(100, ("earthquake", "bodyslam"))})
    assert alone._plan({})["o0"].move == "earthquake"      # no partner to hurt: the stronger spread wins


def test_mirror_foe_with_no_known_attack_does_nothing():
    world = {"o0": foe(), "a0": mine()}
    ts = sim(world, {"o0": TS.FoeInfo([], [(1.0, 100)])})
    assert ts._plan({}) == {}


# ---- foe-on-foe damage, per-hypothesis Speed, Protect / Fake Out / switch --------------------------

def test_foe_spread_move_damages_its_own_partner():
    def world(immune):
        o1 = DE.Combatant([hyp()], ["Normal"], immune_prob={"Ground": 1.0} if immune else {})
        return {"o0": foe(), "o1": o1, "a0": mine(cur=1), "a1": mine(cur=1)}
    foes = {"o0": fi(100, ("earthquake",)), "o1": TS.FoeInfo([], [(1.0, 100)])}
    a = DE.Action(0, "bodyslam", ("o0",))
    hurt = sim(world(False), foes).pair_value((a, None))
    safe = sim(world(True), foes).pair_value((a, None))
    assert sim(world(False), foes)._plan({})["o0"].targets == ("a0", "a1", "o1")
    assert hurt > safe + 0.1                      # its own Earthquake chips the partner: good for us


def test_hypothesis_speeds_are_correlated_with_the_build():
    strong, weak = hyp(0.5, atk=250), hyp(0.5, atk=60)
    strong.speeds, weak.speeds = [(1.0, 150)], [(1.0, 50)]
    world = {"o0": foe(strong, weak), "a0": mine()}
    a = DE.Action(0, "bodyslam", ("o0",))
    kw = dict(speeds=(100,), attackers={0: atk()})
    mixed = sim(world, {"o0": fi(100)}, **kw).pair_value((a, None))
    parts = [sim({"o0": foe(hyp(1.0, atk=at)), "a0": mine()}, {"o0": fi(sp)}, **kw).pair_value((a, None))
             for at, sp in ((250, 150), (60, 50))]
    assert abs(mixed - sum(parts) / 2) < 1e-9


def test_foe_fake_out_flinches_our_attack_whatever_the_speed():
    world = {"o0": foe(), "a0": mine()}
    a = DE.Action(0, "bodyslam", ("o0",))
    kw = dict(speeds=(100,), attackers={0: atk()})
    plain = sim(world, {"o0": fi(50, ())}, **kw).pair_value((a, None))
    for spd in (50, 150):
        flinched = sim(world, {"o0": fi(spd, ("bodyslam",), fakeout=1.0)}, **kw).pair_value((a, None))
        assert flinched < plain - 0.15
    ts = sim(world, {"o0": fi(50, ("bodyslam",), fakeout=1.0)}, **kw)
    assert ts.pair_value((DE.Action(0, "fakeout", ("o0",)), None)) > flinched    # Fake Out vs Fake Out: ours is faster


def test_our_fake_out_prevents_the_retaliation():
    world = {"o0": foe(), "a0": mine()}
    ts = sim(world, {"o0": fi(150)}, speeds=(100,), attackers={0: atk()})
    fo, aj = DE.Action(0, "fakeout", ("o0",)), DE.Action(0, "aquajet", ("o0",))
    assert ts.pair_value((fo, None)) > ts.pair_value((aj, None)) + 0.1


def test_foe_protect_blocks_our_attack():
    world = {"o0": foe(), "o1": foe(), "a0": mine()}
    kw = dict(speeds=(100,), attackers={0: atk()})
    a0, a1 = DE.Action(0, "bodyslam", ("o0",)), DE.Action(0, "bodyslam", ("o1",))
    def foes(ok):
        return {"o0": fi(50, (), protect=1.0, protect_ok=ok), "o1": TS.FoeInfo([], [(1.0, 50)])}
    assert abs(sim(world, foes(1.0), **kw).pair_value((a0, None))) < 1e-9
    assert sim(world, foes(0.0), **kw).pair_value((a0, None)) > 0.1       # failed Protect
    assert sim(world, foes(1.0), **kw).pair_value((a1, None)) > 0.1       # the partner is not covered


def test_our_protect_and_switch_absorb_a_hit_but_cost_tempo():
    world = {"o0": foe(), "a0": mine(cur=1), "b0": mine()}
    ts = sim(world, {"o0": fi(150)}, speeds=(100,), attackers={0: atk()})
    stay = ts.pair_value((None, None))
    protect = ts.pair_value((DE.Action(0, "protect", ()), None))
    swap = ts.pair_value((DE.Action(0, TS.SWITCH, ("b0",)), None))
    assert protect > stay + 0.5 and swap > stay + 0.3           # KO avoided
    idle = sim(world, {"o0": TS.FoeInfo([], [(1.0, 150)])}, speeds=(100,), attackers={0: atk()})
    assert abs(idle.pair_value((DE.Action(0, "protect", ()), None)) + TS.PASSIVE_COST) < 1e-9


def test_two_slots_cannot_switch_to_the_same_mon():
    world = {"o0": foe(), "a0": mine(), "a1": mine(), "b0": mine()}
    ts = sim(world, {})
    assert ts.pair_value((DE.Action(0, TS.SWITCH, ("b0",)), DE.Action(1, TS.SWITCH, ("b0",)))) == TS.CONFLICT


def test_foe_retargeting_with_an_empty_partner_slot_does_not_crash():
    world = {"o0": foe(), "o1": foe(), "a1": mine(cur=1)}          # slot 0 is empty (fainted, no bench)
    ts = sim(world, {"o0": fi(150), "o1": fi(140)}, speeds=(0, 100), attackers={1: atk()})
    hit = {f: TS.FoeAct("bodyslam", ("a1",), 0) for f in ("o0", "o1")}
    a = DE.Action(1, "bodyslam", ("o0",))
    ts._run([a], {}, hit, {"o0": 0, "o1": 0}, set())     # the 2nd foe finds a1 dead, has no partner to retarget to


def test_foe_fake_out_targets_the_slot_with_the_better_attack():
    world = {"o0": foe(), "a0": mine(), "a1": mine()}
    ts = sim(world, {"o0": fi(100, ("bodyslam",), fakeout=1.0)})
    ts.set_candidates({0: [DE.Action(0, "bodyslam", ("o0",))], 1: [None]})
    (kind, p, tgt), = ts._kinds["o0"]
    assert (kind, tgt) == ("fakeout", "a0") and abs(p - 1.0) < 1e-9


# ---- DoublesPilot wiring (real poke_env Pokemon / orders, no server) -------------------------------

def _mon(species, stats, hp_frac=1.0):
    from poke_env.battle import Pokemon
    m = Pokemon(gen=9, species=species)
    m._stats, m._max_hp, m._current_hp = dict(stats), stats["hp"], round(stats["hp"] * hp_frac)
    return m


def _pilot(on=True):
    from src.doubles_pilot import DoublesPilot
    p = DoublesPilot.__new__(DoublesPilot)
    p.ko_bonus, p.min_gain, p.use_turn_sim = DE.KO_BONUS, DE.MIN_GAIN, on
    p.stats_counter = {"turns": 0, "overrides": 0, "errors": 0, "sim_turns": 0,
                           "sim_protect": 0, "sim_switch": 0, "sim_fakeout": 0}
    return p


def _battle(ours, foes, **kw):
    from types import SimpleNamespace as NS
    kw.setdefault("available_switches", [[], []])
    return NS(active_pokemon=ours, opponent_active_pokemon=foes, side_conditions={},
              opponent_side_conditions={}, fields={}, weather={}, **kw)


def test_pilot_speed_inputs_use_tailwind_paralysis_and_trick_room():
    from poke_env.battle import Field, SideCondition
    from poke_env.battle.status import Status
    p = _pilot()
    stats = dict(hp=180, atk=150, spa=90, spd=100, spe=100, **{"def": 110})
    m = _mon("garchomp", stats)
    b = _battle([m, None], [None, None])
    assert p._our_speed(m, b) == 100
    b.side_conditions = {SideCondition.TAILWIND: 1}
    assert p._our_speed(m, b) == 200
    m._status = Status.PAR
    assert p._our_speed(m, b) == 100
    foe = _mon("incineroar", stats)
    info = p._foe_info(foe, b, DE.Combatant([DE.Hypothesis(1.0, stats, 180, 180)], ["Fire", "Dark"]))
    assert info.moves == ["bodyslam"] and abs(sum(w for w, _ in info.speeds) - 1.0) < 1e-9
    assert Field.TRICK_ROOM not in b.fields


def test_pilot_improve_with_turn_sim_runs_end_to_end():
    from poke_env.battle import Move
    from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder
    stats = dict(hp=180, atk=150, spa=90, spd=100, spe=100, **{"def": 110})
    ours = [_mon("garchomp", stats), _mon("incineroar", stats)]
    foes = [_mon("kingambit", stats, 0.2), _mon("garchomp", stats)]

    def so(code):
        return SingleBattleOrder(Move("closecombat", gen=9), move_target=code)
    valid = [[so(1), so(2)], [so(1), so(2)]]
    b = _battle(ours, foes, force_switch=[False, False], valid_orders=valid)
    base = DoubleBattleOrder(so(2), so(2))
    p = _pilot()
    out = p._improve(b, base)
    assert isinstance(out, DoubleBattleOrder) and p.stats_counter["sim_turns"] == 1
    p2 = _pilot(False)
    p2._improve(b, base)
    assert p2.stats_counter["sim_turns"] == 0


def test_pilot_sim_considers_protect_and_switch_when_our_mon_is_about_to_die():
    from poke_env.battle import Move
    from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder
    stats = dict(hp=180, atk=150, spa=90, spd=100, spe=100, **{"def": 110})
    fast = dict(stats, spe=200, atk=300)
    ours = [_mon("garchomp", stats, 0.05), _mon("incineroar", stats)]
    bench = _mon("rillaboom", stats)
    foes = [_mon("kingambit", fast), _mon("garchomp", fast)]

    def move(mid, code=None):
        return SingleBattleOrder(Move(mid, gen=9), move_target=code if code is not None else 0)
    v0 = [move("closecombat", 1), move("closecombat", 2), move("protect"), SingleBattleOrder(bench)]
    v1 = [move("closecombat", 1), move("closecombat", 2)]
    b = _battle(ours, foes, force_switch=[False, False], valid_orders=[v0, v1],
                available_switches=[[bench], [bench]])
    p = _pilot()
    out = p._improve(b, DoubleBattleOrder(v0[0], v1[0]))
    assert p.stats_counter["sim_turns"] == 1
    assert out.first_order.message != v0[0].message              # a 5%-HP mon facing two fast attackers does not attack
    assert p.stats_counter["sim_protect"] + p.stats_counter["sim_switch"] == 1


def test_vgc_pilot_foe_action_probs_come_from_the_battle_memory():
    from types import SimpleNamespace as NS

    from src.battle_memory import BattleMemory
    from src.vgc_pilot import VGCPilot
    p = VGCPilot.__new__(VGCPilot)
    p.foe_actions = True
    mem = BattleMemory()
    for line in ("|player|p1|a|1|", "|player|p2|b|1|", "|turn|1",
                 "|switch|p2a: Rillaboom|Rillaboom, M|100/100", "|switch|p2b: Incineroar|Incineroar, M|100/100"):
        mem.feed(line.split("|"))
    p.memory_for = lambda battle: mem
    foe = _mon("rillaboom", dict(hp=180, atk=150, spa=90, spd=100, spe=100, **{"def": 110}))
    foe._name = "Rillaboom"
    fo, pr, ok = p._foe_action_probs(foe, NS(player_role="p1"))
    assert 0.0 <= fo <= 1.0 and 0.0 <= pr <= 1.0 and ok == 1.0
    p.foe_actions = False
    assert p._foe_action_probs(foe, NS(player_role="p1")) == (0.0, 0.0, 1.0)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("PASS")
