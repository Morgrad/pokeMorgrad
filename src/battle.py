"""
battle.py — shared poke_env battle harness for eval and the GA.

Both src/eval.py and src/ga_core.py need the same thing: build two poke_env
players, play one battle, bound it with a timeout, retry once on a flake, and
never leak a websocket on a crash. That logic used to live in BOTH files and had
to be patched in tandem — see STATE.md §5.3, where the "no retry on timeout" fix
had to be applied to `ga_core._run_battle` AND `eval.run_battle` separately. It
lives here once now.

The two callers differ in exactly three knobs, all explicit keyword args:
    pilot      "heuristic" (the GA, and eval's reference pilot) or "bc" (eval's
               neural pilot). The opponent is ALWAYS heuristic.
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
import os

# --- Suppress benign poke_env protocol noise --------------------------------
# poke_env logs certain VGC messages at CRITICAL even though they're
# harmless (open-team-sheet handshake repeats across every battle).
# Filter them at the logger so the console stays readable.
import logging as _logging

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

from poke_env import AccountConfiguration, ServerConfiguration
from poke_env.player import SimpleHeuristicsPlayer

# --- Multi-instance support -------------------------------------------------
# When SHOWDOWN_PORT is set (by run/ga_parallel.sh), route this process's
# players to that server. Unset -> default 8000, same as before.
_SHOWDOWN_PORT = os.environ.get("SHOWDOWN_PORT", "8000")
DEFAULT_SERVER = ServerConfiguration(
    f"ws://localhost:{_SHOWDOWN_PORT}/showdown/websocket",
    f"http://localhost:{_SHOWDOWN_PORT}/action.php?",
)

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
    if pilot == "bc":
        from src.bc_player import BCPlayer      # lazy: keeps torch/ROCm out of the heuristic path
        cls = BCPlayer
    else:
        cls = SimpleHeuristicsPlayer
    return cls(
        battle_format=battle_format,
        team=team_str,
        max_concurrent_battles=1,
        server_configuration=DEFAULT_SERVER,
        account_configuration=AccountConfiguration.generate(f"{prefix}{uid}", rand=False),
    )


async def run_battle_once(team_str, opp_str, uid, sem, battle_format,
                          *, pilot="heuristic", timeout=20, min_turns=0):
    """Play one battle — `pilot` on team_str vs a heuristic on opp_str — once.

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
            opp = make_player("heuristic", opp_str, uid, "O", battle_format)
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
            return 1 if bot.n_won_battles > 0 else 0
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
                     *, pilot="heuristic", timeout=20, min_turns=0, retries=1):
    """Run one battle, retrying up to `retries` times on a None result.

    Each retry offsets the uid by RETRY_STRIDE so the next attempt logs in under a
    different account — most None results are transient login/timeout flakes, not
    deterministic failures, so a fresh login usually clears them. Returns 0/1/None.
    """
    for attempt in range(retries + 1):
        result = await run_battle_once(
            team_str, opp_str, uid + attempt * RETRY_STRIDE, sem, battle_format,
            pilot=pilot, timeout=timeout, min_turns=min_turns)
        if result is not None:
            return result
    return None
