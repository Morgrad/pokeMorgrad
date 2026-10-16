"""Battle memory: per-battle facts poke_env does not track (foundation for the new pilot).

`BattleMemory.feed(split_line)` consumes one Showdown protocol line already split on
'|' (e.g. ['', 'move', 'p1a: X', 'Protect', 'p1a: X']). It is pure and poke_env-free, so
it is tested on real replay logs. `BattleMemoryMixin` hooks a poke_env Player and feeds
every line of a message block BEFORE poke_env processes it, so memory is complete by the
time `choose_move` runs even if the `|request|` line sits in the middle of the block.

Turn stamping: `|turn|N` is emitted when turn N begins, and everything resolved during
turn N (moves, residuals, end-of-turn condition expiry) follows it. A condition set on
turn s with base length L is active on turns s..s+L-1 and its end message is stamped
s+L-1. At decision time on turn t, turns left (including t) = s + L - t.

Tracks: Mega (exact form from |detailschange|, stone from |-mega|; poke_env keeps neither
correctly for the Z line), weather / terrain / Trick Room / side conditions with start
turn and source, per-turn chosen-action order for speed inference (with a taint set for
turns whose order is not pure speed), Protect-family stall chain, and the raw inputs for
Unburden / Quick Feet / Slow Start (item consumed, status, turns since switch-in).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src import regmc_db as DB

# share the stall counter (Wide Guard / Quick Guard / Mat Block do not: measured 0 fails in
# 130+ consecutive uses on real replays, Protect fails 67% on its second consecutive use)
PROTECT_FAMILY = {
    "protect", "detect", "endure", "kingsshield", "spikyshield", "banefulbunker",
    "obstruct", "silktrap", "burningbulwark",
}
WEATHERS = {"RainDance", "Sandstorm", "SunnyDay", "Snow", "Hail", "DesolateLand",
            "PrimordialSea", "DeltaStream"}
TERRAINS = {"Electric Terrain", "Grassy Terrain", "Misty Terrain", "Psychic Terrain"}
PERMANENT_WEATHER = {"DesolateLand", "PrimordialSea", "DeltaStream"}
# base length, length when extended by an item we may not have seen (Rocks / Light Clay /
# Terrain Extender)
DURATIONS = {
    "weather": (5, 8), "terrain": (5, 8), "Trick Room": (5, 5), "Tailwind": (4, 4),
    "Reflect": (5, 8), "Light Screen": (5, 8), "Aurora Veil": (5, 8),
    "Gravity": (5, 5), "Magic Room": (5, 5), "Wonder Room": (5, 5),
}
# `-activate` lines that mean this turn's order is not decided by Speed alone
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


class BattleMemory:
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

    # ---- queries -------------------------------------------------------------------
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

    # ---- ingestion -----------------------------------------------------------------
    def feed(self, p: List[str]) -> None:
        if len(p) < 2:
            return
        ev = p[1]
        awaiting, self._awaiting = self._awaiting, None
        h = getattr(self, "_on_" + ev.lstrip("-").replace("-", "_"), None)
        if ev == "-fail" or ev == "-singleturn":
            self._protect_result(awaiting, ev, p)
        if h:
            h(p)

    def _rec(self, ident: str) -> MonRecord:
        k = _key(ident)
        r = self.mons.get(k)
        if r is None:
            r = self.mons[k] = MonRecord(side=k[0], name=k[1], first_seen_turn=self.turn,
                                         switch_in_turn=self.turn)
        return r

    def _log(self, ident: str, kind: str, move: Optional[str] = None,
             priority: int = 0, chosen: bool = True) -> Action:
        rec = self._rec(ident)
        a = Action(self.turn, self._seq, _side(ident), _slot(ident), rec.name, kind,
                   move, priority, megaed=_key(ident) in self._megaed_now, chosen=chosen)
        self._seq += 1
        self.actions.setdefault(self.turn, []).append(a)
        if kind in ("move", "cant") and chosen and self.turn not in self.first_mover:
            self.first_mover[self.turn] = a
        return a

    def _taint(self, why: str) -> None:
        self.taint.setdefault(self.turn, set()).add(why)

    def _on_turn(self, p):
        self.turn = int(p[2])
        self._upkeep = False
        self._moved_this_turn = False
        self._megaed_now = set()
        self._seq = 0

    def _on_upkeep(self, p):
        self._upkeep = True

    def _on_switch(self, p, drag: bool = False):
        ident, details = p[2], p[3]
        rec = self._rec(ident)
        rec.species = _species(details)
        rec.switch_in_turn = self.turn
        rec.slow_start = False
        rec.protect_chain = 0
        rec.protect_last_turn = None
        chosen = (not drag) and not self._upkeep and not self._moved_this_turn
        self._log(ident, "drag" if drag else "switch", chosen=chosen)

    def _on_drag(self, p):
        self._on_switch(p, drag=True)

    def _on_detailschange(self, p):
        rec = self._rec(p[2])
        rec.species = _species(p[3])
        self._pending_form[_key(p[2])] = rec.species

    def _on_mega(self, p):
        ident, stone = p[2], p[4] if len(p) > 4 else p[3]
        rec = self._rec(ident)
        rec.mega_form = self._pending_form.pop(_key(ident), rec.species)
        rec.mega_stone = stone
        rec.mega_turn = self.turn
        rec.item = stone
        self.mega_used[_side(ident)] = self.turn
        self._megaed_now.add(_key(ident))

    def _on_move(self, p):
        ident, move = p[2], p[3]
        tags = [x for x in p[5:] if x.startswith("[from]")]
        if any(t != "[from]lockedmove" for t in tags):
            return                      # Dancer/Instruct/Sleep Talk copies are not actions
        self._moved_this_turn = True
        mv = DB.get_move(move)
        prio = (mv or {}).get("priority", 0) if mv else 0
        self._log(ident, "move", _id(move), prio)
        rec = self._rec(ident)
        if _id(move) in PROTECT_FAMILY:
            rec.protect_uses += 1
            self._awaiting = _key(ident)
        else:
            rec.protect_chain = 0
            rec.protect_last_turn = None

    def _protect_result(self, awaiting, ev, p):
        if awaiting is None or len(p) < 3 or _key(p[2]) != awaiting:
            return
        rec = self.mons.get(awaiting)
        if rec is None:
            return
        if ev == "-fail":
            rec.protect_fails += 1
            rec.protect_chain = 0
            rec.protect_last_turn = None
        else:
            consecutive = rec.protect_last_turn == self.turn - 1
            rec.protect_chain = rec.protect_chain + 1 if consecutive else 1
            rec.protect_last_turn = self.turn

    def _on_cant(self, p):
        self._moved_this_turn = True
        self._log(p[2], "cant")

    def _on_faint(self, p):
        self._rec(p[2]).fainted = True

    def _on_status(self, p):
        self._rec(p[2]).status = p[3]

    def _on_curestatus(self, p):
        self._rec(p[2]).status = None

    def _on_item(self, p):
        self._rec(p[2]).item = _id(p[3])

    def _on_enditem(self, p):
        rec = self._rec(p[2])
        rec.item_consumed = True
        rec.item = None

    def _on_start(self, p):
        if len(p) > 3 and p[3] == "ability: Slow Start":
            self._rec(p[2]).slow_start = True

    def _on_end(self, p):
        if len(p) > 3 and p[3] == "Slow Start":
            self._rec(p[2]).slow_start = False

    def _on_showteam(self, p):
        sets = []
        for entry in "|".join(p[3:]).split("]"):
            f = entry.split("|")
            if len(f) < 6 or not (f[0] or f[1]):
                continue
            species = f[1] or f[0]
            sets.append({"species": species, "id": _id(species), "item": _id(f[2]),
                         "ability": _id(f[3]), "moves": [_id(x) for x in f[4].split(",") if x],
                         "nature": f[5], "gender": f[7] if len(f) > 7 else ""})
        if sets:
            self.ots[p[2]] = sets

    def _on_activate(self, p):
        if len(p) > 3 and p[3] in TAINT_ACTIVATE:
            self._taint(TAINT_ACTIVATE[p[3]])

    # ---- conditions ----------------------------------------------------------------
    def _from_src(self, p):
        src = next((x[7:].strip() for x in p if x.startswith("[from]")), None)
        of = next((x[5:].strip() for x in p if x.startswith("[of]")), None)
        return src, of

    def _start_turn(self) -> int:
        # set after this turn's residual tick (turn-0 switch-ins, end-of-turn replacements):
        # the first tick it faces is next turn's, so it effectively starts then
        return self.turn + 1 if (self._upkeep or self.turn == 0) else self.turn

    def _begin(self, scope, name, kind, p):
        src, of = self._from_src(p)
        c = Condition(name, scope, kind, self._start_turn(), source=src or "move", setter=of)
        self.conditions[(scope, name)] = c
        return c

    def _finish(self, key, reason="expired"):
        c = self.conditions.pop(key, None)
        if c is not None:
            c.end_turn, c.end_reason = self.turn, reason
            self.history.append(c)

    def _on_weather(self, p):
        name = p[2]
        if name == "none":
            self._end_weather("expired")
        elif "[upkeep]" in p:
            return
        elif self.weather is None or self.weather.name != name:
            self._end_weather("replaced")
            src, of = self._from_src(p)
            self.weather = Condition(name, "field", "weather", self._start_turn(),
                                     source=src or "move", setter=of)

    def _end_weather(self, reason):
        if self.weather is not None:
            self.weather.end_turn, self.weather.end_reason = self.turn, reason
            self.history.append(self.weather)
        self.weather = None

    @staticmethod
    def _cname(raw: str) -> str:
        return raw.split(": ", 1)[1] if raw.startswith("move: ") else raw

    def _on_fieldstart(self, p):
        name = self._cname(p[2])
        if name in TERRAINS:
            for t in TERRAINS - {name}:
                self._finish(("field", t), "replaced")
        self._begin("field", name, "terrain" if name in TERRAINS else name, p)

    def _on_fieldend(self, p):
        self._finish(("field", self._cname(p[2])))

    def _on_sidestart(self, p):
        side, name = _side(p[2]), self._cname(p[3])
        prev = self.conditions.get((side, name))
        c = self._begin(side, name, name, p)
        if prev is not None and name in ("Spikes", "Toxic Spikes"):
            c.layers = prev.layers + 1
            c.start_turn = prev.start_turn

    def _on_sideend(self, p):
        self._finish((_side(p[2]), self._cname(p[3])))


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
