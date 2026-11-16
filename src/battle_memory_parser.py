from __future__ import annotations

from typing import List, Optional

from src import regmc_db as DB
from src.battle_memory_types import (
    PROTECT_FAMILY,
    TAINT_ACTIVATE,
    TERRAINS,
    VOLATILES,
    Action,
    Condition,
    MonRecord,
    _id,
    _key,
    _side,
    _slot,
    _species,
)


class BattleMemoryParserMixin:
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
        self.active[ident[:3]] = rec.name
        rec.slow_start = False
        rec.protect_chain = 0
        rec.protect_last_turn = None
        rec.volatiles.clear()
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
        rec = self._rec(p[2])
        rec.fainted = True
        rec.volatiles.clear()


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
        v = self._volatile_name(p)
        if v:
            self._rec(p[2]).volatiles[v] = self._start_turn()


    def _on_end(self, p):
        if len(p) > 3 and p[3] == "Slow Start":
            self._rec(p[2]).slow_start = False
        v = self._volatile_name(p)
        if v:
            self._rec(p[2]).volatiles.pop(v, None)


    @staticmethod
    def _volatile_name(p) -> Optional[str]:
        if len(p) < 4:
            return None
        name = p[3][6:] if p[3].startswith("move: ") else p[3]
        return name if name in VOLATILES else None


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

