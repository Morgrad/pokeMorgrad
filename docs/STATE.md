> **Bootstrap doc.** Read this first. It should let a fresh agent (or human)
> start contributing within minutes. Update it every time something material
> changes — do not let it drift. `STATE_history.md` is frozen history;
> `GLOSSARY.md` defines terms; the root `README.md` is the public pitch.

# Project State

**Last verified:** 2026-10-13
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
| BC heuristic-imitation (`bc_heuristic.pt`) | ✅ Working, partial | **30.4%** [26.5-34.6] vs held-out (5 seeds). Trained on 60k heuristic-vs-regional decisions; +11 pts over v5 but still ~26 pts below the heuristic it imitates. Bottleneck is the encoder (no items, no abilities visible). |
| BC v3 pilot (`bc_v3_5m.pt`) | ❌ Regression | **8.8%** — target head hurts |
| GA engine (`ga_core.py`) | ✅ Working | Island model with migration, stagnation, checkpointing |
| **GA champion (run1 island C)** | ✅ **+7.4 pts (real)** | 61.8% [59.6-64.1] vs 54.4% [52.1-56.7] on 1800 battles (18 seeds, 2026-10-13). CIs disjoint — statistically significant at 95%. |
| GA run2 (warm-start) | ✅ Ran 2026-10-13 | Champions in `output/champions/ga_run2_island_*.txt` |
| Eval (`eval.py`) | ✅ Working | `--pilot heuristic\|bc\|both`, 5-seed stable |

**Tried and rejected (2026-10-13):** bf16 autocast on the BC trainer gave
no speedup (11.8s vs 11.6s epoch-2) at 1.5M params × batch 256 — this
workload is launch-overhead-bound, not matmul-bound. Larger batches (512,
1024) also lost accuracy at matched epochs. If a bigger model (v3+) is ever
trained, re-test bf16 then. See `bc_train.py` for the fp32 path.

**The strategic picture:** the heuristic pilot is 3× better than BC. BC is
at its ceiling on this dataset. The GA produces real wins regardless, because
it uses the heuristic for fitness. BC's value is as a *foundation for future
search/RL*, not as a better pilot today.

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
pokeMorgrad/
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
│ ├── build_training_data.py THE driver: replays → training_data.jsonl
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

**Status:** ✅ **Resolved 2026-10-13.** The final fix was the Tier 3A
redesign: instead of hand-filtering moves and building orders, the pilot scores
poke_env's `battle.valid_orders` (the server's pre-legal list). Zero
`[Invalid choice]` rejections; 3-battle diagnostic shows `calls/turn ≤ 2`.
Play quality is still weak (see §5.4) — but the mechanical loop is gone.

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

### 5.7 Hardcoded host paths broke portability (resolved 2026-10-13)

**Symptom:** The repo was copied from an earlier host (`morgrad`, `~/project`)
to this one (`sberumen`, `~/pokeMorgrad`), but older modules still had absolute
paths baked in — `os.path.expanduser("~/project/data/...")` in Python and
`/home/morgrad/pokemon-showdown/dist` in the JS bridges. Anything importing
`regmc_db` or `state_encoder` failed, and `data/pool_split.json` listed teams by
absolute `/home/morgrad/...` path, so `ga_core` silently loaded an **empty**
opponent pool (no error, just 0 battles).

**Fix:**
1. New `src/paths.py` — single source of truth. Resolves `REPO_ROOT` from the
   `POKEMORGRAD_ROOT` env var (validated to contain `data/`) else the parent of
   `src/`. Exposes `data_path()`, `output_path()`, `src_path()`, `showdown_dir()`
   (the last honoring `SHOWDOWN_DIR`, default `~/pokemon-showdown`).
2. Every module (`regmc_db`, `state_encoder`, `showdown_validator`,
   `audit_before_launch`, `ga_core`, `run/ga_run.py`) now resolves files through
   it. JS bridges (`showdown_validate.js`, `build_regmc_db.js`) and shell scripts
   (`ga_overnight.sh`, `ops/*.sh`) use `SHOWDOWN_DIR` / `$BASH_SOURCE`-relative
   roots. `tools/*.py` self-bootstrap `sys.path` to import `src.paths`.
3. `ga_core._load_teams` now resolves pool entries by **basename** against
   `data/regional_teams/`, counts misses, warns, and **raises** if a non-empty
   file list loads zero teams (kills the silent-empty-pool failure mode).
4. `data/pool_split.json` regenerated to store basenames, not absolute paths.

**Status:** Resolved by inspection; needs the §13 verification checklist run on
this host to confirm end-to-end.

### 5.8 Eval noise floor — measured 2026-10-13

Fixed-seed evals are **NOT reproducible to the percentage point.** Showdown's
server-side RNG (crits, damage rolls, AI decisions) is not client-seedable, so
identical commands produce different scores run-to-run. `rand=False` in
`src/battle.py` removed the second RNG source but did **not** fix this — the
server is the dominant noise term.

Measured (baseline team, heuristic pilot, same command back-to-back):

| Battles | Observed range | True rate | 1σ (binomial) |
|---|---|---|---|
| 100 (1 seed) | 52–63% | ~57% | ±5 pts |
| 300 (3 seeds) | 54–61% | ~56.5% | ±3 pts |
| 500 (5 seeds) | — | — | ±2.2 pts |

Observed spread matches binomial sampling exactly — this is **not a bug**, it's
arithmetic. (Briefly misdiagnosed as server nondeterminism on 2026-10-13; the
numbers are consistent with the binomial band.)

**Rules for any decision-relevant eval:**
1. Use ≥5 seeds; single-seed numbers are noise.
2. Report a 95% Wilson CI (see §5.9, added with eval.py update).
3. Comparisons need ≥500 battles to distinguish <3-pt gaps.

**Corollary for past claims:**
- "Island C 64.4% vs baseline 57.0%" (+7.4 pts, 500 battles) — real, CI roughly
  [60.2, 68.4] vs [52.5, 61.5]; intervals barely miss overlapping.
- "GA champion +3.4 pts" (300–500 battles) — **inside the noise floor**, cannot
  be distinguished from baseline.
- "v3 8.8% vs v5 19.4%" (−10.6 pts, 500 battles) — real.

### 5.9 Concurrency knob — added 2026-10-13

`GA_CONCURRENCY` env var (default 8) controls simultaneous battles in both
`src/battle.py` and `src/eval.py`. Measured on an 800-battle GA smoke:
`c=3: 35s, c=8: 28s (+20%), c=12: 28s, c=16: 29s` — **ceiling is 8**; per-battle
Showdown handshake (~25ms) dominates above that and concurrency cannot help.

Set per-run: `GA_CONCURRENCY=12 python run/ga_run.py run1 6`.


### 5.10 Island config — 2026-10-13 overnight run

Three islands, 2x Umbreon goal + 1x free reference. All three warm-start
from run1's champions during run2 (if ):

  - **A:** Umbreon locked (slot 0) +  seed
        → OG team; GA improves the other 5 slots
  - **B:** Umbreon locked (slot 0), no seed
        → fresh search of the 5 free slots around Umbreon
  - **C:** fully free, no seed
        → ceiling reference (no Umbreon constraint)

Run budget: 2 × 5.5h (~11h total) + final eval. ,
early-stop active. See  ISLANDS for the canonical spec.


### 5.11 BC-on-heuristic — partial success, encoder is the ceiling

Trained a fresh v2 model on 60,688 rows generated by recording
SimpleHeuristicsPlayer decisions (5,000 heuristic-vs-regional battles,
`tools/generate_heuristic_dataset.py`). Result: **30.4% [26.5-34.6]** on the
held-out 100 × 5 seeds, vs v5's 19.4%. Real +11 pts, but still ~26 pts below
the 57% heuristic it was trained to imitate.

| Metric | v5 (human) | bc_heuristic | Target |
|---|---|---|---|
| val_move_acc | 0.579 | 0.6875 | 0.85+ |
| val_switch_acc | 0.240 | 0.333 | 0.50+ |

Move accuracy plateaued at 0.69 despite a deterministic target. Diagnosis:
**the encoder cannot see what the heuristic sees.** `encode_mon` sets
`item=None, ability=None` for every mon. The heuristic's decision function
uses items and abilities directly. No amount of extra data closes this —
it's an information gap, not a data gap.

**Next lever:** redesign the encoder to carry item and ability ids (and
possibly turns-on-field). That's `CONT_DIM` 17 → 20 and a corresponding
model bump; breaks the current checkpoint contract, so plan for a fresh
train from scratch on the heuristic dataset.

## 6. Environment

- **Host:** Windows 11 + WSL2 (Fedora Linux 42)
- **GPU:** AMD 7900 XTX (ROCm 6.x) — torch uses `cuda` device name
- **Venv:** `~/llm-env/` (`source ~/llm-env/bin/activate`)
- **Showdown server:** `~/pokemon-showdown/` on `localhost:8000`
- **Python:** 3.12
- **Key deps:** `torch>=2.0`, `numpy`, `poke-env>=0.8`

ROCm perf env vars set in `~/llm-env/bin/activate` (not tracked in repo):
  GPU_MAX_HEAP_SIZE=100, GPU_MAX_ALLOC_PERCENT=100, HSA_ENABLE_SDMA=0,
  MIOPEN_FIND_MODE=2, MIOPEN_FIND_ENFORCE=3. Append these exports after
  recreating the venv (`cat >> ~/llm-env/bin/activate <<'EOF' ... EOF`).

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
| Parse replays | `python tools/build_training_data.py` | → `data/training_data.jsonl` (`batch_parse.py` is legacy) |

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

1. `cd ~/pokeMorgrad && source ~/llm-env/bin/activate`
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

---

## 12. Model promotion rule

`output/models/bc_best.pt` is the pilot every eval and GA run loads. **Never
overwrite it without a 5-seed pilot eval showing +3 pts** over the current
`bc_best.pt` on the held-out pool. History: a blind `cp bc_v3_5m.pt bc_best.pt`
on 2026-10-13 silently regressed the pilot (v3 is 8.8% vs v5's 19.4%) and had to
be reverted (§5.6). To promote a candidate:

    python -m src.eval --pilot bc output/models/<candidate>.pt   # 5-seed
    # only if mean win rate ≥ current bc_best + 3 pts:
    cp output/models/<candidate>.pt output/models/bc_best.pt

---

## 13. Verification checklist (portability — run before committing §5.7)

The path refactor was done by inspection on a host where the toolchain could not
be executed. Run these on the WSL (Fedora) host, from the repo root, with the
venv active and Showdown up on `:8000`. Each should pass before the commit.

    cd ~/pokeMorgrad && source ~/llm-env/bin/activate

1. **No dead host paths remain in the live tree** (expect zero hits; `archive/`
   is frozen history and intentionally excluded, as is this doc's own prose):

        grep -rniE '~/project|/home/morgrad' \
          --include='*.py' --include='*.js' --include='*.sh' --include='*.json' \
          src run tools ops data README.md

2. **Lint is clean** (project ruff config: E/F/W/I, ignore E501):

        ruff check src run tools

3. **Path layer resolves and points at this checkout:**

        python -c "from src.paths import data_path, output_path, showdown_dir; \
          print(data_path('regmc_db.json')); print(output_path('champions')); \
          print(showdown_dir())"

4. **Core imports load** (the modules that had baked-in paths):

        python -c "import src.regmc_db, src.state_encoder, src.showdown_validator, \
          src.audit_before_launch, src.ga_core; print('imports OK')"

5. **Opponent pools are non-empty** (the silent-empty-pool regression):

        python -c "from src.ga_core import regional_pool, heldout_pool; \
          print('train', len(regional_pool())); print('holdout', len(heldout_pool()))"
        # expect: train 300, holdout 100

6. **Pre-flight audit passes:**

        python -m src.audit_before_launch

7. **JS bridges find Showdown** (uses `SHOWDOWN_DIR`, default `~/pokemon-showdown`):

        node tools/build_regmc_db.js --dry-run 2>/dev/null || \
          node -e "const o=require('os'),p=require('path'); \
          console.log(process.env.SHOWDOWN_DIR||p.join(o.homedir(),'pokemon-showdown'))"

8. **Legality gate still works end-to-end:**

        python -c "from src.showdown_validator import validate_team; \
          print(validate_team(open('data/baseline_team.txt').read()))"

9. **Optional — override check:** set `POKEMORGRAD_ROOT=/tmp/nope` and confirm
   `src.paths` rejects it (missing `data/`), proving the env validation works.

If all nine pass, commit. If step 5 returns 0 for either pool, the basename
resolution in `ga_core._load_teams` or the `pool_split.json` regeneration is
wrong — stop and fix before committing.

### Refactor 2026-10-13 (part 2) — optimize / de-over-engineer / comment

Status: all three tiers written; pending host verification
(`docs/refactor_verification.md`). Plan: `docs/refactor_plan_2026-10-13.md`. Tiers: 1
(comments + named constants + dead-code removal) → 2 (output-equivalent
optimizations: item-cache, encoder precompute, batched legality, semaphore
hoist) → 3 (shared `src/battle.py`, replay-driver consolidation,
inverted-doc fix). Checkpoint contract frozen throughout — no state_dict key,
arch value, or dimension constant renamed/resized.

Tier 1 landed: contract banners (`bc_model`, `bc_player._get_shared_model`,
`state_encoder`), the two 17-dim `cont[]`/`encode_field` layout maps, named
constants with per-threshold rationale across `ga_core`/`eval`/`regmc_db`/
`state_encoder`/tool scripts, and provably-dead removals (`eval`'s `DB` import,
`showdown_validate.js`'s `Dex`, `replay_tracker`'s `brought_count`/
`next_bench_index`/`["slot"]`, `bc_model.load_checkpoint`).

Tier 2 landed (each output-equivalent, one commit apiece): `_legal_items_for`
`@lru_cache` returning tuples (2A); encoder precompute — `STATUSES`/`WEATHERS`/
`TERRAINS` `.index()` scans → module-level `{name: idx}` dicts + hoisted
`_ACTIVE_MASK`, proven bit-identical by `tools/encode_snapshot.py` (2B);
`replay_tracker` indexed `|turn|` backfill (2D); `filter_legal_genomes` batched
per-attempt legality (2E); per-call semaphore hoist in `eval.evaluate_team` (2F);
and the dropped `mutate_species(constraints)` param.

Tier 3 landed: the shared battle layer now lives in `src/battle.py`
(`make_player`/`run_battle_once`/`run_battle`, `pilot`/`timeout`/`min_turns`
kwargs); `eval` and `ga_core` call it instead of each carrying a copy — this
removes the §5.3 twin-maintenance hazard. Replay drivers consolidated:
`build_training_data.py` is THE driver, `tools/batch_parse.py` archived with a
LEGACY header, and the inverted README/GLOSSARY/STATE doc lines corrected (they
had pointed at `batch_parse.py`). Verification gates: `docs/refactor_verification.md`.

Checkpoint contract held throughout — no state_dict key, arch value, or dimension
constant renamed/resized.
