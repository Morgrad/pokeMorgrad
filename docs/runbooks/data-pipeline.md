# Runbook: data pipeline (scraping, priors, DB rebuild, pools)

Ordered procedures for refreshing the data the GA, pilots and BC read: ladder replays and the
files fitted from them, the format DB (`data/regmc_db.json`), the meta weights, the prior files,
the VGCPastes corpus, pool swaps and adding tournament teams, plus the held-out rules that must
never be broken. Script details: `docs/reference/tools-data.md`; file schemas: `docs/reference/data-files.md`.

Last verified against code: 2026-11-18

## 0. Ground rules

- Held-out discipline: `pool_split.json["holdout"]` (100 `real_ev_*.txt`, frozen 2026-10-15) is
  only for final evaluation. Never add a holdout file to train, never let the GA see it, never
  regenerate it casually. Priors/archetypes may read holdout teams (they describe the meta;
  decision 2026-10-15); fitness and final eval may not mix the pools.
- The 100 `baltimore_/frankfurt_/louisville_/brisbane_/recife_*.txt` files at the top of
  `data/regional_teams/` are the OLD holdout (`pool_split_golden.json`). Do not add them to train
  if you still compare with pre-2026-10-15 numbers, and do not reuse those shortnames with
  `scrape_tournament.py` (it would overwrite them).
- Most pool/prior tools hard-code `~/pokeMorgrad`; run from a checkout at that path.
- Network scrapers are polite by design (0.25-1.5 s delays). Do not lower the delays.
- Outputs under `data/scraped/`, `data/showdown_replays/`, `*.jsonl` are gitignored; tracked files
  (priors, DB, split, regional_teams) change git state: review `git diff --stat data/` and ask
  before committing.
- Always finish with `bash tools/verify.sh` (must end `ALL PASS`) and
  `python -c "from src.ga.pools import regional_pool, heldout_pool; print(len(regional_pool()), len(heldout_pool()))"`.

## 1. Ladder replays and everything fitted from them

```
python tools/scrape_replays.py 1600 200           # resumable; index + replay JSON
python tools/build_meta_weights.py                # data/species_ladder_usage.json (GA fitness weights)
python tools/build_mega_rates.py --dry-run        # holdout log-loss report, writes nothing
python tools/build_mega_rates.py                  # data/mega_rates.json
python tools/build_opp_actions.py --dry-run
python tools/build_opp_actions.py                 # data/opp_actions.json (Protect/Fake Out/TR)
python tools/build_training_data.py               # data/training_data.jsonl (BC only)
```
- Compare dry-run log-loss with the previous fit before writing; a worse fit is a reason to stop.
- New meta weights change GA fitness values: GA scores before and after are not comparable.
- `build_meta_weights.py` prints `<n> team sides, <k> species` (current file: 10,012 sides, 204
  species) and the train/holdout weight spread.
- Run the relevant tests after refitting: `python tests/test_mega_model.py`,
  `python tests/test_opp_actions.py`, `python tests/test_ladder_opp.py`, `python tests/test_meta_weights.py`.

## 2. Rebuild the format DB (`data/regmc_db.json`)

Needs a built Showdown checkout (`$SHOWDOWN_DIR`, default `~/pokemon-showdown`, with `dist/`);
the server does not need to run.
```
cp data/regmc_db.json /tmp/regmc_db.before.json
node tools/build_regmc_db.js                      # format gen9championsvgc2026regmc -> data/regmc_db.json
python - <<'EOF'
import json
a, b = json.load(open("/tmp/regmc_db.before.json")), json.load(open("data/regmc_db.json"))
for k in ("species", "moves", "items", "abilities"):
    print(k, len(a[k]), "->", len(b[k]), "added", sorted(set(b[k]) - set(a[k]))[:10],
          "removed", sorted(set(a[k]) - set(b[k]))[:10])
EOF
python -m src.audit_before_launch | head -40
bash tools/verify.sh
```
- Any added/removed species, move, item or ability shifts the BC vocab: all BC checkpoints become
  unloadable (this already happened on 2026-10-16 with `Lucario-Mega-Z`). Retrain BC or accept it.
- Rollback: `git checkout -- data/regmc_db.json`.
- Current DB: built 2026-10-20, 392 species, 515 moves, 166 items, 316 abilities.

## 3. VGCPastes corpus (real team pastes with EVs)

```
pip install -e ".[scrape]"                                   # openpyxl, bs4
python tools/scrape_vgcpastes.py fetch-csv                   # XLSX -> raw/m-c.csv (JSON inside)
python tools/scrape_vgcpastes.py report                      # tournaments, ranks, EVs=Yes counts
python tools/scrape_vgcpastes.py filter-balanced --all-tournaments   # or without the flag: tier 1/2 events only
python tools/scrape_vgcpastes.py fetch-teams                 # pokepast.es/<id>/raw, 0.5 s apart
ls data/scraped/vgcpastes/teams | wc -l
```
- XLSX export is mandatory (the Pokepaste column is a HYPERLINK formula; CSV gives stale text).
- `fetch-teams` resumes (skips existing files > 50 bytes) and strips `Tera Type:` lines.
- History: 2026-10-15 balanced filter 204 of 647 rows -> 150 teams after validate+dedup;
  2026-10-16 `--all-tournaments` 558 teams. The corpus lived in `/tmp` once and was wiped by a WSL
  restart (2026-10-15): it now lives in `data/scraped/` (gitignored, so back it up).

## 4. Rebuild priors and archetypes

```
python tools/build_ev_priors.py                   # corpus -> species_{build,ability}_priors.corpus.json
python tools/scrape_metavgc.py fetch              # metavgc pages (cached)
python tools/scrape_metavgc.py parse              # -> data/scraped/metavgc/species.json
python tools/blend_priors.py --dry-run            # report only
python tools/blend_priors.py                      # 4 blended files
python tests/test_blend_priors.py
python tools/build_archetypes.py --dry-run && python tools/build_archetypes.py
python tests/test_archetypes.py
```
- `blend_priors.py` never touches `species_move_priors.json` (BC mask + GA move sampling). That
  file is rebuilt only by `build_species_priors.py` (ladder, from `training_data.jsonl`). Do not run
  `build_move_priors.py` unless you intend to switch both BC and GA to tournament move priors.
- `species_item_priors.json` and `species_move_usage.json` have no consumer yet.
- `meta_items.json` (GA item draws) has no generator in the repo; edit it by hand or leave it.

## 5. Swap the training pool (VGCPastes)

Done once (2026-10-15: 445 mixed-EV teams -> 150 real-EV `vgc_*` teams). Procedure:
```
python tools/swap_pool.py --dry-run               # validate + dedup report, no changes
python tools/swap_pool.py --apply                 # archive old train, copy vgc_<id>.txt, rewrite train
python -c "from src.ga.pools import regional_pool, heldout_pool; print(len(regional_pool()), len(heldout_pool()))"
python -m src.audit_before_launch | sed -n '/4. REGIONAL/,/5. FUZZ/p'
```
Steps inside `--apply`: validate every corpus file with Showdown's `validate-team`; dedup by sorted
(species, item) against itself, the holdout and the current train; move current train files to
`data/regional_teams/_archive_<date>/`; copy kept teams as `vgc_<id>.txt`; back up
`pool_split.json` -> `pool_split.json.bak`; train = ALL kept teams, holdout unchanged.
- It does not cap the pool size: with the 558-team corpus the new train would be far larger than
  148. Decide the size first (e.g. filter the corpus or `keep_ids.txt`).
- About 10% of files cannot be signed (parser rejects them), so ~1 team of holdout leakage per swap
  is possible. Reversible: keep `.bak` and `_archive_<date>/` for at least one full GA run.
- A new train pool changes GA fitness: start a fresh run_id; old champions need re-evaluation.
- Do NOT use `build_real_ev_holdout.py` (replaces the holdout) or `regenerate_split.py`
  (reshuffles everything) for a train refresh.

## 6. Add a Limitless tournament to the training pool

```
python tools/scrape_tournament.py <limitless_id> <new_shortname>   # data/regional_teams/<new_shortname>_NN.txt
python tools/normalize_tournament.py <new_shortname>               # fixes names/items, rejects to _rejected/
python tools/extend_train_pool.py <new_shortname>                  # appends to train; refuses holdout overlap
```
- Limitless has no EVs: EVs and natures are inferred from move categories (low quality; the
  2026-10-15 real-EV evals showed inferred-EV pools mislead). Prefer VGCPastes teams.
- `extend_train_pool.py` always asks `Continue anyway? [y/N]` because the current holdout differs
  from the golden one; answering `y` is expected, but read the overlap messages first.
- Use a shortname that does not exist yet (`ls data/regional_teams | cut -d_ -f1 | sort | uniq -c`).

## 7. If something goes wrong

- Empty or short pool / RuntimeError "pool is empty": check `data/pool_split.json` names exist in
  `data/regional_teams/` (entries resolve by basename).
- Holdout accidentally changed: `git diff data/pool_split.json`; restore with
  `git checkout -- data/pool_split.json` (the split is tracked).
- `pool_split.json` missing, empty holdout, or a file in both lists: `heldout_pool()` raises
  RuntimeError (until 2026-11-18 a missing file silently returned the TRAIN pool). Restore the
  file from git before any eval.

## Related docs

- [tools-data.md](../reference/tools-data.md), [tools.md](../reference/tools.md)
- [Data files](../reference/data-files.md), [foundation](../subsystems/foundation.md)
- [BC training runbook](bc-training.md), [evaluation runbook](evaluation.md)
- [GA run runbook](ga-run.md), [Showdown runbook](showdown.md), [health check](health-check.md)
