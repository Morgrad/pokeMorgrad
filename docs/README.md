# Pokémon AI Project

Finding the best Reg M-C team for Pokémon VGC, using genetic search
against a machine-learning pilot trained on real Showdown replays.

**Status and roadmap:** see `STATE.md`.
**Chronological log:** see `STATE_history.md`.
**Acronyms:** see `GLOSSARY.md`.

---

## What this is

Two goals, stacked:

1. **Find a strong Reg M-C team** that beats the current tournament meta.
2. **Build the machinery to do this for any regulation** — a reusable pipeline
   that adapts to new formats in ~2 weeks.

The project runs on Windows + WSL2 with an AMD 7900 XTX (ROCm).

---

## How it works (short version)

    ┌─────────────────┐
    │  Replay scraper │  pulls ~5000 human games from
    │                 │  replay.pokemonshowdown.com
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │  BC trainer     │  behavior clones strong humans
    │                 │  → competent pilot (neural net)
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │  GA search      │  evolves 6-mon teams
    │                 │  fitness = win rate vs 400 regional top-cuts
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │  Held-out eval  │  100 unseen regional teams
    │                 │  → honest score, no overfitting
    └─────────────────┘

---

## Directory layout

    ~/project/
    ├── data/          read-only inputs
    │   ├── regmc_db.json         canonical format data (from Showdown dex)
    │   ├── baseline_team.txt     reference team for comparison
    │   ├── pool_split.json       300 train / 100 held-out teams
    │   ├── meta_items.json       empirical item distribution per species
    │   ├── regional_teams/       400 real tournament top-cut teams
    │   └── showdown_replays/     scraped human replays (training data)
    ├── src/           Python modules
    │   ├── regmc_db.py           data access + team validator
    │   ├── showdown_validator.py legality gate
    │   ├── ga_core.py            base GA engine
    │   └── ga_core_v6.py         island model + checkpoints
    ├── run/           entry points
    │   ├── ga_run.py             5-hour GA launcher
    │   └── ga_overnight.sh       10-hour chain (2 runs + eval)
    ├── tools/         setup scripts
    │   ├── build_regmc_db.js     rebuild canonical DB from Showdown
    │   ├── scrape_replays.py     replay scraper
    │   └── scrape_regionals_v2.py regional top-cut scraper
    ├── ops/           server management
    │   ├── start_server.sh
    │   ├── stop_all.sh
    │   └── watch_server.sh
    ├── output/
    │   ├── champions/            GA-produced team files
    │   └── checkpoints/v6/       per-generation snapshots
    ├── docs/          this folder
    └── archive/       old code, one-offs, old pools

**Never touch `~/pokemon-showdown/`** — it's a git repo with its own structure.
We use it as the simulator backend.

---

## Key commands

| Task | Command |
|---|---|
| Rebuild canonical DB | `node ~/project/tools/build_regmc_db.js` |
| Scrape replays | `python ~/project/tools/scrape_replays.py 1200 200` |
| Scrape regionals | `python ~/project/tools/scrape_regionals_v2.py` |
| Launch 5h GA | `python ~/project/run/ga_run.py run1 5` |
| Launch 10h chain | `bash ~/project/run/ga_overnight.sh` |
| Evaluate team vs held-out | `python ~/project/src/eval_head_to_head.py <teams...>` |

---

## Core principles (learned the hard way)

1. **Showdown is the source of truth.** Every format fact (species, items,
   moves, abilities, natures) is extracted from Showdown's dex. No
   hand-maintained JSON files. When they drift, bugs appear.

2. **Every team passes the legality gate.** `showdown_validate.js` runs
   before any genome enters a population. Illegal teams can't exist.

3. **Held-out eval, always.** Fitness uses 300 teams; final eval uses the
   other 100. Otherwise every "improvement" is overfit.

4. **The pilot limits everything.** A weak pilot makes GA results
   meaningless. Always verify the pilot plays competently before trusting
   team quality.

5. **Cheap cycles beat long cycles.** Two 5h runs with checkpoints beat one
   10h run. You can iterate.

---

## Setup history

- **Day 1 (2026-10-09)** — WSL2 + ROCm + PyTorch on 7900 XTX
- **Day 2 (2026-10-10)** — Replay parsing, first GA, NeuralPlayer pilot
- **Day 3 (2026-10-11)** — Canonical DB, Showdown gate, island GA v6,
  pilot diagnosed as broken, BC pipeline planned

See `STATE_history.md` for details.

