# pokeMorgrad

Finding the best Pokémon VGC **Reg M-C** team, using a genetic search
against a behavior-cloned neural pilot trained on real Showdown replays.

**Status:** see [`docs/STATE.md`](docs/STATE.md).
**Dev log:** [`docs/STATE_history.md`](docs/STATE_history.md).
**Terms:** [`docs/GLOSSARY.md`](docs/GLOSSARY.md).
**License:** MIT (see [`LICENSE`](LICENSE)).

---

## What this is

Two goals, stacked:

1. **Find a strong Reg M-C team** that beats the current tournament meta.
2. **Build the machinery to do this for any regulation** — a reusable pipeline
   that adapts to new formats in ~2 weeks.

Runs on Windows + WSL2 with an AMD 7900 XTX (ROCm).

---

## Pipeline

    ┌─────────────────┐    pulls ~5000 human games from
    │  Replay scraper │    replay.pokemonshowdown.com
    └────────┬────────┘
             ▼
    ┌─────────────────┐    behavior clones strong humans
    │  BC trainer     │    → competent neural pilot
    └────────┬────────┘
             ▼
    ┌─────────────────┐    evolves 6-mon teams
    │  GA search      │    fitness = win rate vs 300 training teams
    └────────┬────────┘
             ▼
    ┌─────────────────┐    honest score, no overfitting
    │  Held-out eval  │    100 unseen regional teams
    └─────────────────┘

---

## Layout

    pokeMorgrad/
    ├── data/          read-only inputs (mostly gitignored, see below)
    ├── src/           Python package
    │   ├── paths.py              repo-relative path resolution (single source)
    │   ├── regmc_db.py           canonical format data + team validator
    │   ├── showdown_validator.py legality gate
    │   ├── state_encoder.py      battle state → tensors
    │   ├── bc_model.py           neural net definition + checkpoint I/O
    │   ├── bc_train.py           training loop
    │   ├── bc_player.py          poke_env Player wrapping the BC model
    │   ├── ga_core.py            GA engine (single-pop + island model)
    │   ├── eval.py               unified evaluation CLI
    │   └── audit_before_launch.py pre-flight sanity checks
    ├── run/           entry points
    │   ├── ga_run.py             5-hour island GA launcher
    │   └── ga_overnight.sh       10-hour chain (2 runs + final eval)
    ├── tools/         data pipeline (setup scripts)
    │   ├── build_regmc_db.js     rebuild canonical DB from Showdown
    │   ├── scrape_replays.py     replay scraper
    │   ├── replay_tracker.py     replay parser
    │   ├── batch_parse.py        batch driver for the parser
    │   └── build_species_priors.py
    ├── ops/           server management (start/stop/watch Showdown)
    ├── output/        champions, checkpoints, trained models (gitignored)
    ├── docs/          status, glossary, dev log
    └── archive/       frozen history — old versions, one-offs, old pools

**Never touch `~/pokemon-showdown/`** — separate git repo, used as the simulator backend.

---

## Setup

Requires Python 3.10+, Node.js (for Showdown), and a running Showdown server on `:8000`.

    git clone https://github.com/Morgrad/pokeMorgrad.git
    cd pokeMorgrad
    python -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"

### Missing data files

`data/training_data.jsonl` (144 MB) and `data/showdown_replays/` (60 MB) are
**not committed** — too large and regenerable. Rebuild with:

    python tools/scrape_replays.py            # → data/showdown_replays/
    python tools/batch_parse.py               # → data/training_data.jsonl

Canonical small files (`regmc_db.json`, `pool_split.json`, `meta_items.json`,
`species_move_priors.json`, `regional_teams/`, `showdown_replays_meta/`) *are*
committed — the pipeline runs without re-scraping.

---

## Key commands

| Task | Command |
|---|---|
| Rebuild canonical DB | `node tools/build_regmc_db.js` |
| Scrape replays | `python tools/scrape_replays.py` |
| Parse replays → training data | `python tools/batch_parse.py` |
| Pre-flight audit | `python -m src.audit_before_launch` |
| Train BC model | `python -m src.bc_train` |
| Launch 5h GA | `python run/ga_run.py run1 5` |
| Launch 10h chain | `bash run/ga_overnight.sh` |
| Evaluate vs held-out | `python -m src.eval <teams...>` |
| Evaluate with BC pilot | `python -m src.eval --pilot bc <team.txt>` |
| Compare heuristic vs BC | `python -m src.eval --pilot both` |

---

## Current status

Numbers move between runs, so the authoritative snapshot lives in
[`docs/STATE.md`](docs/STATE.md) — treat that file as the source of truth and
this section as orientation only.

- **Heuristic pilot** is the working baseline; the GA optimizes against it and
  the champion edges it out on the held-out set. See STATE.md §2 for the latest
  figures.
- **BC pilot is functional but weak** — good enough to train and evaluate, not
  yet strong enough to drive GA fitness. Retraining on the outcome-weighted
  training set is the open thread (`bc_train.py` has the oversampling hook).
- **Training data is regenerable:** `python tools/scrape_replays.py` then
  `python tools/batch_parse.py` rebuild `data/showdown_replays/` and
  `data/training_data.jsonl`.
- **Paths are now portable.** All modules resolve files through `src/paths.py`
  (repo-relative, overridable via `POKEMORGRAD_ROOT` / `SHOWDOWN_DIR`), so the
  tree runs from any checkout location — no hardcoded home directories.

---

## Core principles

1. **Showdown is the source of truth.** Format facts come from Showdown's dex,
   not hand-maintained JSON. When they drift, bugs appear.
2. **Every team passes the legality gate.** `showdown_validator` runs before
   any genome enters a population.
3. **Held-out eval, always.** Fitness uses 300 teams; final eval uses 100
   the GA never saw.
4. **The pilot limits everything.** A weak pilot makes GA results meaningless.
5. **Cheap cycles beat long cycles.** Two 5h runs with checkpoints beat one
   10h run.
