"""One scenario of a simulated turn, played out in move order (the body of TurnSim._run).

`src/turn_sim.py::TurnSim` enumerates scenarios (foe hypotheses x foe outcomes x speed-order
cuts) and calls `TurnSim._run` for each one, which builds a `Resolution` and calls `run()`:
  1. Every combatant's HP is a probability vector (`pmf`), created lazily from the hypothesis
     it is simulated with (`hi[id]`).
  2. Actions are applied in order: the foes whose cut is k act right before our k-th action
     (`cut[fid]` = how many of our sorted actions move before that foe), then our action k.
  3. `value()`: HP fraction removed + KO bonus per foe, minus the same for our mons (times
     `ally_weight`), plus the stat-drop persistence and Trick Room / Taunt terms.

State shared by the steps (one Resolution = one scenario):
  pmf, start   HP distribution / starting HP per combatant id
  occ          our slot ("a0", "a1") -> id of the mon standing in it (switches)
  blocked      ids whose incoming hits are blocked this turn (Protect)
  fskip        foe -> P(flinched before acting) (our Fake Out)
  oskip        our slot -> P(flinched before acting) (foe Fake Out)
  fdrop        foe -> {(d_atk, d_spa) stage drops: P} landed this turn (Snarl / Charm)
  helped       our slot -> P(its next attack gets Helping Hand)
  taunted      foe -> P(a Taunt landed on it)
  extra        persistence value of landed stat drops (only without lookahead)

Split out of TurnSim._run on 2026-11-18 (it was one 173-line method of nested closures). The
arithmetic and its order are unchanged; pinned by tests/test_turn_sim.py, tests/test_support.py
and tests/test_turn_sim_paths.py.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, FrozenSet, List, Set, Tuple

import numpy as np

from src import doubles_eval as DE
from src import support_value as SV
from src.turn_sim_types import (
    FAKE_OUT,
    FoeAct,
    _apply,
    _is_physical,
    _is_single,
    _pmf,
    is_protect,
    is_switch,
)

if TYPE_CHECKING:
    from src.turn_sim import TurnSim


class Resolution:
    """HP distributions and effects of one scenario; `run()` plays it and returns its value."""

    def __init__(self, sim: "TurnSim", hi: Dict[str, int], cut: Dict[str, int], protecting: Set[str]):
        self.sim = sim
        self.hi = hi
        self.cut = cut
        self.pmf: Dict[str, np.ndarray] = {}
        self.start: Dict[str, float] = {}
        self.occ = {"a0": "a0", "a1": "a1"}            # our slot -> id of the mon standing in it
        self.blocked: Set[str] = set(protecting)       # ids whose incoming hits are blocked
        self.fskip: Dict[str, float] = {}              # foe -> P(flinched before acting)
        self.oskip: Dict[int, float] = {}              # our slot -> P(flinched before acting)
        self.fdrop: Dict[str, Dict[Tuple[int, int], float]] = {}   # foe -> {(d_atk, d_spa) stages: P}
        self.helped: Dict[int, float] = {}             # our slot -> P(its next attack gets Helping Hand)
        self.taunted: Dict[str, float] = {}            # foe -> P(a Taunt landed on it)
        self.extra = 0.0                               # persistence value of landed stat drops
        self.snarl = "snarl" in sim.effects

    # ---- HP distributions ----------------------------------------------------------------------

    def get(self, t: str) -> np.ndarray:
        if t not in self.pmf:
            h = self.sim.world[t].hyps[self.hi.get(t, 0)]
            self.pmf[t] = _pmf(h)
            self.start[t] = float(min(h.cur_hp, h.max_hp))
        return self.pmf[t]

    def alive(self, t: str) -> float:
        return 1.0 - self.get(t)[0] if t in self.sim.world else 1.0

    def hit_pmf(self, t: str, r: np.ndarray, p: float, ph: float = 0.0) -> np.ndarray:
        if ph <= 0.0:
            return _apply(self.get(t), r, p)
        boosted = (r * SV.HELPING_HAND_MULT).astype(np.int64)
        return (1.0 - ph) * _apply(self.get(t), r, p) + ph * _apply(self.get(t), boosted, p)

    def heal_pmf(self, t: str, frac: float, p: float) -> np.ndarray:
        """HP distribution after a self-heal of `frac` of max HP that goes off with probability `p`."""
        old = self.get(t)
        n = len(old)
        up = np.zeros(n)
        up[0] = old[0]
        amount = int(frac * (n - 1))
        np.add.at(up, np.minimum(np.arange(1, n) + amount, n - 1), old[1:])
        return (1.0 - p) * old + p * up

    def foe_mix(self, fid: str, move: str, tid: str, n: int) -> List[Tuple[float, np.ndarray]]:
        """Rolls of a foe hit, mixed over the Atk / Sp. Atk stage drops it carries this turn."""
        dist = self.fdrop.get(fid)
        hf, ht = self.hi.get(fid, 0), self.hi.get(tid, 0)
        if not dist:
            return [(1.0, self.sim._foe_rolls(fid, hf, move, tid, ht, n))]
        i = 0 if _is_physical(move) else 1
        marg: Dict[int, float] = {}
        for sh, q in dist.items():
            marg[sh[i]] = marg.get(sh[i], 0.0) + q
        return [(q, self.sim._foe_rolls(fid, hf, move, tid, ht, n, d)) for d, q in marg.items()]

    def apply_mix(self, t: str, mix: List[Tuple[float, np.ndarray]], p: float) -> np.ndarray:
        if len(mix) == 1:
            return _apply(self.get(t), mix[0][1], p)
        return sum(q * _apply(self.get(t), r, p) for q, r in mix)

    # ---- effects --------------------------------------------------------------------------------

    def land(self, tid: str, p: float, drop: SV.Drop) -> None:
        """A stat drop hits foe `tid` with probability `p`: in-turn stage distribution + persistence."""
        sim = self.sim
        if p <= 0.0 or tid not in sim.foes:
            return
        outs = sim._drop_outcomes(drop, tid)
        new: Dict[Tuple[int, int], float] = {}
        for sh, q in (self.fdrop.get(tid) or {(0, 0): 1.0}).items():
            new[sh] = new.get(sh, 0.0) + (1.0 - p) * q
            for pr, da, ds in outs:
                k2 = (SV.shifted(sh[0], da), SV.shifted(sh[1], ds))
                new[k2] = new.get(k2, 0.0) + p * q * pr
        self.fdrop[tid] = new
        if sim.la is None:
            self.extra += (sim.ally_weight * SV.SUPPORT_HORIZON * SV.FOE_STAY * p * self.alive(tid)
                           * sim._drop_gain(drop, tid, self.hi))

    # ---- actions --------------------------------------------------------------------------------

    def our_hit(self, k: int, a: DE.Action) -> None:
        """Our k-th action (in our sorted move order)."""
        sim, occ, pmf, hi = self.sim, self.occ, self.pmf, self.hi
        if is_switch(a):
            occ[f"a{a.attacker}"] = a.targets[0]
            return
        me = occ[f"a{a.attacker}"]
        if is_protect(a):
            self.blocked.add(me)
            return
        pa = self.alive(me) * (1.0 - self.oskip.get(a.attacker, 0.0))
        pk = SV.pure_kind(a.move)
        if pk == "helpinghand":
            ps = 1 - a.attacker
            self.helped[ps] = 1.0 - (1.0 - self.helped.get(ps, 0.0)) * (1.0 - pa)
            return
        if pk == "heal":
            pmf[me] = self.heal_pmf(me, SV.heal_fraction(a.move, sim.weather), pa)
            return
        if pk:
            for t in a.targets:
                tid = occ.get(t, t)
                if tid not in sim.foes:
                    continue
                p = pa * DE._accuracy(a.move) * (tid not in self.blocked)   # status moves ignore type immunity
                if pk == "taunt":
                    self.taunted[tid] = 1.0 - (1.0 - self.taunted.get(tid, 0.0)) * (1.0 - p)
                else:
                    self.land(tid, p, SV.foe_drop(a.move))
            return
        ph = self.helped.pop(a.attacker, 0.0)
        drop = SV.foe_drop(a.move) if self.snarl else None
        if drop is not None and drop.kind != "secondary":
            drop = None
        single = _is_single(a.move) and len(a.targets) == 1
        for t in a.targets:
            tid = occ.get(t, t)
            p = pa * sim._p_hit_id(a.move, tid) * (tid not in self.blocked)
            p_dead = self.get(tid)[0]
            r = sim.rolls(a, tid, hi.get(tid, 0))
            pmf[tid] = self.hit_pmf(tid, r, p, ph)
            if a.move == FAKE_OUT and tid in self.cut and self.cut[tid] > k:
                pfl = p * float((r > 0).mean())
                self.fskip[tid] = 1.0 - (1.0 - self.fskip.get(tid, 0.0)) * (1.0 - pfl)
            if drop is not None and t.startswith("o"):
                self.land(tid, p, drop)
            if single and t.startswith("o") and p_dead > 1e-9:
                other = "o1" if t == "o0" else "o0"
                if other in sim.world and other not in self.blocked:
                    ra = DE.Action(a.attacker, a.move, (other,))
                    pmf[other] = self.hit_pmf(other, sim.rolls(ra, other, hi.get(other, 0)),
                                              pa * sim._p_hit_id(a.move, other) * p_dead, ph)

    def foe_hit(self, fid: str, fa: FoeAct) -> None:
        """Foe `fid` uses `fa` (its slot in the order comes from `cut`)."""
        sim, occ, pmf = self.sim, self.occ, self.pmf
        pf = self.alive(fid) * (1.0 - self.fskip.get(fid, 0.0))
        single = _is_single(fa.move) and len(fa.targets) == 1
        n = len(fa.targets)
        for t in fa.targets:
            tid = occ.get(t, t)
            p = pf * sim._p_hit_id(fa.move, tid) * (tid not in self.blocked)
            p_dead = self.get(tid)[0]
            mix = self.foe_mix(fid, fa.move, tid, n)
            pmf[tid] = self.apply_mix(tid, mix, p)
            if fa.move == FAKE_OUT and t in occ:
                s = int(t[1])
                self.oskip[s] = 1.0 - (1.0 - self.oskip.get(s, 0.0)) * (1.0 - p * float((mix[0][1] > 0).mean()))
            if single and t in occ and p_dead > 1e-9:
                o = occ["a1" if t == "a0" else "a0"]
                if o in sim.world and o not in self.blocked:
                    pmf[o] = self.apply_mix(o, self.foe_mix(fid, fa.move, o, 1),
                                            pf * sim._p_hit_id(fa.move, o) * p_dead)

    # ---- the scenario -----------------------------------------------------------------------------

    def run(self, ours: List[DE.Action], foe_acts: Dict[str, FoeAct], trfoes: FrozenSet[str] = frozenset(),
            wt: float = 0.0) -> float:
        """Play the turn in move order, then return its value (see `value`)."""
        slots: List[List[str]] = [[] for _ in range(len(ours) + 1)]
        for f in foe_acts:
            slots[self.cut[f]].append(f)
        for k in range(len(ours) + 1):
            for f in slots[k]:
                self.foe_hit(f, foe_acts[f])
            if k < len(ours):
                self.our_hit(k, ours[k])
        return self.value(trfoes, wt)

    def value(self, trfoes: FrozenSet[str], wt: float) -> float:
        """Damage / KO value of the played turn (our view) plus the drop and Trick Room terms.
        `trfoes`: foes that set Trick Room this scenario; `wt`: scenario weight for the leaf sink."""
        sim = self.sim
        total = self.extra
        if sim.la is not None:
            for f, dist in self.fdrop.items():
                for sh, q in dist.items():
                    if sh != (0, 0):
                        total += q * self.alive(f) * sim.la.h_drop * sim.la.dv(("drop", f, sh[0], sh[1]))
            for f in trfoes:
                total += sim.la.h_tr * sim.la.dv(("tr",)) * (1.0 - self.taunted.get(f, 0.0)) * self.alive(f)
        else:
            for f in trfoes:                   # Taunt (+0) lands before Trick Room (-7), so it fails
                total += sim._tr_cost() * (1.0 - self.taunted.get(f, 0.0))
        if sim._sink is not None:
            sim._sink(wt, self.hi, self.pmf)
        for t, dist in self.pmf.items():
            c = sim.world[t]
            h = c.hyps[self.hi.get(t, 0)]
            e_hp = float((dist * np.arange(len(dist))).sum())
            v = (self.start[t] - e_hp) / h.max_hp + sim.ko_bonus * float(dist[0])
            total += (-sim.ally_weight * v) if c.is_ally else v
        return total
