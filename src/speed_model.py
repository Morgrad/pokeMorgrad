"""Speed model: who moves first, as a probability (staged plan, stage 1).

We cannot see opponent speed stats, so the opponent's speed is a weighted mixture of
hypotheses built from the same priors as src/opp_model.py (top-K builds x ability
distribution). `p_faster` answers "what is the probability we move before them" for
same-priority moves, accounting for stat stages, paralysis, Tailwind, Choice Scarf,
weather/terrain speed abilities and Trick Room. Ties resolve 50/50.

Stage 1 (this file): prior mixture only. Stage 2 (planned): `SpeedBelief.observe_*`
reweights hypotheses from the observed move order. The API is stable across stages.

Torch-free and poke_env-free on purpose: pure data in, pure data out.
Not modelled yet: Choice Scarf on an unrevealed item, Unburden/Quick Feet/Slow Start,
Mega Evolution speed changes, Quick Claw / Custap / Lagging Tail / Stall.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src import damage, opp_model

# ability id -> (kind, condition) that doubles the holder's Speed
SPEED_ABILITIES = {
    "swiftswim": ("weather", "rain"),
    "chlorophyll": ("weather", "sun"),
    "sandrush": ("weather", "sand"),
    "slushrush": ("weather", "snow"),
    "surgesurfer": ("terrain", "electric"),
}


@dataclass(frozen=True)
class SpeedMods:
    """Battle-time modifiers on one mon's Speed (everything except its own ability)."""
    stage: int = 0
    paralyzed: bool = False
    tailwind: bool = False
    scarf: bool = False
    weather: Optional[str] = None     # "rain" | "sun" | "sand" | "snow" | None
    terrain: Optional[str] = None     # "electric" | "grassy" | "psychic" | "misty" | None


@dataclass(frozen=True)
class SpeedHypothesis:
    weight: float
    stat: int               # raw level-50 Speed stat, before battle modifiers
    ability: Optional[str]  # ability id, or None if irrelevant/unknown


def effective_speed(stat: int, mods: SpeedMods = SpeedMods(), ability: Optional[str] = None) -> int:
    """Battle Speed after stages and modifiers (floor after the stage, then once at the end)."""
    spe = int(stat * damage._stage_mult(mods.stage))
    mult = 1.0
    if mods.scarf:
        mult *= 1.5
    boost = SPEED_ABILITIES.get(ability or "")
    if boost and ((boost[0] == "weather" and mods.weather == boost[1])
                  or (boost[0] == "terrain" and mods.terrain == boost[1])):
        mult *= 2.0
    if mods.tailwind:
        mult *= 2.0
    if mods.paralyzed:
        mult *= 0.5
    return int(spe * mult)


class SpeedBelief:
    """Weighted hypotheses about one opposing mon's Speed."""

    def __init__(self, hypotheses: List[SpeedHypothesis]):
        total = sum(h.weight for h in hypotheses)
        self.hypotheses = [SpeedHypothesis(h.weight / total, h.stat, h.ability)
                           for h in hypotheses] if total > 0 else []

    def __bool__(self) -> bool:
        return bool(self.hypotheses)

    def speeds(self, mods: SpeedMods = SpeedMods()) -> List[tuple]:
        """[(weight, effective speed)] under the given modifiers."""
        return [(h.weight, effective_speed(h.stat, mods, h.ability)) for h in self.hypotheses]

    def p_faster(self, our_speed: int, mods: SpeedMods = SpeedMods(),
                 trick_room: bool = False) -> float:
        """P(we move before this opponent) among same-priority moves. 0.5 if no hypotheses."""
        if not self.hypotheses:
            return 0.5
        p = 0.0
        for w, theirs in self.speeds(mods):
            if our_speed == theirs:
                p += 0.5 * w
            elif (our_speed > theirs) != trick_room:
                p += w
        return p


def belief_for(species, known_ability: Optional[str] = None) -> SpeedBelief:
    """Prior speed belief for an opposing `species` (top-K builds x ability distribution)."""
    builds = opp_model.opponent_builds(species)
    if not builds:
        return SpeedBelief([])
    abilities = opp_model.ability_distribution(species, known_ability) or {None: 1.0}
    return SpeedBelief([SpeedHypothesis(b.weight * pa, b.stats["spe"], a)
                        for b in builds for a, pa in abilities.items()])
