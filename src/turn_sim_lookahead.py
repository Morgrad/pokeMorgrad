"""LookAhead: next-turn state-delta valuation (split from turn_sim.py)."""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import numpy as np

from src import doubles_eval as DE
from src import support_value as SV
from src.turn_sim_types import (
    COARSE_HYPS,
    COARSE_OUTCOME_P,
    FAKE_OUT,
    FoeInfo,
    is_protect,
    is_support,
    is_switch,
)

if TYPE_CHECKING:
    from src.turn_sim import TurnSim


class LookAhead:
    """Next-turn value of the STATE a turn leaves behind, as differences of a coarse one-turn sim.

    The leaf `s'` is the mean-field state after our best plain attack pair (expected HP per hypothesis,
    mons likely dead removed, Trick Room one turn older). A state delta `d` (a stat drop on a foe, a
    Trick Room going up) is worth `V1(s' + d) - V1(s')`, where `V1` is the best attack-pair value of a
    coarse TurnSim on that state. Both terms use the same HP, so a KO this turn is not penalised
    (V1 counts damage still to deal); the delta only changes who wins the NEXT turn's races, which is
    what a one-turn sim cannot see (Trick Room with nobody KO'd yet, a Snarl that keeps a foe from KOing).
    Shared by the fine and coarse sims of a decision; every V1 is cached per delta."""

    def __init__(self, sim: "TurnSim"):
        self.sim = sim
        self.h_drop = SV.SUPPORT_HORIZON * SV.FOE_STAY
        self.h_tr = SV.discounted_turns(SV.TR_TURNS_AFTER_SET)
        self._eff = sim.effects & {"foulplay"}              # leaf attacks carry no drops (that is the delta)
        self._v1: Dict[tuple, float] = {}
        self._dv: Dict[tuple, float] = {}
        self._cands = {s: ([a for a in acts if a is not None and not is_switch(a) and not is_protect(a)
                            and not is_support(a) and a.move != FAKE_OUT] or [None])
                       for s, acts in sim._cands.items()}
        self.world, self.foes = self._leaf()
        tl = sim.tr_left
        self.trick_room = sim.trick_room and (tl == 0 or tl > 1)
        self.tr_left = max(tl - 1, 0) if self.trick_room else 0

    def _sim(self, world: Dict[str, DE.Combatant], foes: Dict[str, FoeInfo], trick_room: bool,
             tr_left: int) -> "TurnSim":
        from src.turn_sim import TurnSim  # lazy to avoid circular import
        sim = self.sim
        return TurnSim(sim.attackers, world, sim.our_speed, foes, trick_room, sim.weather, sim.terrain,
                       sim.ko_bonus, sim.ally_weight, COARSE_HYPS, sim.passive_cost, COARSE_OUTCOME_P,
                       self._eff, sim.support_cost, tr_left)

    def _best(self, ts: "TurnSim", cands: Dict[int, List[Optional[DE.Action]]]) -> Tuple[float, tuple]:
        ts.set_candidates(cands)
        keep = {s: [acts[i] for i in ts.shortlist(acts, 2)] for s, acts in cands.items()}
        return max(((ts.pair_value((a, b)), (a, b)) for a in keep.get(0, [None]) for b in keep.get(1, [None])),
                   key=lambda x: x[0])

    def _leaf(self) -> Tuple[Dict[str, DE.Combatant], Dict[str, FoeInfo]]:
        sim = self.sim
        ref = self._sim(sim.world, sim.foes, sim.trick_room, sim.tr_left)
        _, pair = self._best(ref, self._cands)
        acc: Dict[Tuple[str, int], List[float]] = {}

        def sink(wt: float, hi: Dict[str, int], pmf: Dict[str, np.ndarray]) -> None:
            for t, c in ref.world.items():
                h = hi.get(t, 0)
                a = acc.setdefault((t, h), [0.0, 0.0, 0.0])
                a[0] += wt
                if t in pmf:
                    a[1] += wt * (1.0 - float(pmf[t][0]))
                    a[2] += wt * float((pmf[t] * np.arange(len(pmf[t]))).sum())
                else:
                    cur = float(min(c.hyps[h].cur_hp, c.hyps[h].max_hp))
                    a[1] += wt
                    a[2] += wt * cur
        ref._joint.clear()
        ref._sink = sink
        ref.pair_value(pair)
        world: Dict[str, DE.Combatant] = {}
        for t, c in sim.world.items():
            tot = sum(acc.get((t, j), [0.0])[0] for j in range(len(c.hyps)))
            alive = sum(acc.get((t, j), [0.0, 0.0])[1] for j in range(len(c.hyps)))
            if tot <= 0.0 or alive / tot < 0.5:
                continue
            hyps = []
            for j, h in enumerate(c.hyps):
                a = acc.get((t, j))
                cur = max(1, round(a[2] / a[1])) if a and a[1] > 1e-9 else h.cur_hp
                hyps.append(DE.Hypothesis(h.weight, h.stats, h.max_hp, min(cur, h.max_hp), h.types, h.speeds))
            world[t] = DE.Combatant(hyps, c.types, c.boosts, c.is_ally, c.immune_prob)
        foes = {f: replace(i, taunt_left=max(i.taunt_left - 1, 0)) for f, i in sim.foes.items() if f in world}
        return world, foes

    def _cands_in(self, world: Dict[str, DE.Combatant]) -> Dict[int, List[Optional[DE.Action]]]:
        out: Dict[int, List[Optional[DE.Action]]] = {}
        for slot, acts in self._cands.items():
            ok = [a for a in acts if a is not None and f"a{slot}" in world
                  and all(t in world for t in a.targets)]
            out[slot] = ok or [None]
        return out

    def v1(self, key: tuple = ()) -> float:
        """Best attack-pair value next turn; `key` = () for the leaf itself or a delta."""
        if key not in self._v1:
            world, foes, tr, tl = self.world, self.foes, self.trick_room, self.tr_left
            if key and key[0] == "drop":
                _, f, da, ds = key
                if f in world:
                    c = world[f]
                    world = {**world, f: DE.Combatant(c.hyps, c.types, {
                        **c.boosts, "atk": SV.shifted(c.boosts.get("atk", 0), da),
                        "spa": SV.shifted(c.boosts.get("spa", 0), ds)}, c.is_ally, c.immune_prob)}
            elif key == ("tr",):
                tr, tl = True, SV.TR_TURNS_AFTER_SET
            self._v1[key] = self._best(self._sim(world, foes, tr, tl), self._cands_in(world))[0]
        return self._v1[key]

    def dv(self, key: tuple) -> float:
        if key not in self._dv:
            absent = key[0] == "drop" and key[1] not in self.world
            self._dv[key] = 0.0 if absent else self.v1(key) - self.v1()
        return self._dv[key]
