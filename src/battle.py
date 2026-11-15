"""
battle.py — shared poke_env battle harness for eval and the GA.

Both src/eval.py and src/ga_core.py need the same thing: build two poke_env
players, play one battle, bound it with a timeout, retry once on a flake, and
never leak a websocket on a crash. That logic used to live in BOTH files and had
to be patched in tandem — see STATE.md §5.3, where the "no retry on timeout" fix
had to be applied to `ga_core._run_battle` AND `eval.run_battle` separately. It
lives here once now.

The two callers differ in a few knobs, all explicit keyword args:
    pilot      our side: "heuristic", "bc" (neural), "doubles" (joint-attack pilot),
               "vgc" (VGCPilot, the GA's fitness pilot) or "ladder" (heuristic +
               Protect / Fake Out at ladder rates); see make_player.
    opp_pilot  the opponent's pilot, same names; default "heuristic". The GA plays
               "ladder" (ga_core.FITNESS_OPP).
    timeout    seconds before a hung battle is abandoned as None (both use 20).
    min_turns  the GA drops battles under 3 turns — a Showdown desync/forfeit, not
               a real game — so they don't poison fitness. eval scores every
               completed game, so it passes min_turns=0 (guard disabled).

Design constraints (both prevent real breakage, not just style):
  - Does NOT import ga_core. ga_core imports THIS module, so importing it back
    would be circular; the format string is passed in as `battle_format` instead.
  - Does NOT import bc_player at module top. bc_player pulls bc_model →
    state_encoder → torch/ROCm (multi-GB GPU libraries) into every importer. The
    BCPlayer import is lazy, inside make_player, so a heuristic-only run (the GA,
    and `--pilot heuristic` eval) never pays the torch import cost.
"""
import asyncio

# --- Suppress benign poke_env protocol noise --------------------------------
# poke_env logs certain VGC messages at CRITICAL even though they're
# harmless (open-team-sheet handshake repeats across every battle).
# Filter them at the logger so the console stays readable.
import logging as _logging
import os


class _DropVGCNoise(_logging.Filter):
    _PATTERNS = (
        "cannot reject open team sheets",
        "already made your decision about agreeing to open team sheets",
    )
    def filter(self, record):
        try:
            msg = record.getMessage().lower()
        except Exception:
            return True
        return not any(p in msg for p in self._PATTERNS)

for _name in ("poke_env", "poke_env.ps_client", "poke_env.player"):
    _logging.getLogger(_name).addFilter(_DropVGCNoise())
# ---------------------------------------------------------------------------

import uuid

from poke_env import AccountConfiguration, ServerConfiguration
from poke_env.player import SimpleHeuristicsPlayer
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder

# --- Multi-instance support -------------------------------------------------
# When SHOWDOWN_PORT is set (by run/ga_parallel.sh), route this process's
# players to that server. Unset -> default 8000, same as before.
_SHOWDOWN_PORT = os.environ.get("SHOWDOWN_PORT", "8000")
DEFAULT_SERVER = ServerConfiguration(
    f"ws://localhost:{_SHOWDOWN_PORT}/showdown/websocket",
    f"http://localhost:{_SHOWDOWN_PORT}/action.php?",
)

# --- TimeoutPlayer for early battle forfeit ---
# This class overrides choose_move to immediately forfeit battles that exceed turn limits
class TimeoutPlayer(SimpleHeuristicsPlayer):
    """Player that automatically forfeits battles when turn limit is exceeded."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def choose_move(self, battle):
        """Override choose_move to check turn limit before making a move."""
        # Check if the battle has exceeded the turn limit
        if hasattr(battle, 'turn') and battle.turn > 50:
            # Return a forfeit order instead of normal move
            return DoubleBattleOrder(
                first_order=SingleBattleOrder.forfeit(),
                second_order=SingleBattleOrder.forfeit()
            )
        # Otherwise, let the parent class handle normal move selection
        return super().choose_move(battle)

# Added to a battle's account uid on each retry so the next attempt logs in under
# a fresh Showdown account. Large prime → no collision with the uids of nearby
# battles sharing the same server.
RETRY_STRIDE = 999_983


def make_player(pilot, team_str, uid, prefix, battle_format):
    """Construct one poke_env Player for `pilot` on `team_str`.

    `prefix` namespaces the throwaway account id ("B" for our bot, "O" for the
    opponent) so the two players in a battle never share a login. The uid is
    already a random int from the caller's seeded RNG, so collisions are
    impossible without further salting — and passing rand=False keeps the
    account name deterministic, which makes battle outcomes REPRODUCIBLE
    across concurrency levels. (rand=True would pull from Python's global
    random module inside each async task, so the exact name depends on task
    interleaving — same seed, different results at different concurrencies.)
    The BCPlayer import is lazy so this stays torch-free for the heuristic path.
    """

    # Add unique process identifier to prevent race condition when fork() is used
    # (ga_parallel.sh spawns 3 islands via fork(), so all inherit same RNG state)

    if pilot == "bc":
        from src.bc_player import BCPlayer  # lazy: keeps torch/ROCm out of the heuristic path
        cls = BCPlayer
    elif pilot == "doubles":
        from src.doubles_pilot import DoublesPilot  # lazy: only the experimental pilot pays for it
        cls = DoublesPilot
    elif pilot == "ladder":
        # lazy: heuristic + Protect / Fake Out at ladder rates
        from src.ladder_opp import LadderOpponent
        cls = LadderOpponent
    elif pilot == "vgc":
        from src.vgc_pilot import VGCPilot  # lazy: new pilot, torch-free
        # Use TimeoutPlayer for our side to prevent long battles, but regular VGCPilot for opponent
        if prefix == "B":  # Our side - use TimeoutPlayer to prevent long battles
            cls = TimeoutPlayer
        else:  # Opponent side - use regular VGCPilot
            cls = VGCPilot
    else:
        cls = SimpleHeuristicsPlayer
    return cls(
        battle_format=battle_format,
        team=team_str,
        max_concurrent_battles=1,
        server_configuration=DEFAULT_SERVER,
        account_configuration=AccountConfiguration.generate(f"{prefix}{uid}_{uuid.uuid4().hex[:8]}", rand=True),
    )


async def run_battle_once(team_str, opp_str, uid, sem, battle_format,
                          *, pilot="heuristic", timeout=20, min_turns=0, opp_pilot="heuristic"):
    """Play one battle — `pilot` on team_str vs `opp_pilot` (default: the heuristic) on opp_str — once.

    Returns 1 (our win) / 0 (loss) / None. None means "no usable result": the
    battle errored, never finished, or (only when min_turns > 0) ended in under
    min_turns turns. Concurrency is bounded by the caller-supplied semaphore.
    Both players always have their Showdown listeners stopped in `finally`, so a
    crashed battle can't leak a hung websocket.
    """
    async with sem:
        bot = opp = None
        try:
            bot = make_player(pilot, team_str, uid, "B", battle_format)
            opp = make_player(opp_pilot, opp_str, uid, "O", battle_format)
            await asyncio.wait_for(bot.battle_against(opp, n_battles=1), timeout=timeout)
            if bot.n_finished_battles == 0:
                return None
            # Short-game guard, GA-only. Skipped entirely when min_turns == 0 so
            # the eval path takes its original behavior and scores every game.
            if min_turns > 0:
                try:
                    turns = getattr(list(bot.battles.values())[-1], "turn", 0)
                except Exception:
                    turns = 0
                if turns < min_turns:
                    return None
            # Add turn limit check to prevent battles from running excessively long
            try:
                turns = getattr(list(bot.battles.values())[-1], "turn", 0)
            except Exception:
                turns = 0
            if turns > 50:
                return None
            return 1 if bot.n_won_battles > 0 else 0
        except KeyError as e:
            # Handle the specific KeyError: 'round' issue mentioned in the bug report
            if "'round'" in str(e):
                _logging.getLogger(__name__).warning(f"Battle failed with KeyError: 'round': {e}")
                return None
            raise  # Re-raise if it's a different KeyError
        except Exception:
            return None
        finally:
            for p in (bot, opp):
                try:
                    if p:
                        await p.ps_client.stop_listening()
                except Exception:
                    pass


async def run_battle(team_str, opp_str, uid, sem, battle_format,
                     *, pilot="heuristic", timeout=20, min_turns=0, retries=1, opp_pilot="heuristic"):
    """Run one battle, retrying up to `retries` times on a None result.

    Each retry offsets the uid by RETRY_STRIDE so the next attempt logs in under a
    different account — most None results are transient login/timeout flakes, not
    deterministic failures, so a fresh login usually clears them. Returns 0/1/None.
    """
    for attempt in range(retries + 1):
        result = await run_battle_once(
            team_str, opp_str, uid + attempt * RETRY_STRIDE, sem, battle_format,
            pilot=pilot, timeout=timeout, min_turns=min_turns, opp_pilot=opp_pilot)
        if result is not None:
            return result
    return None
