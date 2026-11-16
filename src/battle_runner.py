"""
battle_runner.py — run battles with poke_env.
"""

import asyncio
import logging as _logging
import os

from poke_env import ServerConfiguration

from src.player_factory import RETRY_STRIDE, make_player


# --- Suppress benign poke_env protocol noise --------------------------------
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


# --- Multi-instance support -------------------------------------------------
_SHOWDOWN_PORT = os.environ.get("SHOWDOWN_PORT", "8000")
DEFAULT_SERVER = ServerConfiguration(
    f"ws://localhost:{_SHOWDOWN_PORT}/showdown/websocket",
    f"http://localhost:{_SHOWDOWN_PORT}/action.php?",
)


async def run_battle_once(
    team_str,
    opp_str,
    uid,
    sem,
    battle_format,
    *,
    pilot="heuristic",
    timeout=20,
    min_turns=0,
    opp_pilot="heuristic",
):
    """Play one battle — `pilot` on team_str vs `opp_pilot` on opp_str — once."""
    async with sem:
        bot = opp = None
        try:
            bot = make_player(pilot, team_str, uid, "B", battle_format)
            opp = make_player(opp_pilot, opp_str, uid, "O", battle_format)
            await asyncio.wait_for(
                bot.battle_against(opp, n_battles=1), timeout=timeout
            )
            if bot.n_finished_battles == 0:
                return None, []

            if min_turns > 0:
                try:
                    turns = getattr(list(bot.battles.values())[-1], "turn", 0)
                except Exception:
                    turns = 0
                if turns < min_turns:
                    return None, []

            try:
                turns = getattr(list(bot.battles.values())[-1], "turn", 0)
            except Exception:
                turns = 0

            if turns > 50:
                return None, []

            battle_obj = list(bot.battles.values())[-1] if bot.battles else None
            battle_log = getattr(battle_obj, "log", [])
            return (1 if bot.n_won_battles > 0 else 0), battle_log

        except KeyError as e:
            if "'round'" in str(e):
                _logging.getLogger(__name__).warning(
                    f"Battle failed with KeyError: 'round': {e}"
                )
                return None, []
            raise
        except Exception:
            return None, []
        finally:
            for p in (bot, opp):
                try:
                    if p:
                        await p.ps_client.stop_listening()
                except Exception:
                    pass


async def run_battle(
    team_str,
    opp_str,
    uid,
    sem,
    battle_format,
    *,
    pilot="heuristic",
    timeout=20,
    min_turns=0,
    retries=1,
    opp_pilot="heuristic",
    save_filter=None,
    save_callback=None,
):
    """Run one battle, retrying up to `retries` times on a None result."""
    result = None
    battle_log = []
    for attempt in range(retries + 1):
        result, battle_log = await run_battle_once(
            team_str,
            opp_str,
            uid + attempt * RETRY_STRIDE,
            sem,
            battle_format,
            pilot=pilot,
            timeout=timeout,
            min_turns=min_turns,
            opp_pilot=opp_pilot,
        )
        if result is not None:
            break

    if save_filter is not None and save_callback is not None:
        try:
            if save_filter(
                fitness=0.0,
                outcome="unknown",
                genome_species=[],
                battle_history=battle_log,
            ):
                save_callback(battle_log, [], 0.0, "unknown")
        except Exception as e:
            _logging.getLogger(__name__).warning(
                f"Error in save_filter/save_callback: {e}"
            )

    return result
