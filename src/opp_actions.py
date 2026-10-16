"""Foe action prediction: P(a foe mon uses a Protect-family move / Fake Out THIS turn).

Pure logic, no poke_env. The one-turn simulator branches on these two probabilities per foe
mon. Rates come from data/opp_actions.json (tools/build_opp_actions.py, fitted on real ladder
replays). Each target is a table over a few cheap context features (does the mon already have
the move revealed, how long it has been on the field, did it just Protect, lead vs back ...)
times a per-species factor shrunk toward 1 (does this species usually carry the move).

`foe_ctx` is the single place that turns a BattleMemory record into features; the fitting tool
and the pilot both call it, so there is no off-by-one drift between fit and inference.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

from src import battle_memory as BM
from src.paths import data_path

RATES_PATH = Path(data_path("opp_actions.json"))
MAX_P = 0.98
DEFAULT_CELL = 0.05        # a context absent from the rates file (never happens on the fitted corpus)


@dataclass(frozen=True)
class FoeCtx:
    species: str                  # DB/showdown species of the foe mon (base form is fine)
    turn: int                     # the turn being decided (>= 1)
    age: int                      # turns on the field before this one: 0 = entered during the
    #                               previous turn (or a turn-1 lead), i.e. Fake Out is legal now
    lead: bool                    # turn == 1 (a starting lead)
    known_moves: frozenset        # move ids revealed so far (lowercase alnum), may include OTS moves
    moves_complete: bool          # True only if known_moves is the full 4-move set (OTS)
    protect_chain: int            # consecutive successful Protect-family uses ending on turn-1
    protect_uses: int             # Protect-family uses so far in the battle
    hp_frac: float                # current HP fraction 0..1


@dataclass(frozen=True)
class ActionProbs:
    fakeout: float                # P(uses Fake Out this turn)
    protect: float                # P(uses a Protect-family move this turn) (not that it succeeds)


def base_species(species: str) -> str:
    """'Charizard-Mega-X' -> 'Charizard' (a foe's Mega form shares its base form's move pool)."""
    return species.split("-Mega")[0]


def foe_ctx(mem: BM.BattleMemory, side: str, name: str, turn: int, known_moves=(),
            moves_complete: bool = False, hp_frac: float = 1.0) -> FoeCtx:
    """Features of foe mon `name` for the decision on `turn`.

    Works for both call conventions: the pilot calls it with mem.turn == turn (the |turn|N line
    already fed), the fitting tool before feeding turn `turn`'s chunk (mem.turn == turn - 1).
    Only actions stamped before `turn` are used, so the two agree. `known_moves` is merged with
    the moves this mon was seen using in earlier turns."""
    rec = mem.mon_by(side, name)
    if rec is None:
        return FoeCtx("", turn, 0, turn == 1, frozenset(_ids(known_moves)), moves_complete, 0, 0, hp_frac)
    seen = {a.move for t, acts in mem.actions.items() if t < turn for a in acts
            if a.kind == "move" and a.side == side and a.name == name and a.move}
    chain = rec.protect_chain if rec.protect_last_turn == turn - 1 else 0
    return FoeCtx(base_species(rec.species), turn, max(turn - 1 - rec.switch_in_turn, 0), turn == 1,
                  frozenset(seen | set(_ids(known_moves))), moves_complete, chain,
                  rec.protect_uses, hp_frac)


def _ids(moves):
    return [BM._id(m) for m in moves]


# ---- cells ---------------------------------------------------------------------------------
# Each target has a fine cell and a coarser parent; the fit smooths a fine cell toward its
# parent, and a fine cell never seen in the fit falls back to the parent (then to DEFAULT_CELL).
def protect_revealed(ctx: FoeCtx) -> bool:
    """The mon is known to carry a Protect-family move (used one, or one is in known_moves)."""
    return ctx.protect_uses > 0 or bool(ctx.known_moves & BM.PROTECT_FAMILY)


def _hp_bucket(hp: float) -> str:
    return "h0" if hp <= 0.5 else "h1" if hp < 1.0 else "h2"


def protect_keys(ctx: FoeCtx) -> Tuple[str, str]:
    """(cell, parent) of the Protect table.

    revealed: x consecutive successes ending last turn (0 / 1 / 2+) x age (0 / 1+) x HP bucket.
    not revealed: x age (0 / 1 / 2 / 3+) x HP bucket. Parent drops the HP bucket."""
    h = _hp_bucket(ctx.hp_frac)
    if protect_revealed(ctx):
        parent = f"rev|c{min(ctx.protect_chain, 2)}|a{min(ctx.age, 1)}"
    else:
        parent = f"new|a{min(ctx.age, 3)}"
    return f"{parent}|{h}", parent


def fakeout_keys(ctx: FoeCtx) -> Tuple[str, str]:
    """(cell, parent) of the Fake Out table: revealed or not x lead or mid-game switch-in."""
    parent = "rev" if "fakeout" in ctx.known_moves else "new"
    return f"{parent}|{'lead' if ctx.lead else 'back'}", parent


def species_applies(ctx: FoeCtx, target: str) -> bool:
    """The species factor only describes 'does this species carry the move'; moot once revealed."""
    return not (protect_revealed(ctx) if target == "protect" else "fakeout" in ctx.known_moves)


# ---- probabilities -------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _rates() -> dict:
    return json.loads(RATES_PATH.read_text())


def cell_p(ctx: FoeCtx, target: str, r: dict) -> float:
    """Table rate for this context (no species factor)."""
    t = r[target]
    key, parent = (protect_keys if target == "protect" else fakeout_keys)(ctx)
    return t["cells"].get(key, t["parents"].get(parent, DEFAULT_CELL))


def _p_one(ctx: FoeCtx, target: str, r: dict) -> float:
    p = cell_p(ctx, target, r)
    if species_applies(ctx, target):
        p *= r[target]["species_rel"].get(ctx.species, 1.0)
    return min(max(p, 0.0), MAX_P)


def action_probs(ctx: FoeCtx, rates: Optional[dict] = None) -> ActionProbs:
    """P(Fake Out), P(Protect-family) this turn; fakeout + protect <= 1."""
    r = rates or _rates()
    fo = 0.0 if ctx.age > 0 else _p_one(ctx, "fakeout", r)
    pr = _p_one(ctx, "protect", r)
    if ctx.moves_complete:
        if "fakeout" not in ctx.known_moves:
            fo = 0.0
        if not protect_revealed(ctx):
            pr = 0.0
    total = fo + pr
    if total > MAX_P:
        fo, pr = fo * MAX_P / total, pr * MAX_P / total
    return ActionProbs(fakeout=fo, protect=pr)
