"""Types, constants, and helpers for turn_sim. Split from turn_sim.py for modularity."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import numpy as np

from src import damage
from src import doubles_eval as DE
from src import support_value as SV
from src.battle_memory import PROTECT_FAMILY

MAX_HYPS = 4
MIN_SCENARIO_P = 1e-4
MIN_OUTCOME_P = 0.005
SINGLE_TARGET = ("normal", "any")
BLOCKING = PROTECT_FAMILY - {"endure"}        # Endure survives a hit, it does not block it
SWITCH = "switch"
FAKE_OUT = "fakeout"
SWITCH_PRIORITY = 8
PASSIVE_COST = float(os.environ.get("DOUBLES_PASSIVE_COST", 0.30))
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
    trickroom: float = 0.0                        # P(sets Trick Room this turn); read only when a Taunt is a candidate
    abilities: Optional[Dict[str, float]] = None  # ability id -> P, for stat-drop blockers / punishers
    taunt_left: int = 0                           # turns it stays Taunted (counting this one): no Protect / Trick Room


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


def is_support(a: DE.Action) -> bool:
    """Pure-support action (Helping Hand, Taunt, a status stat drop): no damage, valued by its effect."""
    return not is_switch(a) and SV.pure_kind(a.move) is not None


@lru_cache(maxsize=None)
def _is_physical(move: str) -> bool:
    return (damage.DB.get_move(move) or {}).get("category") == "Physical"


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



__all__ = [
    'FoeInfo', 'FoeAct', 'Speeds',
    'MAX_HYPS', 'MIN_SCENARIO_P', 'MIN_OUTCOME_P', 'SINGLE_TARGET',
    'BLOCKING', 'SWITCH', 'FAKE_OUT', 'SWITCH_PRIORITY', 'PASSIVE_COST',
    'CONFLICT', 'SHORTLIST', 'TOP_K', 'COARSE_HYPS', 'COARSE_OUTCOME_P',
    'move_priority', 'act_priority', 'is_switch', 'is_protect', 'is_support',
    '_is_physical', '_is_single', '_prune', '_pmf', '_apply', '_flip',
]
