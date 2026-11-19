# Battle harness

How one battle is played: player construction (`make_player`), the async battle runner
(`run_battle` / `run_battle_once`), local Showdown server control, the Node team validator,
and the GA replay-logging path. Read this before touching retries, timeouts, ports, account
names, the validator, or anything the GA / eval call per battle.

Last verified against code: 2026-11-18

## 1. Purpose

Every battle in the project (GA fitness, `src/eval.py` holdouts) goes through
`src/battle.py`, a 15-line facade that re-exports the real code from
`src/battle_runner.py` and `src/player_factory.py`. Battles run on a LOCAL Pokemon
Showdown server (Node, `--no-security`) through poke_env 0.17.0 websockets. The GA also
uses `src/showdown_server.py` to probe / bounce the server and `src/showdown_validator.py`
(+ `src/showdown_validate.js`) as the authoritative legality check for genomes.

Pipeline position: `src/ga/evaluator.py::Evaluator._start_battle` and
`src/eval.py::evaluate_team` -> `src/battle.py::run_battle` -> `make_player` (x2) ->
poke_env `battle_against` -> Showdown on `localhost:$SHOWDOWN_PORT`.

## 2. Files

| path | lines | role |
|---|---|---|
| src/battle.py | 15 | facade: re-exports `run_battle`, `run_battle_once`, `make_player`, `TimeoutPlayer`, `RETRY_STRIDE`, `DEFAULT_SERVER` |
| src/battle_runner.py | 170 | `battle_log_lines`, `run_battle_once`, `run_battle` (retry loop, `log_sink` hook) |
| src/player_factory.py | 102 | `PILOTS`, pilot name -> Player class, `TimeoutPlayer`, `RETRY_STRIDE`, `DEFAULT_SERVER` (reads `SHOWDOWN_PORT`), `_DropVGCNoise` log filter; installs `poke_env_fixes` at import |
| src/poke_env_fixes.py | 50 | `install()`: patches poke_env's `AbstractBattle.parse_message` (Round after its partner's Round, `KeyError: 'round'`); `is_partner_round` |
| src/showdown_server.py | 53 | `is_up` / `restart` / `ensure` for the local server |
| src/showdown_validator.py | 79 | `check_teams`: batch Showdown TeamValidator via Node, md5 cache; `ValidatorError` |
| src/showdown_validate.js | 30 | Node side of the validator (format hard-coded) |
| src/replay_log.py | 94 | `ReplayLogger`: GA replay logging (deterministic, capped sample per generation) |
| src/replay_filters.py | 38 | `default_ga_filter`, `has_trigger`: which battles get logged |

## 3. Key concepts

- **Pilot names** (`player_factory.py::PILOTS = ("heuristic", "bc", "doubles", "ladder",
  "vgc")`, first arg of `make_player`; any other string raises `ValueError`):
  `"heuristic"` -> poke_env `SimpleHeuristicsPlayer`;
  `"vgc"` -> `VGCPilot` (our side, prefix `"B"`, gets `TimeoutPlayer`); `"doubles"` ->
  `DoublesPilot`; `"ladder"` -> `LadderOpponent`; `"bc"` -> `BCPlayer` (torch).
  `bc`, `doubles`, `ladder` are imported lazily inside `make_player`; `VGCPilot` is
  imported at module top (needed by `TimeoutPlayer`), so `import src.battle` loads the
  whole pilot stack (damage DB, turn_sim) but not torch.
- **Sides**: prefix `"B"` = our bot (team_str, `pilot`), `"O"` = opponent (opp_str,
  `opp_pilot`). Both share the same `uid`.
- **Account names**: `AccountConfiguration.generate(f"{prefix}{uid}_{uuid8}", rand=True)`.
  poke_env appends `" " + 5 random [a-z0-9]` and truncates the key so the name is <= 18
  chars; with a 10-digit uid the uuid part is cut off entirely, uniqueness then comes from
  the 5-char suffix (drawn from the global `random`, which eval/GA seed).
- **uid**: random int in `[1, UID_MAX]`, `UID_MAX = 10**9` (`src/ga/config.py`), drawn by
  the caller. Retry k uses `uid + k * RETRY_STRIDE`, `RETRY_STRIDE = 999_983` (prime).
- **Result values**: `1` win, `0` loss, `None` = no usable result (timeout, crash, too
  short, too long). Callers DROP `None` from the denominator; it is never a loss.
- **TimeoutPlayer** (`player_factory.py::TimeoutPlayer`, subclass of `VGCPilot`): at
  `battle.turn > 50` returns `DoubleBattleOrder(ForfeitBattleOrder(), ForfeitBattleOrder())`.
  Only used for `pilot="vgc"` with prefix `"B"`. Unverified: that poke_env 0.17 sends
  `/forfeit` for this order (not exercised by any test).

## 4. Public API

- `battle_runner.py::battle_log_lines(battle)` -> list of protocol lines (`"|move|p1a: Umbreon|Moonlight|..."`) from poke_env's private `battle._replay_data` (falls back to a `log` attribute, else `[]`).
- `battle_runner.py::run_battle_once(team_str, opp_str, uid, sem, battle_format, *, pilot="heuristic", timeout=20, min_turns=0, opp_pilot="heuristic")` -> `(result, log_lines)`; result 1/0/None; log_lines only for a counted battle, else `[]`.
- `battle_runner.py::run_battle(team_str, opp_str, uid, sem, battle_format, *, pilot="heuristic", timeout=20, min_turns=0, retries=1, opp_pilot="heuristic", log_sink=None)` -> `1 | 0 | None`; `log_sink(result, log_lines)` is called once after the last attempt.
- `player_factory.py::make_player(pilot, team_str, uid, prefix, battle_format)` -> poke_env Player (`max_concurrent_battles=1`, `server_configuration=DEFAULT_SERVER`); `ValueError` if `pilot not in PILOTS`.
- `player_factory.py::DEFAULT_SERVER` -> `ServerConfiguration("ws://localhost:<port>/showdown/websocket", "http://localhost:<port>/action.php?")`.
- `showdown_server.py::is_up(port)` -> True if HTTP on `localhost:port` answers within 2 s.
- `showdown_server.py::restart(port, showdown_dir, wait_s=60, tries=2)` -> True once up, False if never.
- `showdown_server.py::ensure(port, showdown_dir)` -> None; raises `RuntimeError` if down and restart fails.
- `showdown_validator.py::check_teams(team_texts)` -> `[(ok: bool, msg: str), ...]` same order; raises `showdown_validator.py::ValidatorError` (subclass of `RuntimeError`) if node fails as a whole.
- `replay_log.py::ReplayLogger(out_dir, run_id, max_per_gen=50, seed=0, keep=default_ga_filter)`: `start_generation(island, gen)`, `for_genome(island, gen, idx)` -> `on_battles` callback, `record(...)`, `end_generation(island, gen)` -> rows written.
- `replay_filters.py::default_ga_filter(fitness, outcome, genome_species, battle_history, rng=None)` -> bool; `has_trigger(battle_history)` -> bool.

## 5. Flow

`run_battle` (one call per (genome, opponent) pair):
1. Loop `attempt in range(retries + 1)` (default 2 attempts); call `run_battle_once` with
   `uid + attempt * RETRY_STRIDE`; stop at the first non-None result.
2. If `log_sink` is set: `log_sink(result, log_lines)` of the last attempt (also when the
   result is None, then with `[]`). Exceptions inside it are logged (warning), never raised.
3. Return the result only.

`run_battle_once`:
1. `async with sem` (the caller's semaphore bounds concurrent battles; player creation is
   inside it).
2. `make_player(pilot, team_str, uid, "B", fmt)` and `make_player(opp_pilot, opp_str, uid, "O", fmt)`.
3. `await asyncio.wait_for(bot.battle_against(opp, n_battles=1), timeout)`.
4. `n_finished_battles == 0` -> `(None, [])`. If `min_turns > 0` and last battle
   `turn < min_turns` -> `(None, [])`. If `turn > 50` -> `(None, [])` (always on).
5. Else `(1 if bot.n_won_battles > 0 else 0, battle_log_lines(battle))`.
6. `KeyError` containing `'round'` -> warning + `(None, [])`; other `KeyError` re-raised;
   `asyncio.TimeoutError` (hung past `timeout`) -> `(None, [])` silently; any other
   exception -> `_report_battle_error` (ERROR log `battle error #N (pilot vs opp_pilot):
   Type: msg` with traceback for the first `TRACEBACKS_PER_TYPE` = 3 per exception type,
   then one line every 100th; counted in `battle_error_counts()`) and `(None, [])`. Before
   2026-11-18 these were swallowed silently.
7. `finally`: `await p.ps_client.stop_listening()` for both players, errors ignored.

GA server control (`src/ga/engine.py`): `showdown_server.ensure(cfg.showdown_port,
cfg.showdown_dir)` at `run_islands` startup; `restart(...)` every
`showdown_restart_every` generations (10 in `run/ga_island.py`), raising `RuntimeError`
if it does not come back (the island exits non-zero and `run/ga_parallel.sh` respawns it
from the checkpoint). `restart` = `pkill -9 -f "pokemon-showdown start <port>"`, sleep 1,
`Popen(["node", "pokemon-showdown", "start", port, "--no-security"], cwd=showdown_dir)`,
probe once per second up to `wait_s`, whole sequence up to `tries` times.

Validator: `check_teams` md5-hashes each text, serves cached verdicts, sends the rest
base64-encoded one per line to ONE `node src/showdown_validate.js` process (timeout
60 s, `TIMEOUT_S`). JS prints per line `OK`, `FAIL:<first error>`, `PARSE_FAIL` or
`ERR:<msg>`. Python maps `OK` -> `(True, "")`, `FAIL:x` -> `(False, x)`, anything else ->
`(False, line)`; `ERR:` verdicts are returned but not cached. If node cannot run
(`OSError` / `TimeoutExpired`), exits non-zero, or prints a different number of verdicts
than teams, `ValidatorError` is raised (message includes the tail of node's stderr) and
nothing is cached. Called in batches
by `src/ga/legality.py` (`SV.check_teams`). Quick manual check (needs a built Showdown):
`python -m src.showdown_validator` (validates the baseline team and a broken copy).

Replay logging (only `run/ga_island.py`, when env `GA_REPLAY_LOG` is non-empty; redesigned
2026-11-18, `src/replay_log.py`):
1. `run/ga_island.py::make_replay_logger` builds `ReplayLogger(GA_REPLAY_DIR,
   run_id="<run>_<X>", max_per_gen=GA_REPLAY_MAX_PER_GEN, seed=<island seed>)` and passes
   it to `run_islands(replay_logger=...)`.
2. Per island and generation `src/ga/engine.py::_evolve_island` calls
   `start_generation(island, gen)`, gives every genome `on_battles=for_genome(island, gen, i)`,
   then `end_generation` and prints `  [X] replay log: N battles saved`.
3. `Evaluator.evaluate(..., on_battles=cb)` passes `run_battle(..., log_sink=...)`, which
   receives each battle's final result and `battle_log_lines(battle)` (the protocol lines
   from poke_env's `battle._replay_data`). After the genome is scored, `cb(genome,
   fitness, outcomes, logs)` gets the REAL fitness and per played battle (head only on an
   early abort) the outcome and log, in opponent order.
4. `ReplayLogger.record` offers every battle with a non-empty log to `default_ga_filter`
   with the real fitness, outcome (`win` / `loss` / `none`) and species. It keeps: fitness
   > 0.75; fitness > 0.65 and a loss; any line with a terrain / weather / Trick Room /
   Tailwind string (`TRIGGER_STRINGS`); else a 2% sample. The random draw uses a private
   `random.Random("<seed>:<island>:<gen>:<genome>:<opp>")`, never the global stream.
5. `end_generation` writes the first `max_per_gen` kept battles in (genome, opponent)
   order to `<GA_REPLAY_DIR>/<run>_<X>/<X>_gen<NNNN>.jsonl`, one JSON object per battle:
   `run_id, island, gen, genome_index, genome_fitness, opponent_index, outcome,
   our_species, log` (log = list of protocol lines). A re-run generation (after a resume)
   overwrites its file.
Logging never changes the GA: without it no extra argument reaches `run_battle`, and with
it the population, fitness and global random state are identical (pinned by
`tests/test_replay_log.py`; the golden master runs with logging off and is unchanged).

## 6. Invariants

- `run_battle` positional order `(team, opp, uid, sem, fmt)` + keywords: the GA evaluator,
  eval, `tests/golden/ga_harness.py` and `tests/test_ga_eval_order.py` fakes all use
  `fake(team, opp, uid, sem, fmt, **kw)`.
- `run_battle(log_sink=None)` and no `save_filter` / `save_callback` (`tests/test_battle_hook.py`).
- `make_player` accepts exactly `PILOTS`; `src/ga/config.py::PILOT_NAMES` must stay equal
  (`tests/test_ga_config.py::test_pilot_names_match_player_factory`).
- `check_teams` raises on a node failure, caches nothing then, never caches `ERR:`
  (`tests/test_showdown_validator.py`).
- `None` means "no result", never a loss; changing that shifts every fitness number.
- Battles over 50 turns never count (runner rule) - keep `TimeoutPlayer` threshold and the
  runner threshold equal or forfeits will start counting as losses.
- `restart`: success after the 40th probe with `wait_s=60` launches once; never-up with
  `wait_s=5, tries=2` launches twice and probes 10 times; `ensure` does not relaunch an
  up server and raises when dead (`tests/test_ga_robust.py`).
- Replay logging never changes GA results or the global random stream, its sample is
  deterministic and capped per (island, generation) (`tests/test_replay_log.py`).
  `default_ga_filter` thresholds 0.75 / 0.65+loss / triggers / 0.02 are pinned by
  `tests/test_replay_filters.py`.

## 7. Config / env / constants

| name | default | where read | effect |
|---|---|---|---|
| `SHOWDOWN_PORT` | `8000` | `src/paths.py::showdown_port`, called by `src/player_factory.py` at import (battles) and `GAConfig` | port in `DEFAULT_SERVER`; must be set before the process starts |
| `SHOWDOWN_PORT` | `8000` | `src/ga/config.py::GAConfig.from_env` | port the GA ensures / restarts |
| `SHOWDOWN_DIR` | `~/pokemon-showdown` | `src/paths.py::showdown_dir`, `GAConfig`, `src/showdown_validate.js` | server cwd for restarts; validator loads `$SHOWDOWN_DIR/dist/sim/*` (needs a built checkout) |
| `RETRY_STRIDE` | `999_983` | `src/player_factory.py` (copy in `tools/paired_eval.py`) | uid offset per retry |
| `UID_MAX` | `10**9` | `src/ga/config.py` (used by `src/eval.py`) | uid range |
| `GAConfig.battle_timeout` | 20 s | `src/ga/config.py` | `timeout` for GA battles (eval: `TIMEOUT = 20`; `tools/paired_eval.py`: 90) |
| `GAConfig.min_turns` | 3 | `src/ga/config.py` | GA drops battles < 3 turns (desync / forfeit); eval passes 0 |
| turn cap | 50 | literal in `run_battle_once` and `TimeoutPlayer.choose_move` | > 50 turns -> None / forfeit |
| `GA_REPLAY_LOG`, `GA_REPLAY_DIR`, `GA_REPLAY_MAX_PER_GEN` | off, `<repo>/output/replay_log`, 50 | `run/ga_island.py` | replay logging; max battles saved per island and generation |
| validator format | `gen9championsvgc2026regmc` | literal in `src/showdown_validate.js` | Reg M-C Champions doubles; Mega legal, Tera not |

## 8. Tests

Run from the repo root (venv active). All of these are in `bash tools/verify.sh` (since
2026-11-18 every `tests/test_*.py` file is):
- `tests/test_ga_robust.py` (6: restart/ensure with faked subprocess/sleep/probe, fail-fast
  without the usage file, eval reports the GA fitness via a fake `run_battle`), and the GA
  golden / eval-order tests that fake `run_battle`.
- `tests/test_showdown_validator.py` (3, faked `subprocess.run`): verdict parsing + cache,
  node failure -> `ValidatorError` + empty cache, `ERR:` not cached.
- `tests/test_ga_config.py::test_pilot_names_match_player_factory`: `PILOTS` ==
  `PILOT_NAMES`, unknown name raises.
- `python tests/test_battle_hook.py` (4) - `run_battle` signature, `battle_log_lines` on a fake
  battle, `log_sink` gets the last attempt's result and log, sink errors are swallowed.
- `python tests/test_replay_log.py` (4) - `ReplayLogger` rows / cap / order, private
  deterministic RNG, Evaluator `on_battles`, engine wiring with identical results.
- `python tests/test_battle_runner.py` (5) - imports; a pilot exception returns `(None, [])`
  and is logged with a traceback and counted; repeated errors do not flood the log;
  timeouts are not errors; `KeyError: 'round'` warns, other `KeyError`s propagate.
- `python tests/test_player_factory.py` - builds a heuristic player (Unverified: whether
  construction tries to reach a server).
- `python tests/test_replay_filters.py`.
No test runs a real battle; live behaviour (timeouts, forfeits, retries) is untested.

## 9. Gotchas and known issues

- Fixed 2026-11-18 (redesign, see the replay-logging flow above): the old hook read
  `battle.log` (absent in poke_env 0.17, so every history was empty), called the filter
  with `fitness=0.0` / `outcome="unknown"`, wrote `gen=0`, used `GA_REPLAY_MAX_PER_GEN` as
  rows per battle and drew from the global `random` stream (so logging changed GA results).
  `src/decision_logger.py` and its test were removed with it.
- `battle_log_lines` relies on poke_env's PRIVATE `battle._replay_data`. After a poke_env
  upgrade, check that saved logs are not empty (`tests/test_battle_hook.py` only uses a fake).
- The 50-turn cap (added 2026-11-14 with `PASSIVE_COST` 0.30, commit `7f72853`) fixed GA
  generations taking ~1 h because Protect/switch-heavy games ran 60+ turns. A >50-turn
  battle costs a retry (a second full battle) and is then dropped if it repeats.
- `TimeoutPlayer` (2026-11-14) affects `tools/paired_eval.py` too (it calls
  `make_player("vgc", ..., "B", ...)` directly and does NOT apply the 50-turn discard), so
  there a long game becomes a forfeit loss.
- Unknown pilot names raise `ValueError` in `make_player`. BUT `make_player` is called inside
  `run_battle_once`'s `try`: a bad name passed straight to `run_battle` yields dropped
  battles plus a logged `battle error` (`ValueError`). The GA catches it earlier
  (`GAConfig` validates `GA_PILOT` / `GA_OPP` at import) and `src/eval.py` via argparse
  choices. Fixed 2026-11-18: unknown names silently became `SimpleHeuristicsPlayer`.
- `SHOWDOWN_PORT` is parsed only by `src/paths.py::showdown_port`, called at import by
  `src/player_factory.py` (battles) and `GAConfig` (GA server control); changing
  `os.environ` after import has no effect. eval has no port
  flag; set the variable on the command line. Fixed 2026-11-18: `src/battle_runner.py` had
  its own unused `DEFAULT_SERVER` / `_SHOWDOWN_PORT` and a duplicate `_DropVGCNoise` filter;
  both removed, `player_factory.py` is the single place.
- poke_env `KeyError: 'round'`: Fixed 2026-11-18 (`src/poke_env_fixes.py`). When both mons
  of a side use Round, Showdown tags the second `|move|X|Round|Y|[from] move: Round`; poke_env
  treats the tag as "called by another move", does not reveal Round and looks it up in the
  user's known moves -> KeyError for a foe that had not shown Round. It happened inside the
  player's message handler task (not in `run_battle_once`), so the player stopped deciding
  and the battle hung until the timeout, then was replayed (seen 2026-10-16 and in the
  2026-11-18 workstation smoke run). The patch parses that one message as the ordinary Round
  it is (revealed, one PP, like the partner) and keeps `_replay_data` verbatim; installed by
  `src/player_factory.py` for every player. `tests/test_poke_env_fixes.py` also asserts the
  unpatched poke_env still raises, so a poke_env upgrade that fixes it is noticed. The
  `KeyError 'round'` branch in `run_battle_once` stays as a harmless fallback.
- The Node server leaks / slows over thousands of battles (2026-10-16: throughput halved
  after ~15 min on 7-8 h old servers); GA bounces it every 10 gens, paired runs every
  1000 matchups. A server a few hours old has taken > 30 s to answer, hence `wait_s=60`.
- Validator: if `node` crashes, times out (60 s) or the Showdown checkout is not built,
  `check_teams` raises `ValidatorError`, so `filter_legal_genomes` / a GA island crash loudly
  instead of rejecting every genome. Fixed 2026-11-18: the first team got a CACHED
  `(False, "")`, the rest `(False, "no-verdict")`, and every genome looked illegal.
  `CACHE` is unbounded and process-global.
- `run_battle` returns only the result; the old docs saying it returns `(result, log)`
  are stale (only `run_battle_once` does).

## 10. How to change safely

1. Keep `run_battle`'s positional signature and `None` semantics; grep callers:
   `src/ga/evaluator.py`, `src/eval.py`, `tests/golden/ga_harness.py`,
   `tests/test_ga_eval_order.py`, `tests/test_ga_robust.py`, `tools/paired_eval.py`.
2. A new pilot name: add it to `player_factory.py::PILOTS` AND `src/ga/config.py::PILOT_NAMES`,
   add a branch in `make_player` (lazy import if heavy), add it to `src/eval.py` argparse choices, and document it here and in `pilots.md`.
3. Changing timeouts / turn caps / `min_turns` changes which battles count: GA scores
   before and after are not comparable - record the date in `docs/STATE.md`.
4. Port handling: `player_factory.py::DEFAULT_SERVER` (battles) plus `GAConfig`
   (server control).
5. Run `bash tools/verify.sh` (must end `ALL PASS`) and the hand-run tests in section 8.
6. Never start Showdown / battles from tests; fake `subprocess`, `time.sleep`, `is_up` as
   `tests/test_ga_robust.py` does.

## Related docs

- [pilots.md](pilots.md) - the Player classes `make_player` builds
- [turn-sim.md](turn-sim.md) - the one-turn simulator inside `VGCPilot`
- [ga.md](ga.md) - evaluator, fitness, server restarts in the GA loop
- [eval.md](eval.md) - `src/eval.py`, paired comparisons
- [bc.md](bc.md) - `BCPlayer` (`pilot="bc"`)
- [../runbooks/showdown.md](../runbooks/showdown.md) - starting servers, ports, validator setup
- [../reference/config-and-env.md](../reference/config-and-env.md) - all env vars
- [../runbooks/failure-modes.md](../runbooks/failure-modes.md) - symptom -> fix
