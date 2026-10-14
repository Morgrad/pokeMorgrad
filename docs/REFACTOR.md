# Refactor roadmap

Work items derived from a code audit on 2026-10-14. The audit's findings
are grouped here by risk tier and by session, so we can pick one tier at
a time and never mix a mechanical rename with a structural change.

Referenced file:line numbers were accurate at audit time and may drift.
Re-grep before editing.

Do not batch more than one tier in a single session. The cost of
introducing a subtle bug in `ga_core.py` is a lost GA cycle.

---

## Tier 0 — real defects (fix immediately, one at a time)

### C2 — duplicated battle-split block in `bc_train.py`
Status: fixed 2026-10-14 (`7dba410`).

The split logic ran twice: two `random.Random(SEED)` seeds, two
`shuffle`s, two prints with conflicting row counts. Second assignment
was dead. Removed the first block.

Verification: `grep -c "battle-level split" src/bc_train.py` returns 1.

---

## Tier 1 — mechanical duplication across files (low risk, batchable)

One session, 60 to 90 minutes. Verify after each file. If any import
chain breaks, the failure shows up immediately in `python3 -c "import X"`.

### A1 — four private copies of path resolution
`src/paths.py` is the declared single source of truth. But four modules
re-define `_REPO_ROOT` and `_p()` locally:

- `src/ga_core.py:41`
- `src/eval.py:30`
- `src/bc_train.py:25`
- `src/bc_player.py:30`

These ignore the `POKEMORGRAD_ROOT` environment override that `paths.py`
supports. Not just style — it's a real behavioral inconsistency, and
`docs/STATE.md` section 5.7 currently claims all modules use `paths.py`.
The claim is wrong.

Fix: import `data_path`, `output_path` from `src.paths`. Remove the local
helpers. `eval.py` uses its copy once and can inline.

Verification:
- `python3 -c "from src.ga_core import run_islands; print('ok')"` and similar for each module
- `POKEMORGRAD_ROOT=/tmp python3 -c "from src.paths import REPO_ROOT; print(REPO_ROOT)"` errors loudly
- Run `python3 -m src.audit_before_launch` clean

### A2 — EV caps declared twice with a "keep in lockstep" comment
`src/regmc_db.py:24` declares `EV_MAX_PER_STAT=32`, `EV_MAX_TOTAL=66`.
`src/ga_core.py:58` declares `EV_STAT_CAP=32`, `EV_BUDGET=66`.

Same two format numbers, different names, hand-maintained cross-file
invariant. If they drift, the GA produces genomes the validator rejects.
Move the constants into `regmc_db.py` (the format source of truth) and
import them into `ga_core`.

Verification: `python3 -c "from src.ga_core import EV_STAT_CAP, EV_BUDGET; print(EV_STAT_CAP, EV_BUDGET)"` prints `32 66`.

### A3 — duplicated battle constants across `eval.py` and `ga_core.py`
Both files define `FORMAT`, the battle timeout, and read
`GA_CONCURRENCY`. `eval.py` names `UID_MAX=10**9`; `ga_core.py` inlines
the same value at every `random.randint(1, 10**9)` call.

`eval.py` already imports `ga_core`, so reuse is trivial.

Verification: `python3 -c "from src.eval import FORMAT as F1; from src.ga_core import FORMAT as F2; assert F1 == F2"`.

---

## Tier 2 — BC module cleanup (do as one PR, deferred until after the next retrain)

This tier is 2 to 4 hours and touches `bc_model.py`, `bc_train.py`,
`bc_player.py`. Some items require retraining to verify. Do not attempt
before a long GA run or in the same session as Tier 1.

### C1 — delete `BCModelV3` and all v3 branches
The entire v3 transformer (`bc_model.py:103-198`, roughly 95 lines) is
dead weight. v3 was tested and rejected (STATE.md section 5.4). Production
checkpoints are v2. Nothing instantiates v3.

Deleting it cascades cleanly into:
- `bc_train.py`: remove `is_v3`, `target_*` accounting, the `target_logits`
  argument to `slot_loss`, the `BC_MODEL=v3` branch in `build_model`
- `bc_player.py`: remove the `arch=="v3"` unpack, the `tga`/`tgb`
  handling, the target scoring in `_score_options`

This is the single biggest line reduction available in the repo. It does
not touch the BC track's value as an RL foundation.

Verification:
- `python3 -c "from src.bc_model import BCModel, BCModelV3"` fails on V3
  (expected) and succeeds on BCModel
- Load `bc_best.pt` and `bc_heuristic_v1c.pt` — both v2, both should load
- One 5-battle BC pilot smoke test
- Full retrain on the current dataset if any file contents changed

### C3 — remove `encoder_v` checkpoint field
Written by `save_checkpoint` (`bc_model.py:232, 253-256`), never read.
The comment admits no loader reads it. Drop the parameter and the payload
key.

Verification: train one epoch, load the checkpoint, no error. Old
checkpoints still load because `.get("encoder_v")` was never called.

### C4 — delete tombstone comment for removed `load_checkpoint`
`bc_model.py:263-266` documents a function that no longer exists. Git
history holds the rationale. Delete the comment.

### C5 — item / ability / gender residue
- `bc_player.py:144` always feeds `item=None, ability=None` at inference
- Therefore `it_emb` / `ab_emb` receive index 0 every forward pass, always
  the zero vector
- `gender` is collected in `mon_view` but `encode_mon` never reads it

The embedding widths are baked into `bc_best.pt` (v2 checkpoint) and can't
be removed without a retrain. But `gender` can be dropped from `mon_view`
immediately.

Flag the rest for removal on the next retrain, when a v4 checkpoint can
be trained with the fields actually zeroed.

### C6 — collapse repeated CHECKPOINT CONTRACT banners
Both `bc_model.py` and `state_encoder.py` repeat the "frozen, don't
resize" warning four to five times. Collapse to one short note per file.
Low priority.

---

## Tier 3 — `ga_core.py` restructure (highest care, one item per session)

`ga_core.py` is the correctness core. The species-leak bug (STATE.md
section 5.2) lived in the genome-repair paths. Every change here needs a
GA smoke test before commit.

### B1 — delete `run_ga` legacy single-population path
`src/ga_core.py` lines 965-1047 (approximately 85 lines). The function's
own comment says it has no live callers and is not checkpointed. It is a
drifting mini-copy of `run_islands`'s evolve loop.

Deletion is safe if `grep -rn "run_ga" . --include="*.py"` returns only
the definition and the archived call sites. A single-island `run_islands`
covers any debug need.

### B2 — consolidate genome-repair passes (careful)
Species and item-clause repair is re-derived in:

- `build_random_genome`
- `crossover`
- `enforce_constraints`
- `_strip_species` (with nested `_bases()`)
- `mutate_species`
- `_used_bases` / `_used_items`

This is where the species-clause bug originated. A shared helper
(`_repair_clauses(genome, constraints)`) would unify them.

Do not start this until:
1. A fuzz harness exists that generates N random genomes, runs a full
   mutate/crossover/enforce cycle, and asserts species-clause and
   item-clause hold for every genome
2. That harness passes on the current code (establishing a baseline)
3. After the change, the same harness passes

### B3 — collapse `evaluate` and `_eval_on_subset`
`ga_core.py:898` (`evaluate`, with early-stop) and `1364`
(`_eval_on_subset`, no early-stop) share the same
validate→gather→drop-None→win-rate body. Add a boolean
`early_stop=True` parameter to one function and delete the other.

### B4 — consolidate "top up population" loop
The pattern
while len(pop) < size:
g = build_random_genome(constraints)
if g: 
    pop.append(g)

appears four times:
- `init_population` (twice, back-to-back)
- `run_ga`
- `breed`

A `_fill_to(pop, size, constraints)` helper removes all four. The
back-to-back duplication in `init_population` is a real defect — the
second top-up exists because a previous author noticed the first could
return short, but never fixed the root cause.

### B5 — consolidate lazy-global singletons
Four globals follow the same pattern:
- `_MOVE_PRIORS`
- `_META_ITEMS`
- `_REGIONAL`
- `_HELDOUT`

Each does `global X; if X is None: X = load()` at first call. A one-line
`_cached(name, loader)` helper removes the boilerplate.
