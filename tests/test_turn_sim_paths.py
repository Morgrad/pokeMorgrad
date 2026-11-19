"""Characterization tests for the rarely hit branches of the turn resolution
(src/turn_sim_resolve.py, called through TurnSim._run).

The values were recorded from the code before TurnSim._run was split out of
src/turn_sim.py (2026-11-18) and must not change: a different number here means the
simulator's behavior changed. Run: python tests/test_turn_sim_paths.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import doubles_eval as DE  # noqa: E402
from src import support_value as SV  # noqa: E402
from src import turn_sim as TS  # noqa: E402

STATS = {"hp": 180, "atk": 150, "def": 110, "spa": 150, "spd": 110, "spe": 100}
ALL = SV.parse_effects("all")


def _hyp(cur=180):
    return DE.Hypothesis(1.0, dict(STATS), 180, cur)


def _foe():
    return DE.Combatant([_hyp()], ["Normal"])


def _mine(cur=180):
    return DE.Combatant([_hyp(cur)], ["Normal"], is_ally=True)


def _sim(world, foes, speeds=(200, 200), effects=ALL):
    attackers = {0: DE.Attacker(stats={**STATS, "atk": 200}, types=["Normal"]),
                 1: DE.Attacker(stats={**STATS, "atk": 200}, types=["Normal"])}
    return TS.TurnSim(attackers, world, dict(enumerate(speeds)), foes, effects=effects)


def _fi(speed, moves=("bodyslam",)):
    return TS.FoeInfo(list(moves), [(1.0, speed)])


def _close(v, want):
    assert abs(v - want) < 1e-12, (v, want)


def test_snarl_into_protect_and_into_an_unmodelled_foe_lands_no_drop():
    # o0 protects (hit chance 0) and o1 has no FoeInfo: both drops are skipped
    world = {"o0": _foe(), "o1": _foe(), "a0": _mine(), "a1": _mine()}
    ts = _sim(world, {"o0": _fi(50)})
    v = ts._run([DE.Action(0, "snarl", ("o0", "o1"))], {}, {}, {}, {"o0"})
    _close(v, WANT["snarl_protect"])


def test_charm_on_a_foe_without_foe_info_is_skipped():
    world = {"o0": _foe(), "o1": _foe(), "a0": _mine(), "a1": _mine()}
    ts = _sim(world, {"o0": _fi(50)})
    _close(ts.pair_value((DE.Action(0, "charm", ("o1",)), None)), WANT["charm_unmodelled"])
    _close(ts.pair_value((DE.Action(0, "charm", ("o0",)), None)), WANT["charm_modelled"])


def test_foe_single_target_hit_retargets_our_partner_when_the_target_fainted():
    world = {"o0": _foe(), "o1": _foe(), "a0": _mine(cur=1), "a1": _mine()}
    ts = _sim(world, {"o0": _fi(150), "o1": _fi(140)}, speeds=(100, 100))
    hit = {f: TS.FoeAct("bodyslam", ("a0",), 0) for f in ("o0", "o1")}
    _close(ts._run([], {}, hit, {"o0": 0, "o1": 0}, set()), WANT["foe_retarget"])
    # our partner protects first (cut 1: Protect moves before both foes): the retargeted hit is blocked
    _close(ts._run([DE.Action(1, "protect", ())], {}, hit, {"o0": 1, "o1": 1}, set()),
           WANT["foe_retarget_protected"])


WANT = {
    "snarl_protect": 0.12435763888888876,
    "charm_unmodelled": -0.553125,
    "charm_modelled": -0.07229166666666667,
    "foe_retarget": -1.4086805555555555,
    "foe_retarget_protected": -1.0055555555555555,
}


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e!r}")
    sys.exit(1 if failed else 0)
