> **Bootstrap doc.** Read this first. It should let a fresh agent (or human)
> start contributing within minutes. Update it every time something material
> changes — do not let it drift. `STATE_history.md` is frozen history;
> `GLOSSARY.md` defines terms; the root `README.md` is the public pitch.

# Project State

**Last verified:** 2026-10-12
**Active branch:** `main`
**Repo:** https://github.com/Morgrad/pokeMorgrad

---

## 1. What this project is

Find the best Pokémon VGC **Regulation M-C** team by combining:

1. **Behavior cloning (BC)** — a neural net trained on ~5000 human Showdown
   replays, used as a pilot that plays any 6-mon team.
2. **Genetic algorithm (GA)** — evolves teams against 300 regional top-cut
   teams using the pilot for fitness.
3. **Held-out eval** — 100 regional teams never seen during GA, for honest
   scoring.

Long-term goal: a reusable pipeline that adapts to any new VGC regulation in
~2 weeks by swapping the scraper source and rebuilding `regmc_db.json`.

---

## 2. Current status (2026-10-13, 11:30)

| Component | Status | Notes |
|---|---|---|
| Data pipeline | ✅ Working | 5006 Reg M-C replays (all that exist), 72,048 rows |
| Canonical DB (`regmc_db.json`) | ✅ Working | 391 species, 166 items, 515 moves |
| Legality gate | ✅ Working | 0 invalid in 3500 fuzz tests |
| **Heuristic pilot** | ✅ Working | **61.0%** vs 100 held-out × 5 seeds — the reference |
| BC trainer (`bc_train.py`) | ✅ Working | v2 (MLP, 1.5M) and v3 (transformer, 5.5M) both train |
| BC v5 pilot (`bc_best.pt`) | ⚠️ Functional, weak | **19.4%** vs held-out — 42 pts below heuristic |
| BC v3 pilot (`bc_v3_5m.pt`) | ❌ Regression | **8.8%** — target head hurts |
| GA engine (`ga_core.py`) | ✅ Working | Island model with migration, stagnation, checkpointing |
| **GA champion (run1 island C)** | ✅ **+3.4 pts** | **64.4%** held-out vs 61.0% heuristic baseline |
| GA run2 (warm-start) | 🔄 Running | Started 09:46, ETA ~15:45, 63% at gen 4 |
| Eval (`eval.py`) | ✅ Working | `--pilot heuristic\|bc\|both`, 5-seed stable |

**The strategic picture:** the heuristic pilot is 3× better than BC. BC is
at its ceiling on this dataset. The GA produces real wins regardless, because
it uses the heuristic for fitness. BC's value is as a *foundation for future
search/RL*, not as a better pilot today.

---|---|---|
| Data pipeline (scrape → parse → DB) | ✅ Working | 5000 replays, 144 MB `training_data.jsonl` (local-only) |
| Canonical DB (`regmc_db.json`) | ✅ Working | 391 legal species, 166 items, 515 moves |
| Legality gate (Showdown validator) | ✅ Working | Zero invalid genomes in fuzz tests |
| BC trainer (`src/bc_train.py`) | ✅ Working | v5 = 57.9% move acc |
| BC retrain (72k rows) | ❌ Regression | v6a = 52.7% — worse than v5; needs more data |
| GA champion (2026-10-12) | ✅ **+7.4 pts** | Island C: 64.4% vs 57.0% baseline, 5 seeds |
| BC pilot (`src/bc_player.py`) | ✅ v2 (valid_orders) | Zero Showdown rejections; **weak play quality** (~18% win rate) |
| GA engine (`src/ga_core.py`) | ✅ Working | Overnight run launched 2026-10-12 16:20 |
| Eval (`src/eval.py`) | ✅ Working | `--pilot heuristic|bc|both`, held-out or training pool |
| Baseline team score | ✅ 57.0% | vs 100 held-out teams × 5 seeds, heuristic pilot |

---

## 3. Architecture at a glance
replays (data/showdown_replays/, gitignored, 60 MB)
│ tools/replay_tracker.py
▼
training_data.jsonl (data/, gitignored, 144 MB)
│ src/bc_train.py
▼
output/models/bc_best.pt ◄─── src/bc_player.py loads it as a poke_env Player
│
│ fitness signal
▼
┌───────────────────────────────────┐
│ src/ga_core.py │
│ run_ga() single-pop (debug) │
│ run_islands() island model (prod)│
└──────────────┬────────────────────┘
│
▼
output/champions/ga_<run>island<X>.txt
│
▼
src/eval.py (held-out, honest score)

---

## 4. Repository layout
~/project/
├── README.md public pitch
├── pyproject.toml packaging + ruff config
├── LICENSE MIT
├── .gitignore data/* whitelist
├── .gitattributes line endings + binary markers
│
├── data/ read-only inputs (mostly gitignored)
│ ├── regmc_db.json canonical format data ← TRACKED
│ ├── baseline_team.txt reference team ← TRACKED
│ ├── pool_split.json 300 train / 100 holdout ← TRACKED
│ ├── meta_items.json per-species item frequencies ← TRACKED
│ ├── species_move_priors.json per-species move usage ← TRACKED
│ ├── regional_teams/ 400 real top-cut teams ← TRACKED
│ ├── showdown_replays_meta/ replay index ← TRACKED
│ ├── showdown_replays/ raw scraped replays ← LOCAL (60 MB)
│ ├── training_data.jsonl parsed decisions ← LOCAL (144 MB)
│ └── replays/ legacy parsed replays ← LOCAL
│
├── src/ Python package (from src import x)
│ ├── init.py
│ ├── regmc_db.py DB access + team validation
│ ├── showdown_validator.py subprocess wrapper around Showdown's validator
│ ├── showdown_validate.js Node script invoked by the wrapper
│ ├── state_encoder.py battle state → tensors
│ ├── bc_model.py BCModel + checkpoint save/load + move masks
│ ├── bc_train.py training loop, saves output/models/bc_best.pt
│ ├── bc_player.py poke_env Player wrapping BCModel
│ ├── ga_core.py GA engine (single-pop + island model)
│ ├── eval.py unified evaluation CLI
│ └── audit_before_launch.py pre-flight: DB integrity, fuzz tests
│
├── run/ entry points
│ ├── ga_run.py launch island GA (run_id, hours)
│ └── ga_overnight.sh 10h chain: run1 → run2 → final eval
│
├── tools/ data pipeline (setup scripts)
│ ├── build_regmc_db.js rebuild regmc_db.json from Showdown dex
│ ├── scrape_replays.py scrape human replays from Limitless
│ ├── replay_tracker.py parse replays → training_data.jsonl
│ ├── batch_parse.py batch driver
│ └── build_species_priors.py build species_move_priors.json
│
├── ops/ server management
│ └── start_server.sh, stop_all.sh, stop_everything.sh, watch_server.sh
│
├── output/ generated (gitignored)
│ ├── models/ bc_best.pt, bc_best_move.pt, ...
│ ├── champions/ ga_<run>island<X>.txt
│ └── checkpoints/v6/ per-generation GA snapshots
│
├── docs/ this folder + STATE_history.md + GLOSSARY.md
└── archive/ frozen history — old scripts, old runs, old data

**Never edit `~/pokemon-showdown/`** — separate git repo, used as the simulator.

---

## 5. Active bugs / known issues

### 5.1 BC pilot was looping on invalid moves — fix applied, pending re-test

**Symptom:** A battle called `choose_move` 100–2000+ times per turn. Showdown
rejected our order, re-asked, we answered the same way, loop. `Struggle`
appeared in ~50% of actions.

**Root causes found and fixed (2026-10-12):**
1. `build_move_mask` initialized to all-1s → species missing from priors got a
   fully-open mask → model picked anything, incl. `Struggle`.
   *Fix:* default 0; explicit zeroing of `Struggle` and index 0.
2. Inference used species-priors mask, not live moveset.
   *Fix:* `_live_moveset_mask(battle_mon)` — O(4) lookups via precomputed map.
3. Fallback sent moves with 0 PP.
   *Fix:* fallback filters `current_pp > 0`.
4. `choose_move` nested `choose_random_move` (a `DoubleBattleOrder`) inside
   another `DoubleBattleOrder` → 3-part invalid command.
   *Fix:* if either slot fails, return a single random double-order.
5. **Doubles move orders lacked a target.** Showdown error was
   `Can't move: Yawn needs a target`. Wire message was `/choose move yawn`
   with no target.
   *Fix:* `create_order(move, move_target=slot_idx + 1)`.

**Status:** Awaiting re-test. If `calls/turn` drops to ~1 and `Struggle`
disappears, this is resolved.

### 5.2 GA island migration leaks locked species into free islands

Island A (`{0: "Umbreon"}`) migrating a top genome to island B (no
constraints) carried the Umbreon along. **Fixed 2026-10-12** via
`_strip_species`, which replaces foreign locked species on migration
entry and enforces the species clause during replacement.

### 5.3 No retry on Showdown timeouts

~5–10% of battles hit the 20s/30s timeout and return `None`.
**Fixed 2026-10-12:** both `ga_core._run_battle` and `eval.run_battle` now
retry once with a fresh account id on failure.

---



### 5.4 BC pilot is at its ceiling (measured 2026-10-13)

Empirically confirmed: **no tuning tried today moved the win rate up.**

| Change | Pilot win rate | Delta |
|---|---|---|
| v5 baseline | 19.4% | — |
| + more params (v3, 5.5M) | 8.8% | **−10.6** |
| + target head | (same run) | — |
| + ally-target penalty | (restored v5) | +1.1 vs pre-refactor |
| + outcome weighting | (no change) | 0 |

**Diagnosis:** high imitation accuracy (0.58) does not translate to strong
play. The training signal (human median decisions) is noisy. Escalating the
architecture makes this *worse*, not better.

**Implications:**
- Do not train more BC variants on this dataset expecting gains.
- Do not use BC as a GA fitness pilot (heuristic is 3× better).
- BC is useful only as a *foundation* — for search, or for RL warm-start.

### 5.5 Ally-target bug (resolved 2026-10-13)

`valid_orders` lists ally-target options (move_target = -1/-2) *first* for
every damaging move. Our scoring gave all target variants identical scores,
so `np.argmax` always picked the ally target. Pilot attacked its own ally on
every damaging move → 0.3% win rate.

Fix: `_score_options` applies a 5.0 log-unit penalty to `move_target ∈ {-1,-2}`
unless the move is on an allowlist of genuinely ally-targeting moves
(Helping Hand, Decorate, Follow Me, etc.). Restored v5 to 19.4%.

### 5.6 Never overwrite `bc_best.pt` without 5-seed confirmation

See §12. Briefly: on 2026-10-13 a `cp bc_v3_5m.pt bc_best.pt` ran without
confirming v3 was better. Reverted. All future model promotions require
5-seed pilot eval showing +3 pts over current `bc_best.pt`.

## 6. Environment

- **Host:** Windows 11 + WSL2 (Ubuntu)
- **GPU:** AMD 7900 XTX (ROCm 6.x) — torch uses `cuda` device name
- **Venv:** `~/llm-env/` (`source ~/llm-env/bin/activate`)
- **Showdown server:** `~/pokemon-showdown/` on `localhost:8000`
- **Python:** 3.12
- **Key deps:** `torch>=2.0`, `numpy`, `poke-env>=0.8`

Harmless warning to ignore: `agent.cpp:608] sysfs nodes path
'/sys/class/kfd/kfd/topology/nodes' does not exist` — ROCm probing WSL2.

---

## 7. Key commands

| Task | Command | Notes |
|---|---|---|
| Pre-flight audit | `python -m src.audit_before_launch` | ~15s, 3500 fuzz tests |
| Train BC | `python -m src.bc_train` | Needs `data/training_data.jsonl` |
| Launch 5h GA | `python run/ga_run.py run1 5` | Islands A/B/C |
| Launch 10h chain | `bash run/ga_overnight.sh` | run1 + run2 + eval |
| Eval (heuristic) | `python -m src.eval <team.txt>` | Fast |
| Eval (BC pilot) | `python -m src.eval --pilot bc <team.txt>` | Slow |
| Compare pilots | `python -m src.eval --pilot both <team.txt>` | Delta table |
| Held-out pool size | `python -c "from src.ga_core import heldout_pool; print(len(heldout_pool()))"` | Should be 100 |
| Rebuild DB | `node tools/build_regmc_db.js` | Requires Showdown running |
| Scrape replays | `python tools/scrape_replays.py` | → `data/showdown_replays/` |
| Parse replays | `python tools/replay_tracker.py` | → `data/training_data.jsonl` |

---

## 8. Open questions (things to decide)

1. **Should GA use the BC pilot for fitness, or the heuristic pilot?**
   - Heuristic: fast but optimizes for the wrong policy.
   - BC: slow (~1 battle/2s) but honest.
   - Proposed two-phase: GA with heuristic → final eval with BC.
2. **Should island migration preserve constraints?** See §5.2.
3. **Is 57.9% move accuracy enough, or retrain with more data / epochs
   before launching a long GA run?**
4. **Do we need a persistent replay server or cached team library** to speed
   up GA? Currently every battle spins up a fresh account.

---

## 9. Design decisions

- **Showdown is the source of truth.** Every format fact comes from
  `regmc_db.json`, regenerated from Showdown's dex by `tools/build_regmc_db.js`.
- **`src/` is a package, not a folder of scripts.** No `sys.path.insert`.
  Import as `from src.ga_core import run_islands`.
- **No versioned filenames in active code.** Version history lives in git.
  Archived scripts (`archive/`) keep their historical names.
- **Big data stays local.** `data/training_data.jsonl`, `data/showdown_replays/`,
  `data/replays/` are gitignored. Small canonical files are tracked so the
  pipeline runs without re-scraping.
- **Held-out eval is sacred.** Fitness uses `pool_split.json["train"]` (300).
  Final eval uses `["holdout"]` (100). Never mix.
- **GA has two tiers in one file.** `run_ga` = single-population debug.
  `run_islands` = production with migration, stagnation restart, checkpointing.

---

## 10. History / prior decisions (compressed)

- **Day 1 (2026-10-09):** WSL2 + ROCm + PyTorch on 7900 XTX.
- **Day 2 (2026-10-10):** First GA, replay parser, NeuralPlayer pilot.
- **Day 3 (2026-10-11):** Canonical DB, Showdown legality gate, island GA,
  pilot diagnosed as broken (heuristic-vs-heuristic training signal).
- **Day 4 (2026-10-12):** Full repo consolidation — package `src/`, merged GA,
  split BC into model/train/player, unified eval, root README,
  `pyproject.toml`, `filter-repo` to strip 144 MB file from history, BC pilot
  loop bug diagnosed and fixed.

Full log in `STATE_history.md`.

---

## 11. How to resume work (for an agent)

1. `cd ~/project && source ~/llm-env/bin/activate`
2. Run `python -m src.audit_before_launch`. If it passes, the data layer is
   healthy.
3. Check §5 "Active bugs" — pick the top item and reproduce it.
4. **If touching the BC pilot:** after any change, run the 3-battle diagnostic
   and verify `calls/turn` stays below 5. A higher number means the loop bug
   is back. Look for `[Invalid choice]` errors in the output.
5. **If touching the GA:** run a 1-generation smoke test with 1 island,
   pop 4, 20 battles/genome before committing.
6. Update this file (§2 status, §5 bugs) in the same commit as any material
   change.
