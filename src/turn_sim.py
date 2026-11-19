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
  - Support layer (src.support_value, off unless `effects` names them): Foul Play uses the target's
    Attack; Snarl / Charm lower a foe's Atk / Sp. Atk (in-turn on the foe hits that come later, plus a
    persistence term for the turns after); Helping Hand x1.5 on the partner's attack; Taunt cancels a
    Trick Room the foe was about to set; a self-heal restores HP at its place in the move order (no
    `support_cost`: the lost attack is already the opportunity cost). Other pure-support actions pay `support_cost`.
  - HP is propagated as a probability vector per combatant; an actor acts with the probability it is
    still alive when its turn comes. Accuracy is per hit; no crits, secondary effects (other than
    Fake Out's flinch) or items.
  - Value = sum over foes of (HP fraction removed + KO_BONUS * P(KO)) minus the same for our mons
    (foe retaliation and our own spread damage), so the unit matches the Evaluator.

Layout: this file enumerates the scenarios (foe hypotheses x foe outcomes x speed-order cuts,
`pair_value` -> `_outcome` -> `_run`) and models the foes (`_plan`, `_foe_rolls`, `_order_dist`);
one scenario is played out by src/turn_sim_resolve.py::Resolution (split out 2026-11-18).
"""
from __future__ import annotations

import itertools
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

import numpy as np

from src import damage
from src import doubles_eval as DE
from src import support_value as SV
from src.turn_sim_lookahead import LookAhead
from src.turn_sim_resolve import Resolution
from src.turn_sim_types import (
    BLOCKING,
    COARSE_HYPS,
    COARSE_OUTCOME_P,
    CONFLICT,
    FAKE_OUT,
    MAX_HYPS,
    MIN_OUTCOME_P,
    MIN_SCENARIO_P,
    PASSIVE_COST,
    SHORTLIST,
    SINGLE_TARGET,
    SWITCH,
    SWITCH_PRIORITY,
    TOP_K,
    FoeAct,
    FoeInfo,
    Speeds,
    _flip,
    _is_physical,
    _prune,
    act_priority,
    is_protect,
    is_support,
    is_switch,
    move_priority,
)

__all__ = [
    # Core API
    "TurnSim", "LookAhead", "choose_pair_refined",
    # Types
    "FoeInfo", "FoeAct", "Speeds",
    # Constants (re-exported for callers like tests/test_turn_sim.py)
    "MAX_HYPS", "MIN_SCENARIO_P", "MIN_OUTCOME_P", "SINGLE_TARGET",
    "BLOCKING", "SWITCH", "FAKE_OUT", "SWITCH_PRIORITY", "PASSIVE_COST",
    "CONFLICT", "SHORTLIST", "TOP_K", "COARSE_HYPS", "COARSE_OUTCOME_P",
    # Helpers
    "move_priority", "act_priority", "is_switch", "is_protect", "is_support",
]
class TurnSim(DE.Evaluator):
    def __init__(self, attackers: Dict[int, DE.Attacker], world: Dict[str, DE.Combatant],
                 our_speed: Dict[int, int], foes: Dict[str, FoeInfo], trick_room: bool = False,
                 weather: Optional[str] = None, terrain: Optional[str] = None,
                 ko_bonus: float = DE.KO_BONUS, ally_weight: float = DE.ALLY_WEIGHT,
                 max_hyps: int = MAX_HYPS, passive_cost: float = PASSIVE_COST,
                 min_outcome_p: float = MIN_OUTCOME_P, effects: FrozenSet[str] = frozenset(),
                 support_cost: float = SV.SUPPORT_COST, tr_left: int = 0):
        pruned = {t: (_prune(c, max_hyps) if t.startswith("o") else c) for t, c in world.items()}
        super().__init__(attackers, pruned, weather, terrain, ko_bonus, ally_weight, effects)
        self.support_cost = support_cost
        self.our_speed = our_speed
        self.trick_room = trick_room
        self.tr_left = tr_left if trick_room else 0       # turns of Trick Room left incl. this one
        self.passive_cost = passive_cost
        self.min_outcome_p = min_outcome_p
        self.foes = {f: i for f, i in foes.items() if f in pruned}
        self._foe_rolls_cache: Dict[tuple, np.ndarray] = {}
        self._plans: Dict[tuple, Dict[str, FoeAct]] = {}
        self._orders: Dict[tuple, Dict[int, float]] = {}
        self._p_hits: Dict[tuple, float] = {}
        self._threat: Dict[int, float] = {}
        self._cands: Dict[int, Sequence[Optional[DE.Action]]] = {}
        self._tr_active = False                       # a Taunt is a candidate and Trick Room is down
        self._tr_cost_v: Optional[float] = None
        self._gains: Dict[tuple, float] = {}
        self._drop_outs: Dict[tuple, list] = {}
        self.la: Optional["LookAhead"] = None         # state-delta continuation; None = the heuristic terms
        self._sink = None                             # (weight, hi, pmf) callback used to build the leaf state
        self._build_kinds()

    # ---- foe outcomes ------------------------------------------------------------------------

    def set_candidates(self, cands: Dict[int, Sequence[Optional[DE.Action]]]) -> None:
        """Our candidate actions per slot: a foe's Fake Out goes to the slot whose attack is worth most."""
        self._threat = {}
        self._cands = dict(cands)
        for slot, acts in cands.items():
            vals = [DE.Evaluator.pair_value(self, (a,)) for a in acts
                    if a is not None and not is_switch(a) and not is_protect(a) and not is_support(a)
                    and a.attacker in self.attackers]
            self._threat[slot] = max(vals + [0.0])
        self._tr_active = ("taunt" in self.effects and not self.trick_room
                           and any(a is not None and a.move == "taunt" for acts in cands.values() for a in acts))
        self._tr_cost_v = None
        self._joint.clear()
        self._build_kinds()

    def enable_lookahead(self, la: Optional["LookAhead"] = None) -> "LookAhead":
        """Value state changes by their next-turn effect (see LookAhead); call after `set_candidates`."""
        self.la = la or LookAhead(self)
        self._joint.clear()
        return self.la

    def disable_lookahead(self) -> None:
        self.la = None
        self._joint.clear()

    def shortlist(self, acts: Sequence[Optional[DE.Action]], k: int) -> List[int]:
        """Indices worth simulating: the baseline (0), every Fake Out / Protect / switch, and the `k`
        best other attacks by their solo (no-order) value."""
        keep, plain = {0}, []
        for i, a in enumerate(acts):
            if a is None or is_switch(a) or is_protect(a) or is_support(a) or a.move == FAKE_OUT:
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
            taunted = info.taunt_left > 0                    # a Taunted foe cannot select Protect or Trick Room
            pp = 0.0 if taunted else min(max(info.protect, 0.0), 1.0 - pf)
            pt = min(max(info.trickroom, 0.0), 1.0 - pf - pp) if self._tr_active and not taunted else 0.0
            ok = min(max(info.protect_ok, 0.0), 1.0)
            raw: List[Tuple[str, float, Optional[str]]] = [("atk", 1.0 - pf - pp - pt, None)]
            raw += [("fakeout", pf * wt, t) for t, wt in zip(mine, w)]
            raw += [("protect", pp * ok, None), ("idle", pp * (1.0 - ok), None)]
            if pt > 0.0:
                raw.append(("tr", pt, None))
            raw = [r for r in raw if r[1] >= self.min_outcome_p]
            s = sum(r[1] for r in raw)
            self._kinds[f] = [(k, p / s, t) for k, p, t in raw]

    # ---- foe action model (stand-in) ---------------------------------------------------------

    def _foe_rolls(self, fid: str, hf: int, move: str, tid: str, ht: int, n_targets: int,
                   dlt: int = 0) -> np.ndarray:
        """Damage rolls of a foe move; `dlt` = stages added to the foe's attacking stat (Snarl / Charm)."""
        key = (fid, hf, move, tid, ht, n_targets, dlt)
        if key not in self._foe_rolls_cache:
            fc, tc = self.world[fid], self.world[tid]
            fh, th = fc.hyps[hf], tc.hyps[ht]
            stats, boosts = fh.stats, fc.boosts
            if dlt:
                stat = "atk" if _is_physical(move) else "spa"
                boosts = {**boosts, stat: SV.shifted(boosts.get(stat, 0), dlt)}
            if "foulplay" in self.effects and SV.is_foulplay(move):
                stats = {**stats, "atk": th.stats["atk"]}
                boosts = {**boosts, "atk": tc.boosts.get("atk", 0)}
            r = damage.damage_rolls_from_stats(
                stats, fh.types or fc.types, boosts, move,
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
        ev = DE.Evaluator(attackers, view, self.weather, self.terrain, self.ko_bonus, self.ally_weight,
                          self.effects)
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

    def _drop_outcomes(self, drop: SV.Drop, fid: str) -> list:
        key = (drop, fid)
        if key not in self._drop_outs:
            info = self.foes.get(fid)
            self._drop_outs[key] = SV.drop_outcomes(drop, info.abilities if info else None)
        return self._drop_outs[key]

    def _drop_gain(self, drop: SV.Drop, fid: str, hi: Dict[str, int]) -> float:
        """Expected fraction of our mons' HP that one landed `drop` on foe `fid` saves per later turn,
        against the move the mirror policy has that foe use (damage only, no KO bonus)."""
        foe_ids = [f for f in self.world if f.startswith("o")]
        key = (drop, fid, tuple((f, hi.get(f, 0)) for f in foe_ids))
        if key in self._gains:
            return self._gains[key]
        fa = self._plan(hi).get(fid)
        gain = 0.0
        if fa is not None:
            phys = _is_physical(fa.move)
            outs = self._drop_outcomes(drop, fid)
            for t in fa.targets:
                if not t.startswith("a") or t not in self.world:
                    continue
                th = self.world[t].hyps[hi.get(t, 0)]
                scale = self._p_hit_id(fa.move, t) / th.max_hp

                def dmg(dlt: int) -> float:
                    r = self._foe_rolls(fid, hi.get(fid, 0), fa.move, t, hi.get(t, 0), len(fa.targets), dlt)
                    return float(np.minimum(r, th.cur_hp).mean()) * scale
                base = dmg(0)
                gain += sum(pr * (base - dmg(da if phys else ds)) for pr, da, ds in outs)
        self._gains[key] = gain
        return gain

    def _tr_cost(self) -> float:
        """Value (our view, usually < 0) of a Trick Room going up: the best attack pair with Trick Room
        up minus without, over `TR_HORIZON` turns. Taunt prevents it, so this is what Taunt earns."""
        if self._tr_cost_v is None:
            cands = {s: ([a for a in acts if a is not None and not is_switch(a) and not is_protect(a)
                          and not is_support(a) and a.move != FAKE_OUT] or [None])
                     for s, acts in self._cands.items()}

            def best(tr: bool) -> float:
                sim = TurnSim(self.attackers, self.world, self.our_speed, self.foes, tr, self.weather,
                              self.terrain, self.ko_bonus, self.ally_weight, COARSE_HYPS, self.passive_cost,
                              COARSE_OUTCOME_P, self.effects, self.support_cost)
                sim.set_candidates(cands)
                keep = {s: [acts[i] for i in sim.shortlist(acts, 2)] for s, acts in cands.items()}
                return max(sim.pair_value((a, b)) for a in keep.get(0, [None]) for b in keep.get(1, [None]))
            self._tr_cost_v = SV.TR_HORIZON * (best(True) - best(False))
        return self._tr_cost_v

    # ---- scenario ----------------------------------------------------------------------------

    def _run(self, ours: List[DE.Action], hi: Dict[str, int], foe_acts: Dict[str, FoeAct],
             cut: Dict[str, int], protecting: Set[str], trfoes: FrozenSet[str] = frozenset(),
             wt: float = 0.0) -> float:
        """Value of one scenario: hypotheses `hi`, foe actions, speed-order `cut` (foe -> how many of
        our sorted actions move before it), foes that Protect / set Trick Room. Played out in move
        order by src/turn_sim_resolve.py::Resolution; `wt` is the scenario weight for the leaf sink."""
        return Resolution(self, hi, cut, protecting).run(ours, foe_acts, trfoes, wt)

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
        pure = sum(is_support(a) and SV.pure_kind(a.move) != "heal" for a in acts)
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
                total += wk * self._outcome(acts, hi, kind_ids, kinds, wk)
        total -= self.passive_cost * passive + self.support_cost * pure
        self._joint[key] = total
        return total

    def _outcome(self, acts: List[DE.Action], hi: Dict[str, int], kind_ids: List[str],
                 kinds: Sequence[Tuple[str, float, Optional[str]]], wk: float = 0.0) -> float:
        """Value of our `acts` summed over the speed-order cuts, for one hypothesis and one foe outcome."""
        acting = frozenset(f for f, (k, _, _) in zip(kind_ids, kinds) if k == "atk")
        plan = self._plan(hi, acting) if acting else {}
        foe_acts: Dict[str, FoeAct] = {}
        protecting: Set[str] = set()
        trfoes = frozenset(f for f, (k, _, _) in zip(kind_ids, kinds) if k == "tr")
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
            value += w * self._run(acts, hi, foe_acts, cut, protecting, trfoes, wk * w)
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
