# pokeMorgrad

Finding a competitive Pokémon VGC Regulation M-C team using a genetic
search against a pilot that plays the games. Built and validated for local
tournament use, not theoretical perfection.

Status: `docs/STATE.md`.
Operations: `docs/OPERATIONS.md`.
Dev log: `docs/STATE_history.md`.
Terms: `docs/GLOSSARY.md`.
License: MIT.

---

## What this is

Two goals, stacked:

1. Find a Reg M-C team that performs well against the current tournament meta.
2. Build the machinery to do this for any regulation in roughly two weeks by
   swapping the data source and rebuilding the canonical DB.

The current output is a set of six-mon teams saved as
`output/champions/*.txt`, scored against a held-out pool of real regional
top-cut teams. The team the project is trying to beat is the human baseline
in `data/baseline_team.txt`, which took third place at a local tournament.

Runs on Windows 11 with WSL2 and an AMD 7900 XTX (ROCm).

---

## Pipeline

Two parallel tracks share the same data source. Only the GA track produces
usable teams today.

    ┌─────────────────┐    pulls ~5000 human replays from
    │  Replay scraper │    replay.pokemonshowdown.com
    └────────┬────────┘
             ▼
    ┌─────────────────┐    parses each battle into per-turn
    │  Replay tracker │    decision rows (state + action)
    └────────┬────────┘
             │
             │  training_data.jsonl (~44 MB, gitignored)
             │
             ├──────────────────────────────────┐
             │                                  │
             ▼                                  ▼

    GA track (produces teams)          BC track (produces a pilot)

    ┌─────────────────┐                ┌─────────────────┐
    │  Training pool  │                │   BC trainer    │
    │   270 teams     │                │  imitates human │
    └────────┬────────┘                │  decisions      │
             ▼                         └────────┬────────┘
    ┌─────────────────┐                         ▼
    │    GA search    │                ┌─────────────────┐
    │                 │                │   BC pilot      │
    │  evolves teams  │                │  ~32% live vs   │
    │  under realism  │                │  the held-out   │
    │  constraints    │                │  pool           │
    └────────┬────────┘                └─────────────────┘
             ▼                                  │
    ┌─────────────────┐                         │
    │ Validation      │                         │
    │ slice, 30 teams │                         │
    │ selects         │                         │
    │ champions       │                         │
    └────────┬────────┘                         │
             ▼                                  │
    ┌─────────────────┐                         │
    │  Held-out eval  │◄────────────────────────┘
    │  100 unseen     │   (BC can be swapped in as pilot
    │  regional teams │    for the eval, but wins fewer
    └─────────────────┘    games than the heuristic bot)

The GA's fitness signal is `SimpleHeuristicsPlayer`, poke_env's built-in
rule-based bot, which wins around 57 percent against the held-out pool. The
BC pilot is not currently used as the GA's evaluator because it plays worse
than the heuristic.

---

## GA island model

The GA runs three islands in parallel. Each island is an independent
population with its own constraints and its own champion. Top genomes
migrate around a ring every five generations; stagnant islands restart
their worst half.

    ┌──────────────┐          ┌──────────────┐          ┌──────────────┐
    │  Island A    │          │  Island B    │          │  Island C    │
    │              │          │              │          │              │
    │ Umbreon lock │          │ Umbreon lock │          │  no locks    │
    │ + baseline   │          │ no seed      │          │  no seed     │
    │   seed       │          │              │          │              │
    └──────┬───────┘          └──────┬───────┘          └──────┬───────┘
           │                         │                         │
           │  top 2 genomes          │                         │
           └────────►───────►────────┴────────►───────►────────┘
                    (ring migration every 5 generations)

    Per generation, per island:
      1. Evaluate fitness      800 battles vs sampled 270-team pool
      2. Update all-time best  tracking per island
      3. Evaluate val slice    best genome vs 30 held-back teams
      4. Diversity rescue      if unique species < 15, inject 3 randoms
      5. Stagnation restart    if flat for 5 gens, restart worst half
      6. Breed                 elites + crossovers + immigrants
      7. Legality gate         rebuild illegal genomes, apply constraints

    Champion per island is chosen by validation slice score, not training
    fitness. See `docs/STATE.md` section 5.14.

---

## Repository layout

    ~/project/
    ├── data/          inputs
    │   ├── regmc_db.json              canonical format data
    │   ├── baseline_team.txt          reference team, seeds GA island A
    │   ├── pool_split.json            270 train / 30 val / 100 holdout
    │   ├── meta_items.json            item frequency per species
    │   ├── species_move_priors.json   move frequency per species
    │   ├── regional_teams/            400 top-cut teams
    │   ├── showdown_replays/          raw replays (gitignored, regenerable)
    │   └── training_data.jsonl        parsed decisions (gitignored)
    │
    ├── src/           Python package
    │   ├── paths.py                   repo-relative path resolution
    │   ├── regmc_db.py                canonical data + team validator
    │   ├── showdown_validator.py      Node bridge to Showdown validator
    │   ├── showdown_validate.js       Node side of the bridge
    │   ├── state_encoder.py           battle state to tensors
    │   ├── bc_model.py                neural net + checkpoint I/O
    │   ├── bc_train.py                BC training loop
    │   ├── bc_player.py               poke_env Player wrapping BC model
    │   ├── ga_core.py                 genomes, mutation, crossover, islands
    │   ├── battle.py                  shared battle runner
    │   ├── eval.py                    unified evaluation CLI
    │   └── audit_before_launch.py     pre-flight data-integrity checks
    │
    ├── run/           entry points
    │   ├── ga_run.py                  5.5-hour island GA launcher
    │   └── ga_overnight.sh            11-hour chain: run1 + run2 + eval
    │
    ├── tools/         data pipeline and diagnostics
    │   ├── build_regmc_db.js          rebuild canonical DB from Showdown
    │   ├── scrape_replays.py          replay scraper
    │   ├── replay_tracker.py          replay parser
    │   ├── build_training_data.py     replays -> training_data.jsonl
    │   ├── generate_heuristic_dataset.py  heuristic imitation dataset
    │   ├── build_species_priors.py    species_move_priors.json
    │   ├── preflight.py               pre-launch sanity checks
    │   ├── bc_diagnostic.py           BC vs heuristic comparison
    │   └── encode_snapshot.py         bit-exact encoder verification
    │
    ├── ops/           Showdown server management scripts
    ├── output/        champions, checkpoints, trained models (gitignored)
    ├── docs/          STATE, OPERATIONS, GLOSSARY, history, replay evidence
    └── archive/       frozen history, old scripts, old pools

Never modify `~/pokemon-showdown/`. It is a separate git repository used as
the simulator backend.

---

## Setup

Requires Python 3.10 or newer, Node.js (for Showdown), and a Showdown server
on port 8000.

    git clone https://github.com/Morgrad/pokeMorgrad.git
    cd pokeMorgrad
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"

Two data files are not committed and must be regenerated before the BC or GA
pipelines can run end-to-end:

    python3 tools/scrape_replays.py             # data/showdown_replays/  (~60 MB)
    python3 tools/build_training_data.py        # data/training_data.jsonl (~44 MB)

Everything else (canonical DB, pools, priors, regional teams, showdown
replay metadata) is committed. The GA runs without re-scraping.

---

## Key commands

| Task | Command |
|---|---|
| Pre-flight data audit | `python3 -m src.audit_before_launch` |
| Pre-launch checks | `python3 tools/preflight.py` |
| Launch overnight GA | `GA_CONCURRENCY=8 python3 tools/preflight.py --launch` |
| Launch 5.5h GA only | `python3 run/ga_run.py run1 5.5` |
| Evaluate a team | `python3 -m src.eval <team.txt> --seeds 100 200 300` |
| Evaluate with BC pilot | `BC_PILOT_PATH=output/models/bc_heuristic_v1c.pt python3 -m src.eval --pilot bc <team.txt>` |
| Compare pilots side by side | `python3 -m src.eval --pilot both <team.txt>` |
| Train BC | `python3 -m src.bc_train` |
| Rebuild canonical DB | `node tools/build_regmc_db.js` |
| Scrape replays | `python3 tools/scrape_replays.py` |

Full command reference and failure modes: `docs/OPERATIONS.md`.

---

## Current status (2026-10-14)

Authoritative numbers live in `docs/STATE.md`. Orientation only:

- **Heuristic pilot baseline**: around 57 percent against the held-out pool.
  Every champion is measured against this.
- **Best held-out champion so far**: 66 to 71 percent, from the
  pre-constraint era. Those teams are structurally unrealistic. Dead items
  (Binding Band on a mon with no binding moves), missing Protect coverage,
  off-role moves. The five-part constraint stack landed 2026-10-14 fixes
  those. Expected effect: champion scores drop to the 58 to 64 percent range,
  but the number becomes meaningful.
- **BC pilot**: functional but weak. Best checkpoint
  (`bc_heuristic_v1c.pt`) wins around 32 percent against the held-out pool.
  Imitation accuracy does not predict live win rate, and BC cannot exceed
  the reference it imitates. See `docs/STATE.md` sections 5.12, 5.15, 5.16.

---

## Team realism constraints

The GA optimizes against a rule-based pilot that is blind to items, Protect
timing, and Fake Out priority. Left unconstrained, it produces teams that
score well but would lose to any human. Five constraints prevent the
artifacts:

| Constraint | What it enforces |
|---|---|
| Items from meta | Tournament-usage items only, with canonical fallback |
| Protect coverage | At least one Protect-family move on the team |
| Fake Out / redirection | At least one of Fake Out, Follow Me, Rage Powder |
| Role-committed movesets | Physical/special/support determined by base stats; EVs and nature follow |
| Priors-first move sampling | Top-8 tournament moves by usage; role filter; random fallback |

Full design in `docs/STATE.md` section 5.14.

---

## Core principles

1. **Showdown is the source of truth.** Format facts come from Showdown's
   dex, extracted by `tools/build_regmc_db.js`. Never hand-edit
   `regmc_db.json`.

2. **Every team passes the legality gate.** `showdown_validator` checks
   every genome before it enters a population. Illegal genomes are rebuilt
   up to twenty times, then dropped.

3. **Held-out eval is sacred.** Fitness uses the training slice; final
   scoring uses teams the GA has never seen. Never mix them.

4. **Team realism is enforced, not hoped for.** Items come from tournament
   usage, Protect and Fake Out coverage are required, moves are
   role-appropriate and sampled from priors.

5. **The pilot limits the search.** A team optimized for a weak pilot is
   not a strong team. The current heuristic pilot is the ceiling; improving
   it is a separate project.

6. **Measure with confidence intervals.** Single-seed results vary by five
   percentage points. Every decision needs at least five seeds; every claim
   needs non-overlapping Wilson intervals. See `docs/STATE.md` section 5.8.

---

## What this is not

- Not a team that will win a Regional. It is aimed at local tournament play,
  where execution and matchup knowledge matter more than a theoretical edge.
- Not a replacement for playing the game. It generates candidate teams to
  bring to a tournament; you pilot them.
- Not finished. The pipeline works end to end, but the search is still
  bounded by the quality of the pilot used for fitness.