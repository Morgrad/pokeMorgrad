# Runbook: building BC data, training, diagnosing and promoting a BC model

Step-by-step for the behaviour-cloning pilot: build a training set, train a candidate, check it
does not loop, evaluate it and promote it to `output/models/bc_best.pt` only under the promotion
rule. Code details and measured history: `docs/subsystems/bc.md`.

Last verified against code: 2026-11-18

## 0. Read first: BC is currently blocked (2026-11-18)

Known blockers before BC produces a working pilot again:
1. Fixed 2026-11-18: `src/bc_player.py::BCPlayer._state_to_dict` called `mon_view(m, True)` but
   `mon_view(mon)` takes one argument -> TypeError on every decision (since commit 1788b2a,
   2026-10-16); same bug in `tools/generate_heuristic_dataset.py::state_from_battle` (0 rows).
   Pinned by `tests/test_bc_state.py`. No live BC battle has been run since the fix.
2. Still open: `data/regmc_db.json` gained `Lucario-Mega-Z` on 2026-10-16, so the vocab (393 species incl. pad)
   no longer matches checkpoints trained before (392). Old `.pt` files will fail
   `load_state_dict`. Retrain on the current DB, or check out the old DB to use an old model.
3. On a fresh clone, `data/showdown_replays/`, `data/training_data*.jsonl` and `output/models/`
   do not exist (gitignored). Copy them from the original workstation or rebuild (section 1).
Strategic status (2026-10-14): BC imitating humans reached 19.4% and imitating the heuristic
~30-32% vs ~57-61% for the heuristic itself; more BC variants are not expected to beat the
heuristic. Train BC only for a concrete reason (e.g. RL warm-start).

## 1. Build the training set

Human-replay dataset (the default `BC_DATA`):
```
python tools/scrape_replays.py              # rating floor 1600, 200 pages; resumable
python tools/build_training_data.py         # -> data/training_data.jsonl (overwrites)
python tools/build_species_priors.py        # -> data/species_move_priors.json (BC move mask)
```
- `build_training_data.py` prints `DONE: N rows` and `Skip reasons: {...}`. Reference: 5,001
  replays -> 72,048 rows, 0.3% skipped (13 `tracker_empty`), 2026-10-12. Ties and replays without
  players/winner are skipped. NEVER use `tools/batch_parse.py` (old schema, overwrites the file).
- `build_species_priors.py` also changes the GA's move sampling (`src/ga/genome.py::move_priors_for`);
  rebuild it only when you mean to. Do NOT run `tools/build_move_priors.py` for BC: it replaces the
  ladder priors with tournament priors (never applied so far).
- The format had only ~5,006 replays in total (2026-10-13): more scraping adds little.

Heuristic-imitation dataset (needs Showdown on localhost:8000; broken until item 0.1 is fixed):
```
python tools/generate_heuristic_dataset.py --battles 5000 --concurrency 8 --seed 42 \
    --out data/training_data_heuristic.jsonl
```
Reference: 5,000 battles -> 60,688 rows (2026-10-13). Check the final `DONE: N rows from M/K
battles` line: N = 0 means the state-capture bug.

## 2. Train a candidate (never into bc_best.pt)

```
BC_DATA=data/training_data.jsonl BC_OUT=bc_cand_$(date +%Y%m%d).pt BC_MODEL=v2 \
BC_EPOCHS=30 BC_PATIENCE=3 BC_BATCH=256 \
    nohup python -m src.bc_train > /tmp/bc_train_$(date +%m%d).log 2>&1 &
```
- `BC_OUT` defaults to `bc_candidate.pt` (since 2026-11-18; it used to default to `bc_best.pt`
  and overwrite the production model on the first improving epoch). Give each candidate its own
  name and promote by hand (section on promotion).
- `BC_MODEL=v3` (transformer) exists but played at 8.8% (2026-10-13); v2 is the only sane choice.
- Don't raise `BC_BATCH`: 512/1024 lost move accuracy at matched epochs; bf16 gave no speedup
  (2026-10-13). Epoch time on the 7900 XTX: v2 ~12 s, v3 22-30 s (2026-10-13).
- GPU: the trainer uses `cuda` if torch sees one (ROCm build on the original workstation). Do not
  train while a GA/eval/local LLM needs the GPU or RAM; ask before long jobs.

Read the log:
```
  pre-clean: 72048 -> ... rows (dropped ... consecutive dupes)
  chunked into ... battles, dropped ... corrupted, kept ...
  battle-level split: ... train / ... val battles
Epoch  1/30  trl=... tra=... trm=... trs=...  vll=... vla=... vlm=0.xxx vls=0.xxx  (NN.Ns) *
```
`vlm` = val move accuracy (the save criterion, `*` = saved), `vls` switch accuracy, `vltg` target
accuracy (v3 only), `vll` val loss (spiky because of the -1e4 mask; ignore it). Reference vlm: v5
0.579, heuristic-imitation 0.6875. A higher vlm does NOT mean better play (four counter-examples,
STATE.md 5.12): only the live eval in section 4 decides.

## 3. Diagnose: no illegal-order loops

After any change to `src/bc_player.py` or a new model:
```
PYTHONPATH=. BC_PILOT_PATH=output/models/bc_cand_YYYYMMDD.pt python tools/bc_diagnostic.py 3
```
(baseline team vs random train-pool teams on localhost:8000; writes `/tmp/bc_diag.jsonl`.)
Then compute calls per turn per battle (rows are one per `choose_move` call; a new battle starts
when the turn number drops):
```
python - <<'EOF'
import json
rows = [json.loads(l) for l in open("/tmp/bc_diag.jsonl")]
battles, cur = [], []
for r in rows:
    if cur and r["turn"] < cur[-1]["turn"]:
        battles.append(cur); cur = []
    cur.append(r)
battles += [cur] if cur else []
for i, b in enumerate(battles):
    t = len({r["turn"] for r in b})
    print(f"battle {i}: {len(b)} calls / {t} turns = {len(b) / max(t, 1):.2f} calls/turn")
EOF
```
PASS: calls/turn below 5 in every battle (forced switches after a faint legitimately add calls;
the fixed pilot measured <= 2 on 2026-10-13). FAIL (100-2000 calls per turn, `[Invalid choice]` in
the output) = the order-rejection loop is back (history: STATE.md 5.1). The script also prints BC vs
heuristic agreement by turn and HP bucket; low agreement is expected, it is not a pass/fail.

Encoder edits additionally need the bit-identity gate:
`python tools/encode_snapshot.py capture` (before) and `python tools/encode_snapshot.py check` (after, exit 0).

## 4. Evaluate the candidate (5 seeds, held-out pool)

The model is chosen with `BC_PILOT_PATH`; the positional argument of `src.eval` is a TEAM file.
```
BC_PILOT_PATH=output/models/bc_best.pt python -m src.eval data/baseline_team.txt \
    --pilot bc --opp heuristic --seeds 100 200 300 400 500 --concurrency 8 | tee /tmp/bc_eval_best.log
BC_PILOT_PATH=output/models/bc_cand_YYYYMMDD.pt python -m src.eval data/baseline_team.txt \
    --pilot bc --opp heuristic --seeds 100 200 300 400 500 --concurrency 8 | tee /tmp/bc_eval_cand.log
```
Run both on the same server, back to back, nothing else on the port. The loaded model prints
`BC pilot loaded (v2): epoch=.. vlm=..`: check it is the file you meant. Note: numbers in
`docs/subsystems/bc.md` were measured on the pre-2026-10-15 holdout; re-measure the current
`bc_best.pt` instead of comparing to them.

## 5. Promotion rule (never break it)

`output/models/bc_best.pt` is what every `--pilot bc` run loads by default. Promote a candidate
ONLY if its 5-seed (500-battle) held-out win rate is at least 3 points above the current
`bc_best.pt` measured in the same session:
```
cp output/models/bc_best.pt output/models/bc_best_prev_$(date +%Y%m%d).pt
cp output/models/bc_cand_YYYYMMDD.pt output/models/bc_best.pt
```
Why: on 2026-10-13 a blind `cp bc_v3_5m.pt bc_best.pt` regressed the pilot (8.8% vs 19.4%) and
had to be restored from `bc_v5_best_move.pt`. Record the eval logs, data set, arch and date in the
history log. Model files are gitignored: back them up outside the repo.

## 6. Cleanup

`ls -lat output/models/*.pt` to list; delete superseded candidates by name, never `bc_best.pt` or
its latest `_prev` copy.

## Related docs

- [BC subsystem](../subsystems/bc.md), [evaluation runbook](evaluation.md)
- [Data pipeline runbook](data-pipeline.md), [data files](../reference/data-files.md)
- [tools-data.md](../reference/tools-data.md), [tools-ops.md](../reference/tools-ops.md)
- [Policy (promotion rule)](../design/policy.md), [environment](environment.md)
