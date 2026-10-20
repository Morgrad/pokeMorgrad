"""One-turn simulation for doubles: move order, retaliation, retargeting, Protect, Fake Out, switches
(pure logic, no poke_env).

`TurnSim` is a drop-in replacement for `doubles_eval.Evaluator` (same `pair_value` / `choose_pair`
interface). Where the Evaluator scores our damage as if every attack lands first, TurnSim plays the
turn out in move order, so a slower mon can be KO'd before it acts, a faster KO prevents the foe's
hit, priority moves and Trick Room/Tailwind change who benefits, and a single-target move whose
target already fainted hits the other foe (Showdown retargeting).

Model (deliberately small, each point is a follow-up if it proves to matter):
  - Foe hypotheses (stats/types/HP/Speed) come from the Combatants, pruned to the `max_hyps`
    heaviest. A hypothesis carries its own Speed list (`Hypothesis.speeds`) so Speed and damage stay
    correlated (a Mega foe is fast AND strong); `FoeInfo.speeds` is the fallback.
  - Foe outcome per foe, drawn from `FoeInfo`: attack, Fake Out (on one of our slots), Protect that
    works, or nothing (failed Protect / no known attack). Probabilities come from src.opp_actions.
  - Mirror foe: an attacking foe picks its move the way our own pilot does: the pair of (move, target)
    that maximises `doubles_eval` pair value from THEIR side (focus fire, no overkill, spread moves
    that hurt their partner are avoided) for the foes that attack. Foe-on-foe spread damage applies.
  - Our actions: attacks, Fake Out (flinches a foe that has not acted yet), Protect (blocks hits on
    its occupant for the turn), switch (the bench mon takes the slot's hits). Switch/Protect pay a
    small `passive_cost` (tempo: the value unit only counts damage, one turn ahead).
  - HP is propagated as a probability vector per combatant; an actor acts with the probability it is
    still alive when its turn comes. Accuracy is per hit; no crits, secondary effects (other than
    Fake Out's flinch) or items.
  - Value = sum over foes of (HP fraction removed + KO_BONUS * P(KO)) minus the same for our mons
    (foe retaliation and our own spread damage), so the unit matches the Evaluator.
"""
from __future__ import annotations

import itertools
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

import numpy as np

from src import damage
from src import doubles_eval as DE
from src.battle_memory import PROTECT_FAMILY

MAX_HYPS = 4
MIN_SCENARIO_P = 1e-4
MIN_OUTCOME_P = 0.005
SINGLE_TARGET = ("normal", "any")
BLOCKING = PROTECT_FAMILY - {"endure"}        # Endure survives a hit, it does not block it
SWITCH = "switch"
FAKE_OUT = "fakeout"
SWITCH_PRIORITY = 8
PASSIVE_COST = float(os.environ.get("DOUBLES_PASSIVE_COST", 0.15))
CONFLICT = -1e9
SHORTLIST = 3            # plain attacks kept per slot besides the baseline and the specials
TOP_K = 6                # pairs re-scored with the full sim after the coarse screen
COARSE_HYPS = 2
COARSE_OUTCOME_P = 0.05

Speeds = List[Tuple[float, Optional[int]]]


@dataclass
class FoeInfo:
    moves: List[str]                              # known/assumed damaging moves (DB ids)
    speeds: Speeds                                # (weight, effective Speed); Speed None = unknown (coin flip)
    fakeout: float = 0.0                          # P(uses Fake Out this turn)
    protect: float = 0.0                          # P(uses a Protect-family move this turn)
    protect_ok: float = 1.0                       # P(that Protect works)


@dataclass(frozen=True)
class FoeAct:
    move: str
    targets: Tuple[str, ...]                      # world ids hit: ours ('a0', 'a1') or its foe partner
    priority: int


@lru_cache(maxsize=None)
def move_priority(move: str) -> int:
    return int((damage.DB.get_move(move) or {}).get("priority") or 0)


def act_priority(a: DE.Action) -> int:
    return SWITCH_PRIORITY if a.move == SWITCH else move_priority(a.move)


def is_switch(a: DE.Action) -> bool:
    return a.move == SWITCH


def is_protect(a: DE.Action) -> bool:
    return a.move in BLOCKING


@lru_cache(maxsize=None)
def _is_single(move: str) -> bool:
    return (damage.DB.get_move(move) or {}).get("target") in SINGLE_TARGET


def _prune(c: DE.Combatant, k: int) -> DE.Combatant:
    if len(c.hyps) <= k:
        return c
    top = sorted(c.hyps, key=lambda h: -h.weight)[:k]
    tot = sum(h.weight for h in top)
    hyps = [DE.Hypothesis(h.weight / tot, h.stats, h.max_hp, h.cur_hp, h.types, h.speeds) for h in top]
    return DE.Combatant(hyps, c.types, c.boosts, c.is_ally, c.immune_prob)


def _pmf(h: DE.Hypothesis) -> np.ndarray:
    v = np.zeros(h.max_hp + 1)
    v[min(max(h.cur_hp, 0), h.max_hp)] = 1.0
    return v


def _apply(pmf: np.ndarray, rolls: np.ndarray, p: float) -> np.ndarray:
    """HP distribution after a hit that lands with probability `p` for one of `rolls` equally likely damages."""
    if p <= 0.0:
        return pmf
    n = len(pmf)
    idx = np.maximum(np.arange(n)[:, None] - rolls[None, :], 0)
    w = np.broadcast_to((pmf / len(rolls))[:, None], idx.shape)
    return (1.0 - p) * pmf + p * np.bincount(idx.ravel(), w.ravel(), minlength=n)


def _flip(t: str) -> str:
    """Foe view <-> world: view 'o<i>' is our slot 'a<i>', view 'a<i>' is the foe 'o<i>'."""
    return ("a" if t[0] == "o" else "o") + t[1:]


class TurnSim(DE.Evaluator):
    def __init__(self, attackers: Dict[int, DE.Attacker], world: Dict[str, DE.Combatant],
                 our_speed: Dict[int, int], foes: Dict[str, FoeInfo], trick_room: bool = False,
                 weather: Optional[str] = None, terrain: Optional[str] = None,
                 ko_bonus: float = DE.KO_BONUS, ally_weight: float = DE.ALLY_WEIGHT,
                 max_hyps: int = MAX_HYPS, passive_cost: float = PASSIVE_COST,
                 min_outcome_p: float = MIN_OUTCOME_P):
        pruned = {t: (_prune(c, max_hyps) if t.startswith("o") else c) for t, c in world.items()}
        super().__init__(attackers, pruned, weather, terrain, ko_bonus, ally_weight)
        self.our_speed = our_speed
        self.trick_room = trick_room
        self.passive_cost = passive_cost
        self.min_outcome_p = min_outcome_p
        self.foes = {f: i for f, i in foes.items() if f in pruned}
        self._foe_rolls_cache: Dict[tuple, np.ndarray] = {}
        self._plans: Dict[tuple, Dict[str, FoeAct]] = {}
        self._orders: Dict[tuple, Dict[int, float]] = {}
        self._p_hits: Dict[tuple, float] = {}
        self._threat: Dict[int, float] = {}
        self._build_kinds()

    # ---- foe outcomes ------------------------------------------------------------------------

    def set_candidates(self, cands: Dict[int, Sequence[Optional[DE.Action]]]) -> None:
        """Our candidate actions per slot: a foe's Fake Out goes to the slot whose attack is worth most."""
        self._threat = {}
        for slot, acts in cands.items():
            vals = [DE.Evaluator.pair_value(self, (a,)) for a in acts
                    if a is not None and not is_switch(a) and not is_protect(a) and a.attacker in self.attackers]
            self._threat[slot] = max(vals + [0.0])
        self._joint.clear()
        self._build_kinds()

    def shortlist(self, acts: Sequence[Optional[DE.Action]], k: int) -> List[int]:
        """Indices worth simulating: the baseline (0), every Fake Out / Protect / switch, and the `k`
        best other attacks by their solo (no-order) value."""
        keep, plain = {0}, []
        for i, a in enumerate(acts):
            if a is None or is_switch(a) or is_protect(a) or a.move == FAKE_OUT:
                keep.add(i)
            elif i:
                plain.append((DE.Evaluator.pair_value(self, (a,)), i))
        keep |= {i for _, i in sorted(plain, reverse=True)[:k]}
        return sorted(keep)

    def _build_kinds(self) -> None:
        mine = [t for t in ("a0", "a1") if t in self.world]
        w = [max(self._threat.get(int(t[1]), 0.0), 0.0) for t in mine]
        tot = sum(w)
        w = [x / tot for x in w] if tot > 1e-9 else [1.0 / max(len(mine), 1)] * len(mine)
        self._kinds: Dict[str, List[Tuple[str, float, Optional[str]]]] = {}
        for f, info in self.foes.items():
            pf = min(max(info.fakeout, 0.0), 1.0) if mine else 0.0
            pp = min(max(info.protect, 0.0), 1.0 - pf)
            ok = min(max(info.protect_ok, 0.0), 1.0)
            raw: List[Tuple[str, float, Optional[str]]] = [("atk", 1.0 - pf - pp, None)]
            raw += [("fakeout", pf * wt, t) for t, wt in zip(mine, w)]
            raw += [("protect", pp * ok, None), ("idle", pp * (1.0 - ok), None)]
            raw = [r for r in raw if r[1] >= self.min_outcome_p]
            s = sum(r[1] for r in raw)
            self._kinds[f] = [(k, p / s, t) for k, p, t in raw]

    # ---- foe action model (stand-in) ---------------------------------------------------------

    def _foe_rolls(self, fid: str, hf: int, move: str, tid: str, ht: int, n_targets: int) -> np.ndarray:
        key = (fid, hf, move, tid, ht, n_targets)
        if key not in self._foe_rolls_cache:
            fc, tc = self.world[fid], self.world[tid]
            fh, th = fc.hyps[hf], tc.hyps[ht]
            r = damage.damage_rolls_from_stats(
                fh.stats, fh.types or fc.types, fc.boosts, move,
                th.stats, th.types or tc.types, tc.boosts,
                is_doubles=True, include_spread=n_targets > 1,
                weather=self.weather, terrain=self.terrain)
            self._foe_rolls_cache[key] = np.array(r if r else [0], dtype=np.int64)
        return self._foe_rolls_cache[key]

    def _p_hit_id(self, move: str, tid: str) -> float:
        key = (move, tid)
        if key not in self._p_hits:
            mv = damage.DB.get_move(move)
            self._p_hits[key] = DE._accuracy(move) * (1.0 - self.world[tid].immune_prob.get(mv["type"], 0.0))
        return self._p_hits[key]

    def _plan(self, hi: Dict[str, int], acting: Optional[FrozenSet[str]] = None) -> Dict[str, FoeAct]:
        """Mirror policy: the attack pair of the `acting` foes that maximises their own doubles_eval
        value, given the hypothesis index `hi[fid]` each foe is being simulated with."""
        acting = frozenset(self.foes) if acting is None else acting
        foe_ids = [f for f in self.world if f.startswith("o")]
        key = (tuple((f, hi.get(f, 0)) for f in foe_ids), acting)
        if key in self._plans:
            return self._plans[key]
        mine = [t for t in ("a0", "a1") if t in self.world]
        view: Dict[str, DE.Combatant] = {}
        for t in mine:                                       # our mons are the targets in their view
            c = self.world[t]
            view[_flip(t)] = DE.Combatant(c.hyps[:1], c.types, c.boosts, False, c.immune_prob)
        attackers: Dict[int, DE.Attacker] = {}
        for f in foe_ids:
            fc, j = self.world[f], int(f[1])
            h = fc.hyps[hi.get(f, 0)]
            view[_flip(f)] = DE.Combatant([DE.Hypothesis(1.0, h.stats, h.max_hp, h.cur_hp, h.types)],
                                          fc.types, fc.boosts, True, fc.immune_prob)
            if f in acting:
                attackers[j] = DE.Attacker(dict(h.stats), h.types or fc.types, fc.boosts)
        cands: Dict[int, List[Optional[DE.Action]]] = {0: [None], 1: [None]}
        for f in acting:
            j = int(f[1])
            for move in self.foes[f].moves if f in self.foes else []:
                if not self.modelable(move) or not mine:
                    continue
                tg = (damage.DB.get_move(move).get("target") or "")
                if tg in SINGLE_TARGET:
                    cands[j] += [DE.Action(j, move, (_flip(t),)) for t in mine]
                elif tg == "allAdjacentFoes":
                    cands[j].append(DE.Action(j, move, tuple(_flip(t) for t in mine)))
                elif tg == "allAdjacent":
                    partner = f"a{1 - j}"
                    cands[j].append(DE.Action(j, move, tuple(_flip(t) for t in mine)
                                              + ((partner,) if partner in view else ())))
        ev = DE.Evaluator(attackers, view, self.weather, self.terrain, self.ko_bonus, self.ally_weight)
        best, best_v = (None, None), float("-inf")
        for a in cands[0]:
            for b in cands[1]:
                v = ev.pair_value((a, b))
                if v > best_v + 1e-12:
                    best, best_v = (a, b), v
        plan = {}
        for act in best:
            if act is not None:
                plan[f"o{act.attacker}"] = FoeAct(act.move, tuple(_flip(t) for t in act.targets),
                                                  move_priority(act.move))
        self._plans[key] = plan
        return plan

    # ---- move order --------------------------------------------------------------------------

    def _ours_first(self, slot: int, prio: int, foe_prio: int, foe_speed: Optional[int]) -> float:
        if prio != foe_prio:
            return 1.0 if prio > foe_prio else 0.0
        mine = self.our_speed.get(slot, 0)
        if foe_speed is None or mine == foe_speed:
            return 0.5
        return 1.0 if (mine > foe_speed) != self.trick_room else 0.0

    def _order_dist(self, fid: str, hf: int, ours: Sequence[DE.Action], foe_prio: int) -> Dict[int, float]:
        """{k: P(exactly the first k of our (sorted) actions move before this foe)}."""
        key = (fid, hf, foe_prio, tuple(ours))
        if key in self._orders:
            return self._orders[key]
        speeds = self.world[fid].hyps[hf].speeds or self.foes[fid].speeds
        out: Dict[int, float] = {}
        for w, spd in speeds:
            dist = {0: 1.0}
            for a in ours:
                p1 = self._ours_first(a.attacker, act_priority(a), foe_prio, spd)
                nxt: Dict[int, float] = {}
                for k, pk in dist.items():
                    if p1 > 0:
                        nxt[k + 1] = nxt.get(k + 1, 0.0) + pk * p1
                    if p1 < 1:
                        nxt[k] = nxt.get(k, 0.0) + pk * (1 - p1)
                dist = nxt
            for k, pk in dist.items():
                out[k] = out.get(k, 0.0) + w * pk
        self._orders[key] = out
        return out

    def _sort_ours(self, acts: Sequence[DE.Action]) -> List[DE.Action]:
        sign = 1 if self.trick_room else -1
        return sorted(acts, key=lambda a: (-act_priority(a), sign * self.our_speed.get(a.attacker, 0),
                                           a.attacker))

    # ---- scenario ----------------------------------------------------------------------------

    def _run(self, ours: List[DE.Action], hi: Dict[str, int], foe_acts: Dict[str, FoeAct],
             cut: Dict[str, int], protecting: Set[str]) -> float:
        pmf: Dict[str, np.ndarray] = {}
        start: Dict[str, float] = {}
        occ = {"a0": "a0", "a1": "a1"}            # our slot -> id of the mon standing in it
        blocked: Set[str] = set(protecting)       # ids whose incoming hits are blocked
        fskip: Dict[str, float] = {}              # foe -> P(flinched before acting)
        oskip: Dict[int, float] = {}              # our slot -> P(flinched before acting)

        def get(t: str) -> np.ndarray:
            if t not in pmf:
                h = self.world[t].hyps[hi.get(t, 0)]
                pmf[t] = _pmf(h)
                start[t] = float(min(h.cur_hp, h.max_hp))
            return pmf[t]

        def alive(t: str) -> float:
            return 1.0 - get(t)[0] if t in self.world else 1.0

        def our_hit(k: int, a: DE.Action) -> None:
            if is_switch(a):
                occ[f"a{a.attacker}"] = a.targets[0]
                return
            me = occ[f"a{a.attacker}"]
            if is_protect(a):
                blocked.add(me)
                return
            pa = alive(me) * (1.0 - oskip.get(a.attacker, 0.0))
            single = _is_single(a.move) and len(a.targets) == 1
            for t in a.targets:
                tid = occ.get(t, t)
                p = pa * self._p_hit_id(a.move, tid) * (tid not in blocked)
                p_dead = get(tid)[0]
                r = self.rolls(a, tid, hi.get(tid, 0))
                pmf[tid] = _apply(get(tid), r, p)
                if a.move == FAKE_OUT and tid in cut and cut[tid] > k:
                    pfl = p * float((r > 0).mean())
                    fskip[tid] = 1.0 - (1.0 - fskip.get(tid, 0.0)) * (1.0 - pfl)
                if single and t.startswith("o") and p_dead > 1e-9:
                    other = "o1" if t == "o0" else "o0"
                    if other in self.world and other not in blocked:
                        ra = DE.Action(a.attacker, a.move, (other,))
                        pmf[other] = _apply(get(other), self.rolls(ra, other, hi.get(other, 0)),
                                            pa * self._p_hit_id(a.move, other) * p_dead)

        def foe_hit(fid: str, fa: FoeAct) -> None:
            pf = alive(fid) * (1.0 - fskip.get(fid, 0.0))
            single = _is_single(fa.move) and len(fa.targets) == 1
            n = len(fa.targets)
            for t in fa.targets:
                tid = occ.get(t, t)
                p = pf * self._p_hit_id(fa.move, tid) * (tid not in blocked)
                p_dead = get(tid)[0]
                r = self._foe_rolls(fid, hi.get(fid, 0), fa.move, tid, hi.get(tid, 0), n)
                pmf[tid] = _apply(get(tid), r, p)
                if fa.move == FAKE_OUT and t in occ:
                    s = int(t[1])
                    oskip[s] = 1.0 - (1.0 - oskip.get(s, 0.0)) * (1.0 - p * float((r > 0).mean()))
                if single and t in occ and p_dead > 1e-9:
                    o = occ["a1" if t == "a0" else "a0"]
                    if o in self.world and o not in blocked:
                        pmf[o] = _apply(get(o), self._foe_rolls(fid, hi.get(fid, 0), fa.move, o,
                                                                hi.get(o, 0), 1),
                                        pf * self._p_hit_id(fa.move, o) * p_dead)

        slots: List[List[str]] = [[] for _ in range(len(ours) + 1)]
        for f in foe_acts:
            slots[cut[f]].append(f)
        for k in range(len(ours) + 1):
            for f in slots[k]:
                foe_hit(f, foe_acts[f])
            if k < len(ours):
                our_hit(k, ours[k])

        total = 0.0
        for t, dist in pmf.items():
            c = self.world[t]
            h = c.hyps[hi.get(t, 0)]
            e_hp = float((dist * np.arange(len(dist))).sum())
            v = (start[t] - e_hp) / h.max_hp + self.ko_bonus * float(dist[0])
            total += (-self.ally_weight * v) if c.is_ally else v
        return total

    def pair_value(self, actions: Sequence[Optional[DE.Action]]) -> float:
        acts = self._sort_ours([a for a in actions if a is not None])
        key = tuple(acts)
        if key in self._joint:
            return self._joint[key]
        benched = [a.targets[0] for a in acts if is_switch(a)]
        if len(set(benched)) < len(benched):
            self._joint[key] = CONFLICT
            return CONFLICT
        passive = sum(is_switch(a) or is_protect(a) for a in acts)
        foe_ids = [f for f in self.world if f.startswith("o")]
        hyp_axes = [list(enumerate(self.world[f].hyps)) for f in foe_ids]
        kind_ids = list(self._kinds)
        total = 0.0
        for combo in itertools.product(*hyp_axes):
            wh = 1.0
            hi = {}
            for fid, (i, h) in zip(foe_ids, combo):
                wh *= h.weight
                hi[fid] = i
            for kinds in itertools.product(*[self._kinds[f] for f in kind_ids]):
                wk = wh
                for _, p, _ in kinds:
                    wk *= p
                if wk < MIN_SCENARIO_P:
                    continue
                total += wk * self._outcome(acts, hi, kind_ids, kinds)
        total -= self.passive_cost * passive
        self._joint[key] = total
        return total

    def _outcome(self, acts: List[DE.Action], hi: Dict[str, int], kind_ids: List[str],
                 kinds: Sequence[Tuple[str, float, Optional[str]]]) -> float:
        """Value of our `acts` summed over the speed-order cuts, for one hypothesis and one foe outcome."""
        acting = frozenset(f for f, (k, _, _) in zip(kind_ids, kinds) if k == "atk")
        plan = self._plan(hi, acting) if acting else {}
        foe_acts: Dict[str, FoeAct] = {}
        protecting: Set[str] = set()
        for f, (k, _, tgt) in zip(kind_ids, kinds):
            if k == "atk" and f in plan:
                foe_acts[f] = plan[f]
            elif k == "fakeout":
                foe_acts[f] = FoeAct(FAKE_OUT, (tgt,), move_priority(FAKE_OUT))
            elif k == "protect":
                protecting.add(f)
        order_ids = list(foe_acts)
        order = {f: self._order_dist(f, hi.get(f, 0), acts, foe_acts[f].priority) for f in order_ids}
        value = 0.0
        for cuts in itertools.product(*[list(order[f].items()) for f in order_ids]):
            w = 1.0
            cut = {}
            for fid, (c, pc) in zip(order_ids, cuts):
                w *= pc
                cut[fid] = c
            value += w * self._run(acts, hi, foe_acts, cut, protecting)
        return value


def choose_pair_refined(coarse: "TurnSim", fine: "TurnSim", cands_a: Sequence[Optional[DE.Action]],
                        cands_b: Sequence[Optional[DE.Action]], min_gain: float = DE.MIN_GAIN,
                        top_k: int = 6) -> Tuple[int, int, float, float]:
    """`choose_pair` in two stages: every pair is screened with the cheap `coarse` sim, then the
    `top_k` pairs (plus the baseline) are scored with `fine`. Same return and baseline rule."""
    ranked = sorted(((coarse.pair_value((a, b)), ia, ib) for ia, a in enumerate(cands_a)
                     for ib, b in enumerate(cands_b) if (ia, ib) != (0, 0)), reverse=True)
    base = fine.pair_value((cands_a[0], cands_b[0]))
    best, best_v = (0, 0), base
    for _, ia, ib in ranked[:top_k]:
        v = fine.pair_value((cands_a[ia], cands_b[ib]))
        if v > best_v + (min_gain if best == (0, 0) else 0.0):
            best, best_v = (ia, ib), v
    return best[0], best[1], best_v, base
