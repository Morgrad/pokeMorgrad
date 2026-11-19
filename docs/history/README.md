# History index

Chronological project log, moved verbatim out of the old `docs/STATE.md` (dated entries,
old section 5 "Active bugs / known issues", "Prior regeneration" onward, the 2026-11-12
Slice 3 entry, the HANDOFF block) and all of the old `docs/STATE_history.md`. Read a period
file when you need the reason, measurement or date behind a current fact.

Last verified against code: 2026-11-18 (this index only; period files are verbatim history)

Old entries record what was believed at the time. Code paths in them are historical:
`src/ga_core.py` was split into the `src/ga/` package on 2026-11-18 and removed the same
day; `src/ga/genome.py` was then split into `genome`, `pools`, `legality`, `operators`
(old name -> new module: `../reference/ga-old-names.md`). For the current state read `docs/STATE.md`.

## Period files

| File | Lines | Summary |
|---|---|---|
| [2026-10-09_to_10-10.md](2026-10-09_to_10-10.md) | 236 | Compressed day 1-4 summary; vgc-bench self-play, team evaluator, NeuralPlayer vs SimpleHeuristics, rules sweep, Limitless real teams, GA v3 launch. |
| [2026-10-10_to_10-11.md](2026-10-10_to_10-11.md) | 197 | GA v3 fixes and scaled run (random species swaps 2-5%), 63.3% baseline, canonical `regmc_db.json`, counter-meta GA, 70.2% Umbreon champion. |
| [2026-10-11_to_10-12.md](2026-10-11_to_10-12.md) | 273 | 2026-10-11 state snapshot (island GA v6, overnight chain), Day 4 repo consolidation, old items 5.1-5.3 (BC loop bug, migration leak, retries). |
| [2026-10-13-a.md](2026-10-13-a.md) | 274 | Day 5 first real GA win (+7.4 pts held-out), BC v3 verdict, `valid_orders` pilot; old items 5.4-5.10 (BC ceiling, noise floor, concurrency, islands). |
| [2026-10-13-b.md](2026-10-13-b.md) | 143 | Status table 2026-10-13 11:30, portability checklist (`src/paths.py`), three-tier refactor and shared `src/battle.py`. |
| [2026-10-14-a.md](2026-10-14-a.md) | 253 | Day 6 parallel islands, Louisville pool, val overfit; old items 5.11-5.14 (BC-on-heuristic, GA overfits the pilot, team-realism constraints). |
| [2026-10-14-b.md](2026-10-14-b.md) | 141 | Old items 5.15-5.18: items hurt the BC encoder, BC capped below heuristic, move priors, parallel GA + val-overfit numbers. |
| [2026-10-15-a.md](2026-10-15-a.md) | 260 | Day 7 VGCPastes pool + train-selection; milestones (damage.py, SmartPlayer, real-EV holdout, structural fitness design, priors); old item 5.19. |
| [2026-10-15-b.md](2026-10-15-b.md) | 127 | Prior regeneration, corpus wipe, DB gaps, validate_team fixes; DoublesPilot joint attack allocation and the damage immunity bug. |
| [2026-10-16-a.md](2026-10-16-a.md) | 231 | KO_BONUS sweep; new VGC pilot plan and user decisions; poke_env facts; blended priors; set archetypes and Mega-Z correctness; cleanup. |
| [2026-10-16-b_to_10-20.md](2026-10-16-b_to_10-20.md) | 131 | battle_memory, VGCPilot v0, Mega model, turn_sim v1-v3, paired runs (+4.7/+4.5), ladder opponent, meta-weighted fitness, HANDOFF, 2026-10-20 support layer, lookahead, heals. |
| [2026-11-12_to_11-18.md](2026-11-12_to_11-18.md) | 184 | Slice 3 entry (claims not in code, see below), `_fitness` refactor, q5 results, replay logging, GA package split + fitness-ordering fix. |
| [milestones.md](milestones.md) | - | New entries from `tools/log_milestone.py` (from 2026-11-18 on). The 2026-11-18 bug fixes and docs rewrite are summarized in `../STATE.md`. |

## How the files were made

- Split mechanically by a script; nothing was retyped. Transformations: emoji removed, unicode
  punctuation/arrows/box drawing transliterated to ASCII (`->`, `x`, `-`, `section`), H1
  headings demoted to H2, and a `## <date> - ...` heading added where an entry had no date.
- Check run on 2026-11-18: the multiset of non-empty source lines (normalized the same way)
  equals the multiset of body lines in the period files: 1740 lines, 0 missing, 0 extra.
- Not moved (not dated log content): old STATE.md header, sections 1, 3, 4, 6, 7, 8, 9, 11,
  12 (current-state reference; sections 8 and 9 now live in `docs/design/decisions.md`) and the
  6-line preamble of STATE_history.md ("Old entries are stale by design").
- Within a file, entries keep source order. Source quirks kept as written: the
  "2026-10-11 22:30" entry precedes "2026-10-11 00:30" and "2026-10-11 01:00" (it was most
  likely 2026-10-10 22:30); the 2026-10-10 18:45 rules-sweep block appears twice; old
  STATE.md has two items numbered 5.21 and no 5.20 (5.20 SmartPlayer was referenced but never
  present).

## Known-wrong entries (checked against code 2026-11-18)

- **Slice 3 (2026-11-12, "COMPLETED")**: false. `src/support_value.py::EFFECTS` is
  `("foulplay", "snarl", "charm", "helpinghand", "taunt", "heal")`; there is no Toxic,
  Will-O-Wisp, Wish, Reflect, Light Screen or Tailwind effect, `tools/build_regmc_db.js` has no
  `supportEffect` field, and `tests/test_support.py` has 28 tests, not 61+. The real changes of
  that day (commits e90bbf9, 8b28efb, eba6043): heal effect, a Taunt candidate fix, and
  `DEFAULT_SUPPORT = "all"` (support layer on by default). Its "+2.2 pts" is the 2026-10-20
  plain-pool control (p=0.124), not a new measurement.
- **Replay logging (2026-11-15)**: the follow-up commit says "battle_history capture", but
  `src/battle_runner.py::run_battle_once` reads `getattr(battle, "log", [])` and poke_env 0.17.0
  battles have no `log` attribute, so the history is still empty. `run_battle` also passes
  `fitness=0.0, outcome="unknown"` to the filter, so the fitness/loss triggers never fire.
- **Umbreon lock (2026-11-15 "removed")**: re-added 2026-11-17 (commit 6762c32).
  `run/ga_island.py::SPECS` today: A = Umbreon slot 0 + baseline seed, B = Umbreon slot 0, no
  seed, C = free.

## Undocumented period 2026-10-21 to 2026-11-18 (from `git log`, not from STATE)

No dated STATE entries exist between 2026-10-20 and 2026-11-12. Commits that changed
behavior in 2026-11-12..11-18 and are not described in any period file:

- 2026-11-14 7f72853: `PASSIVE_COST` 0.15 -> 0.30 (`src/turn_sim_types.py`, env
  `DOUBLES_PASSIVE_COST`); battles over 50 turns are dropped (GA runs had 60+ turn battles,
  about 1 h per generation).
- 2026-11-14 81d4044, 129e915, a599910: `TimeoutPlayer` (our side, pilot `vgc`) forfeits after
  turn 50; parallel islands play 50 opponents per genome.
- 2026-11-14 208e0ac: poke_env `KeyError: 'round'` caught in the battle runner (battle -> None).
- 2026-11-14 2efdfb5, fc3d2c2, 6b59d9e: unique Showdown account names (uuid suffix).
- 2026-11-14 3406ce2: two invalid teams removed from the training pool (train is 148 now).
- 2026-11-15 d314001, 235a14f, f253522: async task cancellation in evaluate, parallel Showdown
  startup with readiness poll, 5-min watchdog restored.
- 2026-11-15/16 b8f4092, cf6bbb8, a48f08f, 686b13a, b0ba30b, 2399d5d, c51e5e1: module splits
  (`player_factory`, `battle_runner`, `pilot_support`, `ga_genome`, `turn_sim_types` /
  `turn_sim_lookahead`, `pilot_*` mixins, `battle_memory_types` / `battle_memory_parser`).
- 2026-11-18 16d0bb3: `src/ga/` package split (see the last period file).
- 2026-11-18 0572ca9: GA fixes, replay logging rebuild, local-LLM refactors (genome split,
  facade removed, turn_sim scenario class), clause repair, docs rewrite; summarized in
  `../STATE.md` ("Changes on 2026-11-18").

## Related docs

- [Current state](../STATE.md)
- [Design decisions and open questions](../design/decisions.md)
- [Architecture](../reference/architecture.md)
- [Refactor roadmap](../design/refactor-roadmap.md)
