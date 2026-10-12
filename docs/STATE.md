> ⚠️ **Last verified:** commit `2739569`. Some details may be stale — see the root [README](../README.md) and `git log` for current truth.

# Pokémon AI Project — State

Last updated: 2026-10-11 23:35
Full chronological history: see STATE_history.md
Acronyms and terms: see GLOSSARY.md

---

## Recent changes (2026-10-12)

- `src/` is now a proper Python package — no `sys.path` hacks, no versioned filenames.
- GA merged into one file: `src/ga_core.py` (single-pop + island model).
- BC split into `src/bc_model.py` / `src/bc_train.py` / `src/bc_player.py`.
- Eval unified: `python -m src.eval --pilot heuristic|bc|both`.
- `data/` whitelisted in `.gitignore` — small canonical files tracked, big ones local-only.
- Root `README.md` added; `docs/README.md` is now a pointer.
- 43 MB of raw replays moved out of git (`archive/replays/` → `data/replays/`).
- `pyproject.toml`, `LICENSE` (MIT), `.gitattributes` added.

## Mission
Find a Reg M-C team that beats the elite tournament meta. Build reusable
pipeline that adapts to new regulations in ~2 weeks.

**STATUS (2026-10-12):** Repo consolidated into a clean `src/` package with a
unified GA + BC + eval pipeline. BC v5 checkpoint (`bc_best.pt`) reaches **57.9%**
move accuracy on validation. **Active bug:** the BC pilot's move mask is degenerate
for species missing from `species_move_priors.json` → it can predict `Struggle` or
off-list moves → Showdown rejects and re-asks → infinite loop. Fix in progress.

---

## Headline result (2026-10-11, PILOT-LIMITED)

Held-out 100 regional teams × 3 seeds, N=300 each:

| Champion              | Held-out |
|-----------------------|----------|
| baseline              | 58.3%    |
| ga_run1_island_A      | 74.0%    |
| ga_run1_island_B      | 76.7%    |
| ga_run1_island_C      | 77.7%    |
| **ga_run2_island_A**  | **78.7%** (best) |
| ga_run2_island_B      | 74.7%    |
| ga_run2_island_C      | 74.0%    |

**These numbers are pilot-limited.** They measure "best team for
SimpleHeuristicsPlayer" (broken pilot), not "best team for VGC." See below.

---

## CRITICAL FINDING — pilot is broken

Move-frequency probe (20 battles, 276 decisions) on the champion:

| Action         | % of clicks |
|----------------|-------------|
| Protect        | 0%          |
| Fake Out       | 0%          |
| Parting Shot   | 0%          |
| U-turn / VSwitch | 0%        |
| Follow Me / Tailwind / TR | 0% |
| Dig            | 19.6%       |
| Pass (Dig charge) | 19.6%    |
| Switch         | 12.7%       |
| Other (damage) | ~48%        |

SimpleHeuristicsPlayer is **Tier 0** — greedy, doubles-unaware, clicks the
highest-damage move. It cannot execute Protect, Fake Out, pivots, or any
positioning play.

**Implication:** all GA results so far are "best team for a broken pilot."
Not comparable to real VGC. This is the single biggest limitation of the
project right now.

---

## Also discovered 2026-10-11

- **Umbreon constraint bug** in `ga_core.py` — migration/crossover
  didn't enforce locked slots. Fixed at 22:22. Needs rerun to test the
  real Umbreon experiment.
- **All 6 champions converged to the same composition**:
  Noivern / Gliscor / Incineroar / Gholdengo / Rillaboom / Garchomp.
  Islands B and C (both free) ended identical — migration may be
  over-copying.
- **Replay data verified public.** `gen9championsvgc2026regmc` format
  exists on replay.pokemonshowdown.com. ~5000 replays scraped at 1200+.

---

## Next: Path 3 — BC + RL pilot rebuild

**Goal:** train a competent pilot from ~5000 human replays in our exact
format. Then rerun GA with that pilot.

### Pipeline (to build)
1. **Parse replays** → `(state, action)` pairs (~100k examples)
   - `~/project/tools/parse_replays.py` — to write
2. **Train BC policy** — imitate human play
   - `~/project/src/bc_train.py` — to write
3. **Evaluate BC** vs SimpleHeuristics, vs baseline team
4. **RL fine-tune** (weeks later)
5. **Integrate into GA**, rerun

### Data status
- ~5000 replays in `~/project/data/showdown_replays/`
- Ratings: 750 at 1600+, 11 at 1800+, 0 at 2000+
- Format is young — top of ladder is only 1879
- **Expect quality to improve over time** as the format matures

---

## Previous milestones

- **2026-10-09** — Initial bot + GA v1 (NeuralPlayer pilot)
- **2026-10-10** — Discovered NeuralPlayer exploit (its champions only
  beat NeuralPlayer). Pivoted to SimpleHeuristics pilot. Built canonical
  `regmc_db.json` from Showdown dex + Showdown legality gate. Scraped 400
  regional top-cut teams.
- **2026-10-11** — Island GA v6, refactored directory, ran 10h chain,
  diagnosed pilot as broken, started Path 3.

---

## Key findings to remember

1. **SimpleHeuristics > NeuralPlayer by 22 points** as pilot. And
   SimpleHeuristics itself is broken.
2. **Random species swaps produce 2–5% win rate teams.** Catastrophic.
   Always use role/species constraints.
3. **GA diversity collapses in ~12 generations** without intervention.
4. **Umbreon is off-meta** (not in top 20 species) but works in a support
   shell: Snarl + Yawn + Whirlwind partners.
5. **Top tournament meta:** Rillaboom 53%, Sneasler 40%, Incineroar 34%,
   Gholdengo 31%, Kingambit 31%.
6. **Items matter** (Focus Sash, White Herb, mega stones). Prior belief
   they were noise was wrong.
7. **Showdown format dex is the source of truth.** Never hand-maintain
   format data — extract from Showdown.

---

## Directory layout

    ~/project/
    ├── data/          read-only inputs
    │   ├── regmc_db.json         canonical format data (from Showdown dex)
    │   ├── baseline_team.txt     reference team for comparison
    │   ├── pool_split.json       300 train / 100 held-out
    │   ├── meta_items.json       empirical item distribution per species
    │   ├── regional_teams/       400 real tournament top-cut teams
    │   └── showdown_replays/     ~5000 scraped human replays
    ├── src/           Python modules
    │   ├── regmc_db.py           data access + team validator
    │   ├── showdown_validator.py legality gate
    │   ├── ga_core.py            base GA engine
    │   └── ga_core.py         island model + checkpoints
    ├── run/           entry points
    │   ├── ga_run.py             5-hour GA launcher
    │   └── ga_overnight.sh       10-hour chain
    ├── tools/         setup scripts
    │   ├── build_regmc_db.js     rebuild DB from Showdown
    │   ├── scrape_replays.py     replay scraper
    │   └── scrape_replays.py regional top-cut scraper
    ├── ops/           server management
    │   └── start_server.sh / stop_all.sh / watch_server.sh
    ├── output/
    │   ├── champions/            GA team files
    │   └── checkpoints/v6/       per-generation snapshots
    ├── docs/          this folder
    └── archive/       old code, one-offs, old pools

---

## Key paths

| Purpose             | Path |
|---------------------|------|
| DB                  | `~/project/data/regmc_db.json` |
| Baseline team       | `~/project/data/baseline_team.txt` |
| Training pool (300) | `~/project/data/regional_teams/` via `pool_split.json` |
| Held-out pool (100) | same dir, same split |
| Item prior          | `~/project/data/meta_items.json` |
| Replays             | `~/project/data/showdown_replays/` |
| GA engine           | `~/project/src/ga_core.py` + `ga_core.py` |
| Showdown gate       | `~/project/src/showdown_validator.py` |
| Chain script        | `~/project/run/ga_overnight.sh` |
| Old 681-team pool   | `~/project/archive/pools/real_teams_681_limitless/` |

---

## Architecture decisions (locked in)

- **Showdown format dex is the source of truth.** No hand-maintained JSON.
- **Every generated team passes the Showdown legality gate** before
  entering a population. Illegal teams can't exist.
- **Island model** — 3 populations + ring migration every 5 gens.
- **Stagnation restart** after 5 gens no improvement.
- **Diversity monitor** — inject 3 randoms if unique species < 15.
- **Held-out eval** — fitness on 300 training teams, final eval on the
  other 100. Never evaluate on training data.

---

## Known weaknesses

- **Pilot is broken** (see CRITICAL FINDING above). Path 3 is the fix.
- **Items under-optimized** at N=800 (SE ±1.6%, item effects 1–4%).
  Mitigated by `meta_items.json` prior.
- **Training pool small** (300). Could scrape more regionals.
- **Migration may over-copy** — islands B and C ended identical.

---

## If something crashes

    # Resume run1 from latest checkpoint
    cd ~/project && source ~/llm-env/bin/activate
    nohup python ~/project/run/ga_run.py run1 5 > /tmp/ga_run1_resume.log 2>&1 &
    disown
    # Auto-resumes from output/checkpoints/v6/run1/gen_NNNN.json

---

## Long-term: mature alongside the format

The pipeline is reusable. Every cycle improves as the format matures.

| Cycle | When | Data | Pilot | Deliverable |
|-------|------|------|-------|-------------|
| **1 (now)** | Oct 2026 | ~5000 replays, top 1879 | BC (mixed quality) | Working pipeline |
| **2** | Jan 2027 | 10× replays, top 2100+ | BC retrained | Team-quality improvement |
| **3** | Apr 2027 | Format peak, top 2200+ | BC + RL fine-tune | Real meta-breaker |
| **4+** | Ongoing | New regulation M-D etc. | Adapt | Fresh cycle in ~2 weeks |

**Infra that survives all cycles:**
- `tools/scrape_replays.py` — data collection
- `tools/parse_replays.py` (to write) — replay → training pairs
- `src/bc_train.py` (to write) — BC model training
- `src/ga_core.py` — search engine
- `src/showdown_validator.py` — legality gate
- `data/regmc_db.json` — canonical format data

---

## Rollback anchors

- **Pre-refactor snapshot:** `~/cleanup_2026-10-11/refactor_20261011_005140/project_before`
- **Today's 10h run:** `~/project/output/archive/2026-10-11-10h-run/`


---

## Update 2026-10-12 00:05 — BC v1 trained

### Result
- 10 epochs, ~90s total
- train_acc 29.8%, val_acc 21.0% (best at epoch 7)
- val_loss increased after epoch 7 → overfitting
- Model: 18.3M params, one-hot inputs (16,925 dims)

### Interpretation
- ~100× better than random (0.2%)
- Not yet at the 35-45% target for a competent pilot
- Clear diagnosis: too much capacity for 97k training examples

### Saved
- `~/project/output/models/bc_v1_best.pt`
- `~/project/output/models/bc_v1_final.pt`

### v2 plan (tomorrow)
1. Species/move embeddings (not one-hot)
2. Smaller model (~3M params)
3. Early stopping on val_loss
4. Target: val_acc 35%+
