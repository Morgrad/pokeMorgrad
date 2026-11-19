"""
battle_runner.py — run battles with poke_env.

The Showdown server (SHOWDOWN_PORT, read once at import), the poke_env log-noise
filter and the player classes all live in src/player_factory.py.
"""

import asyncio
import logging as _logging

from src.player_factory import RETRY_STRIDE, make_player

_log = _logging.getLogger(__name__)

TRACEBACKS_PER_TYPE = 3     # full tracebacks logged per exception type; then every 100th, one line
_ERROR_COUNTS = {}          # exception type name -> battles it ended, in this process


def battle_error_counts():
    """{exception type name: count} of battles that ended in an unexpected error (this process).

    Timeouts are not errors (a hung battle is expected and just gives no result)."""
    return dict(_ERROR_COUNTS)


def _report_battle_error(e, pilot, opp_pilot):
    """Log a battle that died on an exception. Before 2026-11-18 these were swallowed
    silently, so a pilot crashing on every decision looked like a run of timeouts."""
    name = type(e).__name__
    n = _ERROR_COUNTS[name] = _ERROR_COUNTS.get(name, 0) + 1
    if n <= TRACEBACKS_PER_TYPE:
        _log.error("battle error #%d (%s vs %s): %s: %s", n, pilot, opp_pilot, name, e, exc_info=e)
    elif n % 100 == 0:
        _log.error("battle error #%d (%s vs %s): %s: %s (traceback only for the first %d)",
                   n, pilot, opp_pilot, name, e, TRACEBACKS_PER_TYPE)


def battle_log_lines(battle):
    """The battle's Showdown protocol log as lines like '|move|p1a: Umbreon|Moonlight|...'.

    poke_env 0.17 keeps every received message, already split on '|', in the private
    `battle._replay_data` (appended in AbstractBattle.parse_message; the same data
    save_replay() writes). Before 2026-11-18 this code read `battle.log`, which poke_env
    0.17 does not have, so every captured history was empty. Returns [] if neither
    exists (e.g. a future poke_env renames the attribute).
    """
    if battle is None:
        return []
    data = getattr(battle, "_replay_data", None)
    if data:
        return ["|".join(msg) for msg in data]
    legacy = getattr(battle, "log", None)
    return list(legacy) if legacy else []


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
    """Play one battle — `pilot` on team_str vs `opp_pilot` on opp_str — once.

    Returns (result, log_lines): result 1 = win, 0 = loss, None = no usable result
    (timeout, desync, < min_turns, > 50 turns, error); log_lines = battle_log_lines()
    of a finished battle, else []. An unexpected exception still gives None (the GA keeps
    going) but is logged with its traceback (_report_battle_error, battle_error_counts);
    a KeyError other than 'round' propagates.
    """
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
            return (1 if bot.n_won_battles > 0 else 0), battle_log_lines(battle_obj)

        except KeyError as e:
            if "'round'" in str(e):
                _logging.getLogger(__name__).warning(
                    f"Battle failed with KeyError: 'round': {e}"
                )
                return None, []
            raise
        except (asyncio.TimeoutError, TimeoutError):
            return None, []          # hung past `timeout`: expected, no result, not an error
        except Exception as e:
            _report_battle_error(e, pilot, opp_pilot)
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
    log_sink=None,
):
    """Run one battle, retrying up to `retries` times on a None result. Returns the result.

    log_sink: optional callable(result, log_lines), called once after the last attempt
    with that attempt's result and protocol log (see battle_log_lines). Used by the GA's
    replay logging (src/replay_log.py); an exception inside it is logged, never raised.
    """
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

    if log_sink is not None:
        try:
            log_sink(result, battle_log)
        except Exception as e:
            _logging.getLogger(__name__).warning(f"Error in run_battle log_sink: {e}")

    return result
