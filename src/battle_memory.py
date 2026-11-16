from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from src.battle_memory_parser import BattleMemoryParserMixin
from src.battle_memory_types import (
    DURATIONS,
    PERMANENT_WEATHER,
    PROTECT_FAMILY,
    TAINT_ACTIVATE,
    TERRAINS,
    VOLATILES,
    WEATHERS,
    Action,
    Condition,
    MonRecord,
    _id,
    _key,
    _side,
)

__all__ = [
    "BattleMemory", "BattleMemoryMixin", "repair_mega_forms",
    "PROTECT_FAMILY", "WEATHERS", "TERRAINS", "PERMANENT_WEATHER",
    "DURATIONS", "VOLATILES", "TAINT_ACTIVATE",
    "Condition", "Action", "MonRecord",
]


class BattleMemory(BattleMemoryParserMixin):
    def __init__(self):
        self.turn = 0
        self.mons: Dict[Tuple[str, str], MonRecord] = {}
        self.mega_used: Dict[str, Optional[int]] = {"p1": None, "p2": None}
        self.weather: Optional[Condition] = None
        self.conditions: Dict[Tuple[str, str], Condition] = {}
        self.history: List[Condition] = []        # ended conditions
        self.actions: Dict[int, List[Action]] = {}
        self.taint: Dict[int, set] = {}
        self.first_mover: Dict[int, Action] = {}
        self._seq = 0
        self._upkeep = False
        self._moved_this_turn = False
        self._pending_form: Dict[Tuple[str, str], str] = {}
        self._awaiting: Optional[Tuple[str, str]] = None
        self._megaed_now: set = set()
        self.repaired: set = set()
        self.ots: Dict[str, List[dict]] = {}     # Open Team Sheet sets by side, when shown
        self.active: Dict[str, str] = {}         # 'p1a' -> mon name currently in that slot


    def mon(self, ident: str) -> Optional[MonRecord]:
        return self.mons.get(_key(ident))


    def mon_by(self, side: str, name: str) -> Optional[MonRecord]:
        return self.mons.get((side, name))


    def ots_set(self, ident_or_species: str, side: Optional[str] = None) -> Optional[dict]:
        """Open Team Sheet set (species, item, ability, moves, nature, gender) for a mon,
        matched by species (a Mega form matches its base). None if no sheet was shown."""
        if side is None and ": " in ident_or_species:
            side, ident_or_species = _side(ident_or_species), _key(ident_or_species)[1]
        want = _id(ident_or_species)
        for sd in ([side] if side else list(self.ots)):
            for st in self.ots.get(sd, []):
                if want == st["id"] or (want.startswith(st["id"]) and "mega" in want[len(st["id"]):]):
                    return st
        return None


    def active_mons(self, side: str) -> List[MonRecord]:
        """Records of the mons currently in `side`'s slots (fainted ones included until replaced)."""
        return [r for slot in "ab" if (n := self.active.get(side + slot)) and (r := self.mon_by(side, n))]


    def mega_available(self, side: str) -> bool:
        return self.mega_used.get(side) is None


    def protect_success_prob(self, ident: str, turn: Optional[int] = None) -> float:
        """Chance a Protect-family move works if used on `turn` (default: current)."""
        rec = self.mon(ident)
        t = self.turn if turn is None else turn
        if rec is None or rec.protect_last_turn != t - 1 or rec.protect_chain <= 0:
            return 1.0
        return 1.0 / (3 ** min(rec.protect_chain, 6))


    def speed_flags(self, ident: str) -> dict:
        rec = self.mon(ident)
        if rec is None:
            return {}
        return {"item_consumed": rec.item_consumed, "status": rec.status,
                "slow_start": rec.slow_start,
                "turns_since_switch_in": self.turn - rec.switch_in_turn}


    def condition(self, scope: str, name: str) -> Optional[Condition]:
        return self.conditions.get((scope, name))


    def terrain(self) -> Optional[Condition]:
        for (scope, name), c in self.conditions.items():
            if scope == "field" and name in TERRAINS:
                return c
        return None


    def turns_left(self, cond: Optional[Condition], now: Optional[int] = None):
        """(min, max) turns the condition is still active, counting turn `now`.

        max assumes a duration-extending item may be present; None = open-ended."""
        if cond is None or cond.end_turn is not None:
            return (0, 0)
        if cond.name in PERMANENT_WEATHER or cond.kind not in DURATIONS:
            return None
        t = self.turn if now is None else now
        base, ext = DURATIONS[cond.kind]
        return (max(cond.start_turn + base - t, 0), max(cond.start_turn + ext - t, 0))


    def volatile_left(self, ident: str, name: str, now: Optional[int] = None) -> int:
        """Turns the volatile `name` (Taunt, Encore, Yawn) is still active on mon `ident`, counting
        turn `now`; 0 = not active. Taunt / Encore are not extended by anything we model."""
        rec = self.mons.get(_key(ident))
        start = rec.volatiles.get(name) if rec else None
        if start is None:
            return 0
        t = self.turn if now is None else now
        return max(start + VOLATILES[name] - t, 0)


    def turn_order(self, turn: int) -> List[Action]:
        """Chosen actions in the order they resolved (switches first, then moves)."""
        return [a for a in self.actions.get(turn, []) if a.chosen and a.kind != "drag"]


    def speed_pairs(self, turn: int):
        """(faster, slower) action pairs from consecutive same-priority moves on an
        untainted turn: the only observations that are pure Speed comparisons.
        The caller must still discount Trick Room and Speed-changing abilities/items."""
        if self.taint.get(turn):
            return []
        acts = [a for a in self.turn_order(turn) if a.kind in ("move", "cant")]
        return [(x, y) for x, y in zip(acts, acts[1:]) if x.priority == y.priority
                and x.kind == "move" and y.kind == "move"]


class BattleMemoryMixin:
    """Mix in BEFORE the poke_env Player base: `class P(BattleMemoryMixin, Player)`."""

    memories: Dict[str, BattleMemory]

    def _memories(self) -> Dict[str, BattleMemory]:
        if not hasattr(self, "memories"):
            self.memories = {}
        return self.memories

    def memory_for(self, battle) -> BattleMemory:
        return self._memories().setdefault(battle.battle_tag, BattleMemory())

    async def _handle_battle_message(self, split_messages):
        tag = split_messages[0][0] if split_messages and split_messages[0] else ""
        if tag.startswith(">battle"):
            key = tag[1:]
            lines = [m for m in split_messages[1:] if len(m) > 1]
            if any(m[1] == "init" for m in lines):
                self._memories()[key] = BattleMemory()
            mem = self._memories().setdefault(key, BattleMemory())
            for m in lines:
                mem.feed(m)
        await super()._handle_battle_message(split_messages)
        if tag.startswith(">battle"):
            battle = self._battles.get(tag[1:])
            if battle is not None:
                repair_mega_forms(battle, self._memories()[tag[1:]])



def repair_mega_forms(battle, mem: BattleMemory) -> None:
    """poke_env's mega_evolve() maps the stone to '<species>mega' and overwrites the
    forme data, which is wrong for the Z line (Garchomp-Mega-Z != Garchomp-Mega). Re-apply
    the exact form logged by |detailschange|."""
    from poke_env.data import GenData
    dex = GenData.from_gen(9).pokedex
    for (side, name), rec in mem.mons.items():
        if rec.mega_form is None:
            continue
        fid = _id(rec.mega_form)
        if fid not in dex:
            continue
        for mon in list(battle.team.values()) + list(battle.opponent_team.values()):
            if mon.name == name and (name, fid) not in mem.repaired:
                mon._update_from_pokedex(fid, store_species=False)
                mem.repaired.add((name, fid))


