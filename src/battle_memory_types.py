from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

PROTECT_FAMILY = {
    "protect", "detect", "endure", "kingsshield", "spikyshield", "banefulbunker",
    "obstruct", "silktrap", "burningbulwark",
}


WEATHERS = {"RainDance", "Sandstorm", "SunnyDay", "Snow", "Hail", "DesolateLand",
            "PrimordialSea", "DeltaStream"}


TERRAINS = {"Electric Terrain", "Grassy Terrain", "Misty Terrain", "Psychic Terrain"}


PERMANENT_WEATHER = {"DesolateLand", "PrimordialSea", "DeltaStream"}


DURATIONS = {
    "weather": (5, 8), "terrain": (5, 8), "Trick Room": (5, 5), "Tailwind": (4, 4),
    "Reflect": (5, 8), "Light Screen": (5, 8), "Aurora Veil": (5, 8),
    "Gravity": (5, 5), "Magic Room": (5, 5), "Wonder Room": (5, 5),
}


VOLATILES = {"Taunt": 3, "Encore": 3, "Yawn": 2}


TAINT_ACTIVATE = {"move: After You": "after_you", "move: Quash": "quash",
                  "item: Quick Claw": "quick_claw", "item: Custap Berry": "custap",
                  "ability: Dancer": "dancer", "move: Instruct": "instruct"}


def _id(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())


def _side(ident: str) -> str:
    return ident[:2]


def _key(ident: str) -> Tuple[str, str]:
    return ident[:2], ident.split(": ", 1)[1] if ": " in ident else ident


def _slot(ident: str) -> str:
    return ident[2] if len(ident) > 2 and ident[2] in "abc" else ""


def _species(details: str) -> str:
    return details.split(",")[0].strip()


@dataclass
class Condition:
    name: str
    scope: str                     # 'field' | 'p1' | 'p2'
    kind: str                      # key into DURATIONS, or '' for open-ended (hazards)
    start_turn: int
    source: Optional[str] = None   # e.g. 'ability: Sand Stream', 'move', None
    setter: Optional[str] = None   # ident of the setter when known
    end_turn: Optional[int] = None
    end_reason: Optional[str] = None   # 'expired' | 'replaced'
    layers: int = 1


@dataclass
class Action:
    turn: int
    seq: int
    side: str
    slot: str
    name: str
    kind: str                      # 'move' | 'cant' | 'switch' | 'drag'
    move: Optional[str] = None
    priority: int = 0
    megaed: bool = False           # mon Mega Evolved earlier this same turn
    chosen: bool = True            # False for forced switches (pivot / replacement / drag)


@dataclass
class MonRecord:
    side: str
    name: str
    species: str = ""
    first_seen_turn: int = 0
    switch_in_turn: int = 0
    mega_form: Optional[str] = None
    mega_stone: Optional[str] = None
    mega_turn: Optional[int] = None
    item: Optional[str] = None
    item_consumed: bool = False
    status: Optional[str] = None
    slow_start: bool = False
    fainted: bool = False
    protect_uses: int = 0
    protect_fails: int = 0
    protect_chain: int = 0         # consecutive turns of successful Protect-family use
    protect_last_turn: Optional[int] = None
    volatiles: Dict[str, int] = field(default_factory=dict)   # VOLATILES name -> start turn
