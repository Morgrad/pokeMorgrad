# tools/ reference: data scripts (scrape, pools, priors, DB, training data)

Per-script details for the data side of `tools/`: how to run, what it reads and writes, and
traps. Index and status key: `tools.md`. Ordered workflows (which script when):
`docs/runbooks/data-pipeline.md`. Network scrapers and anything that rewrites `pool_split.json`
change shared state: read the entry before running.

Last verified against code: 2026-11-18

## Scrapers

**scrape_replays.py** (LIVE) - Showdown public replays for `gen9championsvgc2026regmc`.
- Run: `python tools/scrape_replays.py [RATING_FLOOR=1600] [MAX_PAGES=200]` (positional).
- Phase 1 pages `replay.pokemonshowdown.com/search.json?...&sort=rating` into
  `data/showdown_replays_meta/index.json` (list of `{id, rating, uploadtime, players}`; saved every
  10 pages; resumes at page `len(index)//51 + 1`). Phase 2 fetches `<id>.json` for every replay with
  rating >= floor plus up to 500 unrated, writing `data/showdown_replays/<id>.json` and
  `<id>.meta.json` (`{"rating", "uploadtime"}`); existing files are skipped.
- Tunables: SLEEP 0.25 s, PAGE_SIZE 51, UNRATED_CAP 500, stops after 3 empty pages.
- Fact (2026-10-13): the format had only ~5,006 replays in total; the index holds 5,001.

**scrape_vgcpastes.py** (LIVE) - VGCPastes "Champions M-C" tab (sheet
`1axlwmzPA49rYkqXh7zHvAtSP-TKbM0ijGYBPRflLSWw`) and the pokepastes it links.
- `python tools/scrape_vgcpastes.py fetch-csv` - downloads XLSX to `data/scraped/vgcpastes/raw/m-c.xlsx`
  and writes `raw/m-c.csv`, which is JSON (list of row dicts keyed by sheet headers) despite the name.
  XLSX is required: the Pokepaste column is a HYPERLINK formula and CSV/pubhtml exports return stale
  display text; openpyxl reads `cell.hyperlink.target`.
- `report` - rank/tournament/EVs distribution of the rows.
- `filter-balanced [--all-tournaments]` - keeps EVs == Yes rows from `BALANCED_TOURNAMENTS`
  (or every EVs == Yes row, deduped by paste id) -> `raw/keep_ids.txt`.
- `fetch-teams` - `https://pokepast.es/<id>/raw` (not `.txt`), 0.5 s apart, -> `teams/<TeamID>.txt`
  plus `raw/metadata.json`; skips files > 50 bytes already on disk; strips `Tera Type:` lines.
- Needs `openpyxl` (`pip install -e ".[scrape]"`). Output is gitignored. History: 204 of 647 rows
  kept by the balanced filter (2026-10-15); `--all-tournaments` kept 558 (2026-10-16).

**scrape_metavgc.py** (LIVE) - `python tools/scrape_metavgc.py fetch` caches the list page and every
`/pokemon/<slug>` page (1.5 s apart) in `data/scraped/metavgc/raw/`; `parse` (offline) writes
`data/scraped/metavgc/species.json` with Top Moves / Natures (+ spread) / Abilities / Items as
`[{name, spread?, pct}]`. Staging only; `blend_priors.py` consumes it.

**scrape_tournament.py** (LIVE, per event) - `python tools/scrape_tournament.py <limitless_id> <shortname>`
(e.g. `445 louisville`). Parses `limitlessvgc.com/tournaments/<id>/teams` (needs `bs4`) into
`data/regional_teams/<shortname>_NN.txt`. Limitless publishes no EVs: EVs and nature are INFERRED
from move categories (physical -> `2 HP / 32 Atk / 32 Spe` Jolly, special -> Modest, none -> Calm
bulk). Does not touch `pool_split.json`. Next: `normalize_tournament.py`, then `extend_train_pool.py`.

## Pool management (`data/regional_teams/`, `data/pool_split.json`)

**normalize_tournament.py** (LIVE) - `python tools/normalize_tournament.py <prefix>`. Rewrites
`data/regional_teams/<prefix>_*.txt` in place: prefix-form names to Showdown form ("Female Indeedee"
-> "Indeedee-F", "Hisuian Arcanine" -> "Arcanine-Hisui", ...), `@ Held Item:` -> Leftovers, duplicate
items replaced from `FALLBACK_ITEMS`; unparseable or unknown-species files (or < 4 real moves) move to
`data/regional_teams/_rejected/`. Idempotent. Trap: a mon with no EVs gets `2 HP / 32 Atk / 32 Spe`
(and Jolly if no nature) even for special/support mons; suspected source of the odd
`Incineroar @ Sitrus Berry` Jolly spread seen in priors (STATE.md, 2026-10-15).

**extend_train_pool.py** (LIVE) - `python tools/extend_train_pool.py <prefix>`. Appends
`<prefix>_*.txt` names to `pool_split.json["train"]` (sorted); exits 1 if any is in the current
holdout; never edits holdout. If the current holdout differs from `pool_split_golden.json["holdout"]`
it asks `Continue anyway? [y/N]` on stdin. Since 2026-10-15 the holdout (`real_ev_*`) ALWAYS
differs from golden, so this prompt always appears (answer y deliberately; it is not
non-interactive-safe). Docstring claim "no overlap with golden holdout" is not what the code checks.

**swap_pool.py** (ONE-OFF, applied 2026-10-15) - `python tools/swap_pool.py --dry-run | --apply`.
Validates every `data/scraped/vgcpastes/teams/*.txt` with `node pokemon-showdown validate-team` in
`$SHOWDOWN_DIR`, dedups by sorted (species, item) signature vs itself, the holdout and the current
train; `--apply` moves current train files to `data/regional_teams/_archive_<date>/`, copies kept
teams as `vgc_<id>.txt`, backs up the split to `pool_split.json.bak` and sets train = ALL kept teams
(holdout unchanged). It does NOT cap the count: re-running today (558-team corpus on the original
workstation) would replace the 148-team train with every valid non-duplicate team and archive
the current pool. Known limit: `team_signature` fails on
~10% of files, which cannot be deduped (~1 team of possible holdout leakage per swap).

**build_real_ev_holdout.py** (ONE-OFF, applied 2026-10-15) - `--dry-run | --apply`. Validates the
VGCPastes corpus, rejects signature matches with `vgc_*.txt` and the old holdout, picks 100 with
seed 20261015 stratified by provenance (tournament, then video, then empty; read from
`raw/m-c.csv`, relative path: run from repo root), copies them as `real_ev_NN.txt`, backs up the
split to `pool_split.mixed_holdout.bak`, writes holdout = the 100 (train unchanged). Re-running
REPLACES THE FROZEN HOLDOUT: never do it casually.

**regenerate_split.py** (LEGACY / DANGEROUS) - `python tools/regenerate_split.py [seed=20261015]`.
Shuffles every `data/regional_teams/*.txt` (all prefixes) and takes 100 as holdout, backing up to
`pool_split.json.bak`. Today that mixes `vgc_`, `real_ev_` and tournament files and destroys the
frozen holdout. Do not run.

## Priors and DB

**build_regmc_db.js** (LIVE, rare) - `node tools/build_regmc_db.js [format] [outPath]`
(defaults `gen9championsvgc2026regmc`, `data/regmc_db.json`). Loads `Dex` from
`$SHOWDOWN_DIR/dist` (default `~/pokemon-showdown/dist`); needs a BUILT Showdown checkout, not a
running server. Writes `meta, rules, natures, types, typeChart, items, moves, abilities, species`
(moves include effect fields: boosts, secondary, status, heal, added 2026-10-20). A rebuild that
adds or removes any species/move/item/ability invalidates every BC checkpoint (sorted vocab).

**build_ev_priors.py** (LIVE) - `python tools/build_ev_priors.py`. Reads
`data/scraped/vgcpastes/teams/*.txt`; writes `data/species_build_priors.corpus.json` (keys `"Species"`
and `"Species @ Item"`, top 25 `{evs, nature, count}`; species entries need >= 2 teams, item-keyed
>= 3) and `data/species_ability_priors.corpus.json` (top 5 `{ability, count}`). Its docstring says
the GA samples from these; it does not (only `src/opp_model.py` reads the blended files).

**blend_priors.py** (LIVE) - `python tools/blend_priors.py [--dry-run]`. Blend rule
`count = corpus_count + N0 * metavgc_share` with N0 = 10 teams; keeps top 10 spreads; uses a metavgc
ability table only if >= 90% of it is DB-legal. Writes `species_build_priors.json`,
`species_ability_priors.json` (read by `src/opp_model.py`), `species_item_priors.json`,
`species_move_usage.json` (no consumer yet). Never touches `species_move_priors.json`. Pure helpers
tested by `tests/test_blend_priors.py` (nature/item canonicalisation, blend weights, Mega ability
rules). Rollback per docstring: `git checkout pre-blended-priors -- data/`.

**build_archetypes.py** (LIVE) - `python tools/build_archetypes.py [--dry-run]`. Sources
`data/regional_teams/*.txt` (train AND holdout files, by design: priors describe the meta) and
`data/scraped/vgcpastes/teams/*.txt`, deduplicated by set content; groups each species' sets by
(item, nature), Mega forms under the base species with `form`; top 8 spreads -> `data/species_archetypes.json`.

**build_species_priors.py** (LIVE for BC) - `python tools/build_species_priors.py`. Reads
`data/training_data.jsonl` (not the replays), counts moves the acting mon used, keeps top 30 per
species -> `data/species_move_priors.json` (the BC move mask; also GA move sampling, top 8).

**build_move_priors.py** (ONE-OFF, NOT applied) - `python tools/build_move_priors.py`. Tournament
counts (top 20) from the VGCPastes corpus; first copies the live file to
`species_move_priors.ladder.bak.json` if that backup is absent, then OVERWRITES
`species_move_priors.json`. The live file is still the ladder version (191 species, counts like
867): running this changes the BC mask and the GA's move sampling at once.

**build_meta_weights.py** (LIVE) - `python tools/build_meta_weights.py [--replays data/showdown_replays]`.
Writes `data/species_ladder_usage.json` (`{n_sides, floor, usage}`) via `src/meta_weights.py`, prints
the top species and the train/holdout weight spread. Re-run after new replays; the GA reads it at startup.

**build_mega_rates.py** (LIVE) - `python tools/build_mega_rates.py [--dry-run]`. Replays through
`BattleMemory`; label = Mega Evolved this turn; table keyed by `src.mega_model.cell_key`, species
factor shrunk toward 1 (SHRINK 30). `--dry-run` fits even files, scores odd (log-loss) and writes
nothing. Output `data/mega_rates.json`.

**build_opp_actions.py** (LIVE) - `python tools/build_opp_actions.py [--dry-run] [--cache rows.pkl]`.
Replays through `BattleMemory` and `src.opp_actions.foe_ctx`; fits Protect / Fake Out / Trick Room
cell tables + per-species factors -> `data/opp_actions.json` (read by `src/opp_actions.py`, used by
`VGCPilot` and `LadderOpponent`). `--dry-run` = holdout log-loss only.

## Training data (BC)

**replay_tracker.py** (LIVE library; `python tools/replay_tracker.py <replay.json>` prints a sample).
`Tracker(replay_dict).run()` replays a Showdown log and emits, at each turn start and for each side:
```
{"replay_id": "...", "rating": 1446, "turn": 3, "side": "p1",
 "state": {"my_active": [mon|None, mon|None], "my_bench": [...], "opp_active": [...],
           "opp_seen": [...], "field": {"weather", "weather_turns", "terrain", "terrain_turns",
           "trick_room", "trick_room_turns", "tailwind": {"p1", "p2"}}},
 "legal_actions": {"a": [action, ...], "b": [...]},
 "chosen": {"p1": {"a": action, "b": action}, "p2": {...}}}
action = {"type": "move", "move": "Fake Out", "target": "p2b: Garchomp"} | {"type": "switch", "to": "Garchomp"}
```
Our mons carry the full moveset from `|showteam|` (open team sheets); opponents only revealed moves;
item/ability filled when revealed. The module docstring still shows the old `slot_a`/`slot_b` keys:
the real keys are `a`/`b`, and `chosen` is keyed by side.

**build_training_data.py** (LIVE) - `python tools/build_training_data.py`. Reads
`data/showdown_replays/*.json` (skips `.meta.json`, ties, missing players/winner), runs `Tracker`,
adds `side_won` (bool) and `target_a`/`target_b` (0 our right, 1 our left, 2 none, 3 opp left,
4 opp right) and writes `data/training_data.jsonl` (overwrites). Paths from `__file__`.
Result 2026-10-12/13: 5,001 replays -> 72,048 rows, 0.3% skipped.

**generate_heuristic_dataset.py** (STALE: broken since 2026-10-16) -
`python tools/generate_heuristic_dataset.py --battles 500 --concurrency 8 --seed 42 --out data/training_data_heuristic.jsonl`.
Needs Showdown on localhost:8000 (ignores `SHOWDOWN_PORT`). Our side = a fresh legal random genome
(`build_random_genome` + `filter_legal_genomes`), foe = random train-pool team, both
`SimpleHeuristicsPlayer` subclasses recording one decision per turn; rows have `side, state, turn,
chosen {side: {a, b}}, target_a, target_b, side_won` (no `replay_id`/`rating`/`legal_actions`).
Battle timeout 30 s. Fixed 2026-11-18: `state_from_battle` called `_mon_view(m, encoder, True)` but
`_mon_view` takes 2 args, so every state was None and the file got 0 rows (pinned by
`tests/test_bc_state.py`). Not re-run since the fix (needs Showdown).
History: 5,000 battles -> 60,688 rows (2026-10-13); v2 66,036 rows; a dedup variant 58,293 rows
(no script for it in tools/).

**batch_parse.py** (LEGACY) - writes raw `Tracker` output to `data/training_data.jsonl` with no
`side_won`/`target_*`; training on it silently degrades BC. Never run it (it would overwrite the
real training file).

## Related docs

- [tools.md](tools.md) (index), [tools-ops.md](tools-ops.md)
- [Data files](data-files.md), [data pipeline runbook](../runbooks/data-pipeline.md)
- [BC subsystem](../subsystems/bc.md), [BC training runbook](../runbooks/bc-training.md)
- [Foundation (regmc_db, meta weights, archetypes)](../subsystems/foundation.md)
