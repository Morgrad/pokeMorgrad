# pokeMorgrad

Finding a competitive Pokemon VGC Regulation M-C team with a genetic search whose fitness
comes from real games on a local Pokemon Showdown server. Built for local tournament use,
not theoretical perfection. License: MIT.

- Want to run the GA? Follow `docs/runbooks/quickstart.md`: setup from zero, a test run,
  one or three servers, results. No Python knowledge needed.
- Agents and contributors start at `AGENTS.md`, then `docs/README.md` (which doc to read for
  which task).
- Current status, open issues, next steps: `docs/STATE.md`.
- How it fits together: `docs/reference/architecture.md`.

## What this is
Two goals, stacked:
1. Find a Reg M-C team (`gen9championsvgc2026regmc`: doubles, Mega Evolution legal,
   Terastallization not legal) that performs well against the current tournament meta,
   built around Umbreon.
2. Keep the machinery reusable for the next regulation: swap the team/replay sources and
   rebuild the canonical format DB from Showdown.

Output: six-mon teams in `output/champions/*.txt`, scored against a held-out pool of 100 real
tournament teams the search never saw. The reference to beat is the human team in
`data/baseline_team.txt` (third place at a local tournament).

## Pipeline
```
 real tournament teams (data/regional_teams/)      human replays (Showdown replay API)
              |                                              |
   data/pool_split.json                          tools/replay_tracker.py
   148 train / 100 holdout                                   |
              |                                    data/training_data.jsonl
   train: 118 fitness + 30 validation                        |
              v                                              v
   GA islands A / B / C  (src/ga/)              behavior-cloning pilot (src/bc_*.py)
   each team plays real battles:                parked: weaker than the rule-based
   VGCPilot (ours) vs LadderOpponent,           pilot; kept as a base for future
   meta-weighted win rate                       search / RL
              |
   champions: output/champions/ga_<run>_island_<X>.txt
              |
   held-out eval: src/eval.py on the 100 holdout teams (never used for fitness)
```

## GA island model
| Island | Constraint | Seed |
|---|---|---|
| A | Umbreon locked in slot 0 | `data/baseline_team.txt` |
| B | Umbreon locked in slot 0 (5 slots free) | none |
| C | none | none |

Per generation, per island: sample opponents from the training pool, play every team
(50-battle head; teams under 15% stop early), track the all-time and validation bests, breed
(top third kept, children by crossover + mutation, 20% fresh immigrants), then restart half
the children after 5 flat generations or inject 3 fresh teams when species diversity is low.
Every team passes Showdown's own validator. The parallel launcher runs the 3 islands as 3
processes on 3 Showdown servers (ports 8000-8002) with no migration; the serial launcher
migrates the top 2 around a ring every 5 generations. Details: `docs/subsystems/ga.md`.

## Team realism constraints
A pilot-based fitness happily rewards teams no human would bring, so genomes are constrained:
tournament-usage items with a canonical fallback, at least one Protect-family move, at least
one Fake Out / Follow Me / Rage Powder, role-committed movesets (physical / special / support
from base stats; EVs and nature follow the role), move sampling from usage priors.
Details: `docs/subsystems/ga-genome-operators.md`.

## Setup
Python 3.10+ (3.12 / 3.13 used), Node.js, and a built Pokemon Showdown checkout
(`~/pokemon-showdown`, or set `SHOWDOWN_DIR`).
```
git clone https://github.com/Morgrad/pokeMorgrad.git && cd pokeMorgrad
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
bash tools/verify.sh          # must end with ALL PASS
```
Canonical DB, pools, priors and regional teams are committed, so the GA runs without
scraping. Replays and the BC training data are not committed; see
`docs/runbooks/data-pipeline.md`. Host details (WSL2, ROCm on an AMD 7900 XTX):
`docs/runbooks/environment.md`.

## Key commands
| Task | Command |
|---|---|
| Full gate (lint, tests, audit) | `bash tools/verify.sh` |
| Pre-launch checks | `python tools/preflight.py` |
| Parallel GA, 3 islands | `bash run/ga_parallel.sh <hours> <run_id>` |
| Serial GA with migration | `python -m run.ga_run <run_id> <hours>` |
| Evaluate a team on the holdout | `python -m src.eval <team.txt> --pilot vgc --opp ladder` |
| Paired pilot comparison | `bash tools/paired_run.sh <heuristic or ladder> <matchups>` |
| Rebuild the format DB | `node tools/build_regmc_db.js` |
More: `docs/runbooks/` (one file per procedure).

## Core principles
1. Showdown is the source of truth: format data comes from Showdown's dex
   (`tools/build_regmc_db.js`); never hand-edit `data/regmc_db.json`.
2. Every team passes the legality gate (Showdown's validator) before it is evaluated.
3. Held-out eval is sacred: fitness never sees the 100 holdout teams.
4. Team realism is enforced, not hoped for.
5. The pilot limits the search: a team optimized for a weak pilot is not a strong team.
6. Measure with confidence intervals and paired comparisons; single runs vary by ~5 points.

## What this is not
- Not a team that will win a Regional; it is aimed at local tournaments.
- Not a replacement for playing: it proposes candidate teams; you pilot them.
- Not finished: the search is bounded by the pilot used for fitness (see `docs/STATE.md`).
