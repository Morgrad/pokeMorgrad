"""One-turn simulation for doubles: move order, retaliation and retargeting (pure logic, no poke_env).

`TurnSim` is a drop-in replacement for `doubles_eval.Evaluator` (same `pair_value` / `choose_pair`
interface). Where the Evaluator scores our damage as if every attack lands first, TurnSim plays the
turn out in move order, so a slower mon can be KO'd before it acts, a faster KO prevents the foe's
hit, priority moves and Trick Room/Tailwind change who benefits, and a single-target move whose
target already fainted hits the other foe (Showdown retargeting).

Model (deliberately small, each point is a follow-up if it proves to matter):
  - Foe hypotheses (stats/types/HP) come from the Combatants, pruned to the `max_hyps` heaviest.
    The foe's Speed is a separate weighted list `FoeInfo.speeds` (src.speed_model), independent of
    the damage hypothesis (the Mega case is therefore only correlated through the shared q).
  - Mirror foe: each foe makes ONE attack per turn, and the foes pick their attacks the way our own
    pilot does: the pair of (move, target) that maximises `doubles_eval` pair value from THEIR side
    (focus fire, no overkill, spread moves that hurt their partner are avoided), given the hypothesis
    being simulated (so a foe with the Mega stats picks with them). Stand-in for an opponent action
    model fitted from replays; no Protect / Fake Out / switching, and foe-on-foe damage is not applied.
  - HP is propagated as a probability vector per combatant; an actor acts with the probability it is
    still alive when its turn comes. Accuracy is per hit; no crits, secondary effects or items.
  - Value = sum over foes of (HP fraction removed + KO_BONUS * P(KO)) minus the same for our mons
    (foe retaliation and our own spread damage), so the unit matches the Evaluator.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from src import damage
from src import doubles_eval as DE

MAX_HYPS = 4
MIN_SCENARIO_P = 1e-4
SINGLE_TARGET = ("normal", "any")


@dataclass
class FoeInfo:
    moves: List[str]                              # known/assumed damaging moves (DB ids)
    speeds: List[Tuple[float, Optional[int]]]     # (weight, effective Speed); Speed None = unknown (coin flip)


@dataclass(frozen=True)
class FoeAct:
    move: str
    targets: Tuple[str, ...]                      # our combatant ids ('a0', 'a1')
    priority: int


def move_priority(move: str) -> int:
    return int((damage.DB.get_move(move) or {}).get("priority") or 0)


def _is_single(move: str) -> bool:
    return (damage.DB.get_move(move) or {}).get("target") in SINGLE_TARGET


def _prune(c: DE.Combatant, k: int) -> DE.Combatant:
    if len(c.hyps) <= k:
        return c
    top = sorted(c.hyps, key=lambda h: -h.weight)[:k]
    tot = sum(h.weight for h in top)
    hyps = [DE.Hypothesis(h.weight / tot, h.stats, h.max_hp, h.cur_hp, h.types) for h in top]
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


class TurnSim(DE.Evaluator):
    def __init__(self, attackers: Dict[int, DE.Attacker], world: Dict[str, DE.Combatant],
                 our_speed: Dict[int, int], foes: Dict[str, FoeInfo], trick_room: bool = False,
                 weather: Optional[str] = None, terrain: Optional[str] = None,
                 ko_bonus: float = DE.KO_BONUS, ally_weight: float = DE.ALLY_WEIGHT,
                 max_hyps: int = MAX_HYPS):
        pruned = {t: (_prune(c, max_hyps) if t.startswith("o") else c) for t, c in world.items()}
        super().__init__(attackers, pruned, weather, terrain, ko_bonus, ally_weight)
        self.our_speed = our_speed
        self.trick_room = trick_room
        self.foes = {f: i for f, i in foes.items() if f in pruned}
        self._foe_rolls_cache: Dict[tuple, np.ndarray] = {}
        self._plans: Dict[tuple, Dict[str, FoeAct]] = {}
        self._orders: Dict[tuple, Dict[int, float]] = {}

    # ---- foe action model (stand-in) ---------------------------------------------------------

    def _foe_rolls(self, fid: str, hi: int, move: str, tid: str, n_targets: int) -> np.ndarray:
        key = (fid, hi, move, tid, n_targets)
        if key not in self._foe_rolls_cache:
            fc, tc = self.world[fid], self.world[tid]
            fh, th = fc.hyps[hi], tc.hyps[0]
            r = damage.damage_rolls_from_stats(
                fh.stats, fh.types or fc.types, fc.boosts, move,
                th.stats, th.types or tc.types, tc.boosts,
                is_doubles=True, include_spread=n_targets > 1,
                weather=self.weather, terrain=self.terrain)
            self._foe_rolls_cache[key] = np.array(r if r else [0], dtype=np.int64)
        return self._foe_rolls_cache[key]

    def _foe_p_hit(self, move: str, tid: str) -> float:
        mv = damage.DB.get_move(move)
        return DE._accuracy(move) * (1.0 - self.world[tid].immune_prob.get(mv["type"], 0.0))

    def _plan(self, hi: Dict[str, int]) -> Dict[str, FoeAct]:
        """Mirror policy: the foes' attack pair that maximises their own doubles_eval value, given
        the hypothesis index `hi[fid]` each foe is being simulated with."""
        key = tuple(sorted((f, hi.get(f, 0)) for f in self.foes))
        if key in self._plans:
            return self._plans[key]
        mine = [t for t in ("a0", "a1") if t in self.world]
        view: Dict[str, DE.Combatant] = {}
        for t in mine:                                       # our mons are the targets in their view
            c = self.world[t]
            view["o" + t[1]] = DE.Combatant(c.hyps[:1], c.types, c.boosts, False, c.immune_prob)
        attackers: Dict[int, DE.Attacker] = {}
        for f in self.foes:
            fc, j = self.world[f], int(f[1])
            h = fc.hyps[hi.get(f, 0)]
            attackers[j] = DE.Attacker(dict(h.stats), h.types or fc.types, fc.boosts)
            view[f"a{j}"] = DE.Combatant([DE.Hypothesis(1.0, h.stats, h.max_hp, h.cur_hp, h.types)],
                                         fc.types, fc.boosts, True, fc.immune_prob)
        cands: Dict[int, List[Optional[DE.Action]]] = {0: [None], 1: [None]}
        for f, info in self.foes.items():
            j = int(f[1])
            for move in info.moves:
                if not self.modelable(move) or not mine:
                    continue
                tg = (damage.DB.get_move(move).get("target") or "")
                if tg in SINGLE_TARGET:
                    cands[j] += [DE.Action(j, move, ("o" + t[1],)) for t in mine]
                elif tg == "allAdjacentFoes":
                    cands[j].append(DE.Action(j, move, tuple("o" + t[1] for t in mine)))
                elif tg == "allAdjacent":
                    partner = f"a{1 - j}"
                    cands[j].append(DE.Action(j, move, tuple("o" + t[1] for t in mine)
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
                targets = tuple("a" + t[1] for t in act.targets if t.startswith("o"))
                plan[f"o{act.attacker}"] = FoeAct(act.move, targets, move_priority(act.move))
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

    def _order_dist(self, fid: str, ours: Sequence[DE.Action], foe_prio: int) -> Dict[int, float]:
        """{k: P(exactly the first k of our (sorted) actions move before this foe)}."""
        key = (fid, foe_prio, tuple(ours))
        if key in self._orders:
            return self._orders[key]
        out: Dict[int, float] = {}
        for w, spd in self.foes[fid].speeds:
            dist = {0: 1.0}
            for a in ours:
                p1 = self._ours_first(a.attacker, move_priority(a.move), foe_prio, spd)
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
        return sorted(acts, key=lambda a: (-move_priority(a.move), sign * self.our_speed.get(a.attacker, 0),
                                           a.attacker))

    # ---- scenario ----------------------------------------------------------------------------

    def _run(self, ours: List[DE.Action], hi: Dict[str, int], cut: Dict[str, int],
             plan: Dict[str, FoeAct]) -> float:
        pmf = {t: _pmf(c.hyps[hi.get(t, 0)]) for t, c in self.world.items()}
        start = {t: float(min(c.hyps[hi.get(t, 0)].cur_hp, c.hyps[hi.get(t, 0)].max_hp))
                 for t, c in self.world.items()}

        def alive(t: str) -> float:
            return 1.0 - pmf[t][0] if t in pmf else 1.0

        def our_hit(a: DE.Action) -> None:
            pa = alive(f"a{a.attacker}")
            single = _is_single(a.move) and len(a.targets) == 1
            for t in a.targets:
                p = pa * self.p_hit(a, t)
                other = None
                if single and t.startswith("o"):
                    other = "o1" if t == "o0" else "o0"
                    p_redirect = pmf[t][0]
                pmf[t] = _apply(pmf[t], self.rolls(a, t, hi.get(t, 0)), p)
                if other and other in pmf and p_redirect > 1e-9:
                    ra = DE.Action(a.attacker, a.move, (other,))
                    pmf[other] = _apply(pmf[other], self.rolls(ra, other, hi.get(other, 0)),
                                        pa * self.p_hit(ra, other) * p_redirect)

        def foe_hit(fid: str) -> None:
            fa = plan[fid]
            pf = alive(fid)
            single = _is_single(fa.move) and len(fa.targets) == 1
            for t in fa.targets:
                dead = pmf[t][0]
                n = len(fa.targets)
                pmf[t] = _apply(pmf[t], self._foe_rolls(fid, hi.get(fid, 0), fa.move, t, n),
                                pf * self._foe_p_hit(fa.move, t))
                if single and dead > 1e-9:
                    o = "a1" if t == "a0" else "a0"
                    if o in pmf:
                        pmf[o] = _apply(pmf[o], self._foe_rolls(fid, hi.get(fid, 0), fa.move, o, 1),
                                        pf * self._foe_p_hit(fa.move, o) * dead)

        slots: List[List[str]] = [[] for _ in range(len(ours) + 1)]
        for f in plan:
            slots[cut[f]].append(f)
        for k in range(len(ours) + 1):
            for f in slots[k]:
                foe_hit(f)
            if k < len(ours):
                our_hit(ours[k])

        total = 0.0
        for t, c in self.world.items():
            h = c.hyps[hi.get(t, 0)]
            e_hp = float((pmf[t] * np.arange(len(pmf[t]))).sum())
            v = (start[t] - e_hp) / h.max_hp + self.ko_bonus * float(pmf[t][0])
            total += (-self.ally_weight * v) if c.is_ally else v
        return total

    def pair_value(self, actions: Sequence[Optional[DE.Action]]) -> float:
        acts = self._sort_ours([a for a in actions if a is not None])
        key = tuple(acts)
        if key in self._joint:
            return self._joint[key]
        hyp_ids = [f for f in self.world if f.startswith("o")]
        hyp_axes = [list(enumerate(self.world[f].hyps)) for f in hyp_ids]
        total = 0.0
        for combo in itertools.product(*hyp_axes):
            wh = 1.0
            hi = {}
            for fid, (i, h) in zip(hyp_ids, combo):
                wh *= h.weight
                hi[fid] = i
            plan = self._plan(hi)
            order = {f: self._order_dist(f, acts, plan[f].priority) for f in plan}
            order_ids = list(order)
            for cuts in itertools.product(*[list(order[f].items()) for f in order_ids]):
                w = wh
                cut = {}
                for fid, (k, pk) in zip(order_ids, cuts):
                    w *= pk
                    cut[fid] = k
                if w >= MIN_SCENARIO_P:
                    total += w * self._run(acts, hi, cut, plan)
        self._joint[key] = total
        return total
