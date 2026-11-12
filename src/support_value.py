"""Support-move layer, pure data side (no poke_env): which effects are on, how a move's effect is read
from the DB, and what a foe's ability does to a stat drop.

Effects (slice 1), each gated by name so a paired run can switch them one at a time:
  foulplay     Foul Play damage uses the TARGET's Attack stat and stage (overrideOffensivePokemon).
  snarl        a damaging move whose secondary lowers the target's Atk / Sp. Atk (Snarl, Mystical Fire ...).
  charm        a Status move that lowers the target's Atk / Sp. Atk (Charm, Growl, Noble Roar ...).
  helpinghand  Helping Hand: x1.5 on the partner's attack this turn.
  taunt        Taunt: a Trick Room the taunted foe was about to set fails (Taunt +0 beats Trick Room -7).
  heal         a Status move that restores a fraction of the user's own HP (Recover, Roost, Moonlight ...).
`DOUBLES_SUPPORT` is a comma list of these or `all`; empty = layer off (behaviour identical to before).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, FrozenSet, List, Mapping, Optional, Tuple

from src import damage

EFFECTS = ("foulplay", "snarl", "charm", "helpinghand", "taunt", "heal")
DEFAULT_SUPPORT = "all"             # support layer enabled by default after validation

SUPPORT_COST = float(os.environ.get("DOUBLES_SUPPORT_COST", 0.15))       # tempo cost of a pure-support turn
SUPPORT_HORIZON = float(os.environ.get("DOUBLES_SUPPORT_HORIZON", 2.0))  # further turns a stat drop keeps paying
FOE_STAY = float(os.environ.get("DOUBLES_SUPPORT_STAY", 0.7))            # P(the dropped foe is still in play)
TR_HORIZON = float(os.environ.get("DOUBLES_TR_HORIZON", 2.0))            # turns of Trick Room a Taunt denies
DEFAULT_LOOKAHEAD = False       # state-delta continuation (turn_sim.LookAhead); flip after the paired result
LOOKAHEAD_GAMMA = float(os.environ.get("DOUBLES_LOOKAHEAD_GAMMA", 0.7))  # per-turn discount of a later turn
TR_TURNS_AFTER_SET = 4          # Trick Room set this turn is still up for the next 4 turns
HELPING_HAND_MULT = 1.5
MAX_STAGE = 6

BLOCK_ALL = frozenset({"clearbody", "whitesmoke", "fullmetalbody", "mirrorarmor"})   # Mirror Armor reflects: treated as a block
BLOCK_ATK = frozenset({"hypercutter"})
BLOCK_SECONDARY = frozenset({"shielddust"})
BLOCK_STATUS = frozenset({"magicbounce", "goodasgold"})
PUNISH = {"defiant": "atk", "competitive": "spa"}     # +2 in this stat whenever a stat is lowered by a foe


def lookahead_enabled(flag: Optional[bool] = None) -> bool:
    """None: env DOUBLES_LOOKAHEAD (1/0), then DEFAULT_LOOKAHEAD."""
    if flag is not None:
        return flag
    return os.environ.get("DOUBLES_LOOKAHEAD", "1" if DEFAULT_LOOKAHEAD else "0") == "1"


def discounted_turns(n: int, gamma: float = LOOKAHEAD_GAMMA) -> float:
    """Value weight of an effect that is still active for the next `n` turns: gamma + gamma^2 + ... + gamma^n."""
    return sum(gamma ** k for k in range(1, n + 1))


def parse_effects(spec: Optional[str] = None) -> FrozenSet[str]:
    """Effects named by `spec` (None: env DOUBLES_SUPPORT, then DEFAULT_SUPPORT)."""
    if spec is None:
        spec = os.environ.get("DOUBLES_SUPPORT", DEFAULT_SUPPORT)
    spec = spec.strip().lower()
    if spec in ("", "0", "off", "none"):
        return frozenset()
    if spec in ("all", "1", "on"):
        return frozenset(EFFECTS)
    names = {s.strip() for s in spec.split(",") if s.strip()}
    unknown = names - set(EFFECTS)
    if unknown:
        raise ValueError(f"unknown support effect(s) {sorted(unknown)}; known: {EFFECTS}")
    return frozenset(names)


@dataclass(frozen=True)
class Drop:
    deltas: Tuple[Tuple[str, int], ...]        # (('spa', -1),) ; only atk / spa are modelled
    chance: float                              # 1.0 for a primary effect
    kind: str                                  # 'secondary' (damaging move) | 'status'


@lru_cache(maxsize=None)
def foe_drop(move: str) -> Optional[Drop]:
    """The Atk / Sp. Atk drop `move` puts on a foe it hits, read from the DB effect fields."""
    mv = damage.DB.get_move(move)
    if not mv or mv.get("selfSwitch"):
        return None
    status = mv.get("category") == "Status"
    if status:
        raw, chance, kind = mv.get("boosts"), 1.0, "status"
        if (mv.get("target") or "") not in ("normal", "any", "allAdjacentFoes"):
            return None
    else:
        sec = mv.get("secondary") or {}
        raw, chance, kind = sec.get("boosts"), float(sec.get("chance", 100)) / 100.0, "secondary"
    deltas = tuple(sorted((s, int(d)) for s, d in (raw or {}).items() if s in ("atk", "spa") and d < 0))
    return Drop(deltas, chance, kind) if deltas else None


# Weather-dependent heals the DB keeps as a function, not a fraction: {move: (clear, sun, bad weather)}.
WEATHER_HEALS = {"moonlight": (0.5, 2 / 3, 0.25), "synthesis": (0.5, 2 / 3, 0.25), "morningsun": (0.5, 2 / 3, 0.25)}
BAD_WEATHER = frozenset({"rain", "sand", "snow", "hail"})


def _mid(move: str) -> str:
    return "".join(c for c in move.lower() if c.isalnum())


@lru_cache(maxsize=None)
def _fixed_heal(move: str) -> float:
    mv = damage.DB.get_move(move)
    if not mv or mv.get("category") != "Status" or mv.get("target") not in ("self", "adjacentAllyOrSelf"):
        return 0.0
    n, d = mv.get("heal") or (0, 1)
    return n / d


def heal_fraction(move: str, weather: Optional[str] = None) -> float:
    """Fraction of its max HP the user restores with `move` (0.0: not a self-heal)."""
    w = WEATHER_HEALS.get(_mid(move))
    if w is not None:
        return w[1] if weather == "sun" else w[2] if weather in BAD_WEATHER else w[0]
    return _fixed_heal(move)


@lru_cache(maxsize=None)
def pure_kind(move: str) -> Optional[str]:
    """'helpinghand' | 'taunt' | 'heal' | 'drop' for a move that does no damage and is valued only by its effect."""
    mv = damage.DB.get_move(move)
    if not mv:
        return None
    mid = "".join(c for c in move.lower() if c.isalnum())
    if mid == "helpinghand":
        return "helpinghand"
    if mid == "taunt":
        return "taunt"
    if heal_fraction(move) > 0.0:
        return "heal"
    if mv.get("category") == "Status" and foe_drop(move) is not None:
        return "drop"
    return None


def effect_of(move: str) -> Optional[str]:
    """The effect name (an EFFECTS entry) `move` belongs to, or None."""
    mid = "".join(c for c in move.lower() if c.isalnum())
    if mid == "foulplay":
        return "foulplay"
    pk = pure_kind(move)
    if pk == "drop":
        return "charm"
    if pk:
        return pk
    d = foe_drop(move)
    return "snarl" if d is not None and d.kind == "secondary" else None


def pure_enabled(move: str, effects: FrozenSet[str]) -> bool:
    pk = pure_kind(move)
    return bool(pk) and ("charm" if pk == "drop" else pk) in effects


def is_foulplay(move: str) -> bool:
    return (damage.DB.get_move(move) or {}).get("overrideOffensivePokemon") == "target"


def _clamp(x: int) -> int:
    return max(-MAX_STAGE, min(MAX_STAGE, x))


def drop_outcomes(drop: Drop, abilities: Optional[Mapping[str, float]]) -> List[Tuple[float, int, int]]:
    """[(probability, d_atk, d_spa)] the foe ends up with from one use of `drop` that hit it.

    Folds in the move's secondary chance and the foe's ability distribution: blockers (Clear Body ...),
    Hyper Cutter (Atk only), Shield Dust (secondary only), Magic Bounce / Good as Gold (status moves
    only), Contrary (reverses), Simple (doubles), Defiant / Competitive (+2 in their stat once any drop lands)."""
    abil = dict(abilities) if abilities else {None: 1.0}
    tot = sum(abil.values()) or 1.0
    out: Dict[Tuple[int, int], float] = {}
    for ab, pa in abil.items():
        pa /= tot
        dd = dict(drop.deltas)
        blocked = (ab in BLOCK_ALL or (drop.kind == "secondary" and ab in BLOCK_SECONDARY)
                   or (drop.kind == "status" and ab in BLOCK_STATUS))
        if ab in BLOCK_ATK:
            dd.pop("atk", None)
        if blocked or not dd:
            out[(0, 0)] = out.get((0, 0), 0.0) + pa
            continue
        da, ds = dd.get("atk", 0), dd.get("spa", 0)
        lowered = True
        if ab == "contrary":
            da, ds, lowered = -da, -ds, False
        elif ab == "simple":
            da, ds = 2 * da, 2 * ds
        if lowered and PUNISH.get(ab) == "atk":
            da += 2
        elif lowered and PUNISH.get(ab) == "spa":
            ds += 2
        out[(da, ds)] = out.get((da, ds), 0.0) + pa * drop.chance
        out[(0, 0)] = out.get((0, 0), 0.0) + pa * (1.0 - drop.chance)
    return [(p, da, ds) for (da, ds), p in out.items() if p > 0]


def shifted(boost: int, delta: int) -> int:
    """Stage after applying `delta` to `boost`, clamped to +-6."""
    return _clamp(boost + delta)
