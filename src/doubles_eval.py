"""Joint (two-slot) attack evaluation for doubles — pure logic, no poke_env.

The vanilla heuristic picks each slot's move independently, so it can never see
that two attackers together KO a target neither can KO alone, that a second
attacker is wasted on an already-dead target, or that a spread move like
Earthquake hurts our own partner. This module scores a *pair* of attack actions
in one unit — expected fraction of an opposing mon's max HP removed, plus a KO
bonus, minus the same for our own ally — so those cases fall out of one number.

Hidden opposing stats are a mixture of plausible builds (src.opp_model); both
attackers hitting the same target share the same hypothesis, so focus-fire KO
probability is computed against one build at a time, then mixed.

Not modelled (deliberately; each is its own follow-up): speed order, Protect /
Fake Out / redirection, opposing retaliation, secondary effects, item/ability
damage modifiers on the *defender*.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

import numpy as np

from src import damage
from src import support_value as SV

KO_BONUS = 1.0      # swept 0-4 (2026-10-16): plateau from 1.0 up; 0 is ~4 pts worse
ALLY_WEIGHT = 1.0   # damage/KO on our own mon costs as much as it gains on a foe
MIN_GAIN = 0.01     # deviate from the baseline pair only for a real improvement


@dataclass
class Hypothesis:
    weight: float
    stats: Dict[str, int]
    max_hp: int
    cur_hp: int
    types: Optional[List[str]] = None   # overrides Combatant.types (a Mega form changes typing)
    speeds: Optional[List[Tuple[float, Optional[int]]]] = None   # (weight, effective Speed) given THIS build (turn_sim)


@dataclass
class Combatant:
    """Anything that can be hit: an opposing mon (several hypotheses) or our ally (one)."""
    hyps: List[Hypothesis]
    types: List[str]
    boosts: Dict[str, int] = field(default_factory=dict)
    is_ally: bool = False
    immune_prob: Dict[str, float] = field(default_factory=dict)   # move type -> P(nullified)


@dataclass
class Attacker:
    stats: Dict[str, int]
    types: List[str]
    boosts: Dict[str, int] = field(default_factory=dict)
    burn: bool = False
    ability: Optional[str] = None
    final_mult: float = 1.0          # e.g. Life Orb 1.3, applied to every roll


@dataclass(frozen=True)
class Action:
    attacker: int                    # our slot index, 0 or 1
    move: str                        # DB-resolvable move name or id
    targets: Tuple[str, ...]         # combatant ids hit: 'o0','o1' (foes), 'a0','a1' (ours)


def _accuracy(move: str) -> float:
    acc = (damage.DB.get_move(move) or {}).get("accuracy")
    return acc / 100.0 if isinstance(acc, (int, float)) and not isinstance(acc, bool) else 1.0


def _capped(rolls: np.ndarray, hp: int) -> Tuple[float, float]:
    """(E[min(dmg, hp)], P(dmg >= hp)) over equally likely rolls."""
    return float(np.minimum(rolls, hp).mean()), float((rolls >= hp).mean())


class Evaluator:
    """Scores sets of simultaneous attack actions against a fixed world snapshot."""

    def __init__(self, attackers: Dict[int, Attacker], world: Dict[str, Combatant],
                 weather: Optional[str] = None, terrain: Optional[str] = None,
                 ko_bonus: float = KO_BONUS, ally_weight: float = ALLY_WEIGHT,
                 effects: FrozenSet[str] = frozenset()):
        self.attackers = attackers
        self.effects = effects
        self.world = world
        self.weather = weather
        self.terrain = terrain
        self.ko_bonus = ko_bonus
        self.ally_weight = ally_weight
        self._rolls: Dict[tuple, np.ndarray] = {}
        self._joint: Dict[tuple, float] = {}

    def modelable(self, move: str) -> bool:
        mv = damage.DB.get_move(move)
        return bool(mv and mv.get("category") != "Status" and (mv.get("basePower") or 0) > 0)

    def p_hit(self, action: Action, tid: str) -> float:
        mv = damage.DB.get_move(action.move)
        immune = self.world[tid].immune_prob.get(mv["type"], 0.0)
        return _accuracy(action.move) * (1.0 - immune)

    def rolls(self, action: Action, tid: str, hi: int) -> np.ndarray:
        key = (action, tid, hi)
        if key not in self._rolls:
            atk = self.attackers[action.attacker]
            tgt = self.world[tid]
            stats, boosts = atk.stats, atk.boosts
            if "foulplay" in self.effects and SV.is_foulplay(action.move):
                stats = {**stats, "atk": tgt.hyps[hi].stats["atk"]}          # attacks with the TARGET's Attack
                boosts = {**boosts, "atk": tgt.boosts.get("atk", 0)}
            r = damage.damage_rolls_from_stats(
                stats, atk.types, boosts, action.move,
                tgt.hyps[hi].stats, tgt.hyps[hi].types or tgt.types, tgt.boosts,
                is_doubles=True, include_spread=len(action.targets) > 1,
                burn=atk.burn, weather=self.weather, terrain=self.terrain,
                attacker_ability=atk.ability)
            if atk.final_mult != 1.0:
                r = [int(x * atk.final_mult) for x in r]
            self._rolls[key] = np.array(r if r else [0], dtype=np.int64)
        return self._rolls[key]

    def _hits(self, hits: Sequence[Tuple[Action, float]], tid: str, hi: int) -> Tuple[float, float]:
        """(E[capped damage], P(KO)) on target `tid`, hypothesis `hi`, given the actions hitting it."""
        hp = self.world[tid].hyps[hi].cur_hp
        if len(hits) == 1:
            (a, p), = hits
            e, k = _capped(self.rolls(a, tid, hi), hp)
            return p * e, p * k
        (a, pa), (b, pb) = hits
        ra, rb = self.rolls(a, tid, hi), self.rolls(b, tid, hi)
        both = (ra[:, None] + rb[None, :]).ravel()
        e = k = 0.0
        for prob, arr in ((pa * pb, both), (pa * (1 - pb), ra), ((1 - pa) * pb, rb)):
            if prob > 0:
                ce, ck = _capped(arr, hp)
                e += prob * ce
                k += prob * ck
        return e, k

    def pair_value(self, actions: Sequence[Optional[Action]]) -> float:
        acts = tuple(a for a in actions if a is not None)
        key = frozenset(enumerate(acts)) if len(acts) < 2 else (acts[0], acts[1])
        if key in self._joint:
            return self._joint[key]
        total = 0.0
        for tid, comb in self.world.items():
            hits = [(a, self.p_hit(a, tid)) for a in acts if tid in a.targets]
            if not hits:
                continue
            sign = -self.ally_weight if comb.is_ally else 1.0
            for hi, h in enumerate(comb.hyps):
                e, k = self._hits(hits, tid, hi)
                total += sign * h.weight * (e / h.max_hp + self.ko_bonus * k)
        self._joint[key] = total
        return total


def choose_pair(ev: Evaluator, cands_a: Sequence[Optional[Action]],
                cands_b: Sequence[Optional[Action]],
                min_gain: float = MIN_GAIN) -> Tuple[int, int, float, float]:
    """Best (index_a, index_b) over the candidate cross product.

    Index 0 of each list is the baseline (the vanilla pilot's pick). The baseline pair
    wins unless another pair beats it by more than `min_gain`. Returns
    (ia, ib, best_value, baseline_value).
    """
    base = ev.pair_value((cands_a[0], cands_b[0]))
    best, best_v = (0, 0), base
    for ia, a in enumerate(cands_a):
        for ib, b in enumerate(cands_b):
            if (ia, ib) == (0, 0):
                continue
            v = ev.pair_value((a, b))
            if v > best_v + (min_gain if best == (0, 0) else 0.0):
                best, best_v = (ia, ib), v
    return best[0], best[1], best_v, base
