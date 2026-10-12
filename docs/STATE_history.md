# Pokémon AI Project — History Log

> **READ STATE.md FOR CURRENT STATE.**
> This file is the raw chronological log of the project's evolution.
> Old entries are stale by design — they record what we thought at the time.
> Do not treat the "latest" section at the bottom of this file as current.

---

## Chronological log begins below

# Session 2026-10-10 18:05 (early state)

## Current goal
Train Reg M-C self-play for 1M steps (run_id 1000) to improve Umbreon team.

## Latest run — HEALTHY
RUN_ID: 1000
Started: 2026-10-10 17:43
Last observed TB step: 141312 @ ~18:10 (still only 0.zip checkpoint)
fps: 144
Latest checkpoint: seed1000/0.zip only (no 20k+ zip yet as of 18:05)
TB dir: ~/vgc-bench/results/logs_sp/reg_mc/20_teams/seed1000_0/
Checkpoint dir: ~/vgc-bench/results/saves_sp/reg_mc/20_teams/seed1000/
Watchdog PID: 2424 (log: /tmp/watch_server.log)

## Prior runs
seed101  → 0.zip, 101376.zip
seed500  → 0.zip, 30720.zip
seed502  → 0.zip, 101376.zip

## Server / TensorBoard
Showdown: up on :8000
TensorBoard: up on :6006

## Key facts learned
- vgc_bench.train AUTO-RESUMES from highest-numbered .zip in seed${RUN_ID}/. No --checkpoint flag exists.
- If highest zip < 20,000, training restarts from step 0 (BC-init case).
- save_interval = 20,000 in code, but observed saves at 30720 / 101376 — effective rule unclear.
- --help must be run from ~/vgc-bench (data files load at import).
- vgc_bench.eval is the upstream paper artifact: needs seeds 1-5, all methods, LLM player, TB tag "train/eval". NOT usable for our metric.
- Custom evaluate_checkpoint.sh required to measure win rate vs the 296-team pool.

## Project layout
- ~/project/opponent_pool.json — 296 tournament teams (species lists)
- ~/vgc-bench/teams/reg_mc/ — team files used by RandomTeamBuilder
- ~/vgc-bench/results/saves_sp/reg_mc/20_teams/seed*/ — checkpoints
- ~/vgc-bench/results/logs_sp/reg_mc/20_teams/seed*_0/ — TB logs

## Known issues
- Showdown crash stalls training silently. Watchdog mitigates.
  Recover: stop_all → start_server → start_training (auto-resumes).

## Next actions
1. Wait for first non-0 zip in seed1000 (expect at 20k-100k steps).
2. Write + test evaluate_checkpoint.sh against seed101/101376.zip baseline.
3. Consider upgrading watchdog to auto-restart training after stall.

## North Star
Find the best Reg M-C team (species + items + moves + abilities + natures + EVs).
- Policy RL (vgc_bench.train) improves the PILOT, not the team.
- Team search uses a FIXED pilot + fitness = win rate vs 296-team pool.
- Evaluator script (evaluate_team.sh) — TODO.
- Existing tools: ~/project/ga_set.py, ga_set_history.json, seed_team_v2.txt, winner_v1.txt.

## Team evaluation
- Evaluator: ~/pokemon-ai/evaluate_team.sh (wraps evaluate_team.py)
- Baseline team: ~/pokemon-ai/baseline_team.txt (seed Umbreon set)
- Pilot: NeuralPlayer (matches ga_set.py for comparability)
- Opponents: 10 random from opponent_pool.json × 2 battles = 20 total
- Eval Showdown runs on port 8001 (training uses 8000)
- Smoke test: bash evaluate_team.sh ~/pokemon-ai/baseline_team.txt 3 1 8001 42

## Eval results
- 2026-10-10 18:13 — smoke test (3 opps × 1, seed 42): 66.7% (2/3)
- TODO: run 10×2 seed 42 and seed 43 for stable baseline

## Anomaly
- seed 42: three runs → 65%, 65%, 85%. 3s elapsed each — unrealistic.
- seed 43: 40% in 42s — realistic timing.
- Investigate MIN_TURNS filter + real battle completion. Debug script queued.

## Anomaly RESOLVED (2026-10-10 18:20)
- 3s runtime is REAL. Debug shows 10 battles with turns=11-27, all finished, 0.26-1.70s each.
- NeuralPlayer is fast; the Showdown server is local. No bug.
- Real problem is variance at N=20: same seed → 65%, 65%, 85%, 40% across runs.
- Fix: multi-seed eval (21 opps × 2 battles × 5 seeds = 210 battles).

## Champions evaluated
(pending — will fill after the 5x5 run above)

## MAJOR CORRECTION (2026-10-10 18:35)
- Retract "GA was noise-mining". Champions beat baseline by +14 to +18 points
  on 210 battles each. That's 4-5 sigma. Real signal.
- BUT: our eval never passes rules_enabled to NeuralPlayer. If RuleEngine
  defaults to no-rules when enabled=None, we're evaluating a crippled pilot.
- README claims 80% for seed team; we measured 56%. That gap is likely
  the missing tactical rules.
- Champion changes look anti-optimal by VGC standards (Modest Incineroar,
  Overgrow Rillaboom, Sassy Gholdengo). Suggests NeuralPlayer is exploitable
  when rules are disabled.
- BLOCKER: verify rules_enabled semantics in ~/project/tactical_rules.py.

## RESULTS AFTER CORRECTION (2026-10-10 18:45)

### Rules sweep (baseline team, 3 seeds × 42 battles)
- none: 56.3%
- A,B,C,D: 46.6%
- A,B,C,D,E,F,G: 55.9%
- A,B,C,D,F,G: 52.5%
- A,B,C: 45.3%
=> Tactical rules HURT. README "80%" claim is not reproducible.
=> Retire the 80% claim. Use ~56% as the honest baseline.

### Champion eval (same config as baseline, 5 seeds × 42 battles)
- winner_1791565446: 156/210 = 74.3%   <-- best
- winner_1791566732: 145/209 = 69.4%
- winner_1791570034: 124/208 = 59.6%
- winner_1791571685: 123/210 = 58.6%
- baseline:          121/210 = 57.6%
- winner_1791568490: 118/210 = 56.2%

=> Champion beats baseline by +16.7pt at N=210 (5σ). Real.

### Hypothesis under test
Champion likely exploits NeuralPlayer's NN move predictor
(shared pilot in all evals), not genuinely stronger VGC team.
Test: re-run vs SimpleHeuristicsPlayer.

### Rules sweep (baseline team, 3 seeds × 42 battles)
- none: 56.3%
- A,B,C,D: 46.6%
- A,B,C,D,E,F,G: 55.9%
- A,B,C,D,F,G: 52.5%
- A,B,C: 45.3%
=> Tactical rules HURT. README "80%" claim is not reproducible.
=> Retire the 80% claim. Use ~56% as the honest baseline.

### Champion eval (same config as baseline, 5 seeds × 42 battles)
- winner_1791565446: 156/210 = 74.3%   <-- best
- winner_1791566732: 145/209 = 69.4%
- winner_1791570034: 124/208 = 59.6%
- winner_1791571685: 123/210 = 58.6%
- baseline:          121/210 = 57.6%
- winner_1791568490: 118/210 = 56.2%

=> Champion beats baseline by +16.7pt at N=210 (5σ). Real.

### Hypothesis under test
Champion likely exploits NeuralPlayer's NN move predictor
(shared pilot in all evals), not genuinely stronger VGC team.
Test: re-run vs SimpleHeuristicsPlayer.

## PILOT + OPPONENT OVERHAUL (2026-10-10 19:00)
- Scraper: ~/project/scrape_limitless.py → ~/project/real_teams/*.txt
  Source: Limitless API. Real teamlists (species/item/ability/moves/nature).
  EVs are defaulted (Limitless doesn't publish them).
- GA v3: ~/project/ga_set_v3.py uses SimpleHeuristicsPlayer pilot +
  real_teams/ opponents.
- Eval v2: ~/pokemon-ai/evaluate_team_v2.py — NeuralPlayer pilot vs real teams.
- Next: run scraper, verify poke-env >= 0.11, then evaluate baseline +
  champions vs real teams.

## 2026-10-10 19:55 — pause + cleanup
- Training run 1000 stopped (was on GPU competing with eval).
- Watchdog stopped.
- stop_all.sh rewritten to only kill training (8000), not eval (8001).
- New stop_everything.sh for when we need full shutdown.
- Eval server on 8001 restarted; re-running baseline vs real teams now.
- Training can be resumed later: start_training.sh 1000 + watchdog.

## 2026-10-10 20:10 — real teams cleaned
- Scraper: 1044 teams → cleaner dropped 299, kept 745.
- Main drop reason: unknown species (284). Likely Mega X/Y and regional
  forme suffixes not covered in regmc_learnsets.json lookup.
- Backup: ~/project/real_teams_raw_backup/
- Timeout in evaluate_team_v2.py reduced 120s → 25s so bad teams fail fast.
- Running baseline vs champions against real teams now.

## 2026-10-10 20:15 — real teams, NeuralPlayer pilot

| Team | Wins | Rate |
|---|---|---|
| winner_1791565446 | 140/206 | 68.0% |
| winner_1791566732 | 116/206 | 56.3% |
| baseline | 94/206 | 45.6% |

Delta champion-1 over baseline: +22.4 points (6σ). Consistent with earlier
+16.7 (vs NN + species) and +18.6 (vs SH + species) findings.

BUT champion sets still look VGC-wrong (Modest Incineroar, Overgrow Rillaboom,
Moxie Mega Salamence, Sassy Gholdengo). Hypothesis: GA exploits NeuralPlayer
NN bias, not genuine team strength.

## Next: re-run same 3-team comparison with SimpleHeuristics pilot
File: ~/pokemon-ai/evaluate_team_v3.py
If champion advantage persists → GA found real signal.
If champion advantage collapses → GA was NN-exploit; needs SimpleHeuristics
pilot for GA v3 training too.

## 2026-10-10 20:25 — GA v3 launched
- ga_set_v3.py: SimpleHeuristics pilot + 745 real teams.
- Fixed indentation bug introduced by earlier sed patch (line 42).
- Expected runtime: 2-4 hours for 8 generations × 6 genomes × 42 battles.
- Monitor: tail -f /tmp/ga_v3.log
- Success criterion: best fitness > 67.3% (baseline against real teams
  with SimpleHeuristics pilot).

## Port conventions
- 8000: training + GA (inherited default)
- 8001: team evaluation scripts
- Both can coexist.

## 2026-10-10 20:26
GA v3 first launch failed with ConnectionRefused on :8000 — server was
killed by stop_all.sh. Restart server on 8000 and relaunch.

## 2026-10-10 20:30 — item clause fix
- Real teams from Limitless sometimes have duplicate items (some mons with
  same item). Showdown Reg M-C enforces Item Clause → teams rejected.
- ~/project/dedupe_real_items.py replaces dup items with unused fallbacks.
- Must run before any GA / eval that uses real_teams/.
- Check: grep -c "Popup message received" /tmp/ga_v3.log  (should be 0)

## 2026-10-10 20:32 — dedupe + relaunch
- dedupe_real_items.py fixed 3/745 teams (3 item changes total).
- Smoke test passed: 5 battles, 40% (sample too small to interpret).
- Previous GA log had 6 stale popups — truncating before relaunch.
- If new popups appear after relaunch: stricter dedupe needed.

## 2026-10-10 20:40 — item whitelist validation
- All 76 mega stones have "stone" key in regmc_items.json → OK.
- 714 kept teams use 134 unique items; all 134 are in whitelist → OK.
- CANNOT find format definition via grep in ~/pokemon-showdown/ → unknown
  if whitelist matches actual server rules.
- Empirical test: 90s GA run, count popups. 0 popups = pool clean.

## 2026-10-10 20:42 — GA v3 launched clean
- 90s dry-run: 0 popups. Pool validated.
- Format defined in ~/pokemon-showdown/config/formats.ts (and mods/champions/).
- Full GA v3 running: 6 genomes × 8 gens × 42 battles = 2016 battles.
- Monitor: tail -f /tmp/ga_v3.log
- Checkpoint saved after each gen (ga_checkpoint.json).
- Success criterion: best fitness > 67.3% (baseline vs real teams).

## 2026-10-10 20:42 — GA v3 running
- 0 popups in 90s dry-run → pool is clean.
- Format not found by grep in config/formats.ts; likely constructed at
  runtime or defined in data/mods/champions/. Not blocking.
- GA v3 launched: 6 genomes × 8 gens × 42 battles.
- PID stored; log at /tmp/ga_v3.log; checkpoint at ga_checkpoint.json.

## 2026-10-10 20:45 — GA v3 completed but did nothing
- 8 generations in 38 seconds total → battles are very fast (SH both sides).
- BUT every genome in every generation has baseline species. No species drift.
- Best fitness by gen: 78, 64, 64, 62, 73, 60, 76, 69.
  Gen 1 best > gen 8 best → no learning.
- Champion (gen 1, 78%): species identical to baseline. Likely baseline + noise.
- Suspect: random_team() not producing diverse initial pop.
- ACTION: run diagnostic to confirm; add species mutation operator.

## 2026-10-10 20:47 — GA v3 post-mortem
- Initial pop was diverse (Pikachu, Steelix, etc.).
- But elites from gen 1 (baseline-like) dominated crossover.
- Species never mutated. Sets mutated but baseline was already set-optimal.
- Champion eval: 68.6% avg → statistically identical to baseline 67.3%.
- FIX: added mutate_species() (30% rate) + 15% random immigrants.
- Rerunning GA v3 with species exploration.

## 2026-10-10 20:53 — GA v3 scaled
- OPPONENTS_PER_TEAM 21 → 105 (= 210 battles/genome, SE ~3.4%)
- GENERATIONS 8 → 5 (to bound runtime)
- MIN_VALID_BATTLES 40 → 180
- Population 6 × 5 gens × 210 battles = 6300 battles, ~10-15 min expected.
- First run with meaningful statistical power.
- Decision: >75% = new champion; 65-70% = baseline is local optimum.

## 2026-10-10 21:00 — opponent validation gap found
- GA popups show opponent teams (O-prefix) rejected for:
  - "Kingambit has multiple copies of Protect" (duplicate moves)
  - "Meowstic can't have Competitive" (illegal ability)
- Previous validator only checked items. Real teams also need move/ability checks.
- Error rate <1% — not blocking. GA continues.
- v2 validator written (~/project/validate_real_teams_v2.py), to run AFTER GA.

## 2026-10-10 21:08 — GA v3 scaled run: KEY FINDING
Gen 1 with N=210 per genome:
  genome 1 (baseline): 65.7%
  genome 5 (baseline): 67.5%
  genome 2 (random species): 2.4%
  genome 3 (random species): 4.8%
  genome 4 (random species): 3.4%
  genome 6 (random species): 3.9%

=> Random species swaps are CATASTROPHIC (2-5% win rate).
=> Baseline team is at a strong local optimum. 65-67% reproduced at N=210.
=> Earlier "78% champion" was noise from N=42 runs.
=> GA got stuck in gen 2 (likely rejected opponent teams blocking battle_against).

## Conclusions
1. Baseline is a legitimate 67% team vs real teams with SimpleHeuristics pilot.
2. Random mutation cannot improve it — search space needs to be restructured.
3. Real path forward: role-preserving swaps or opponent-specific targeting.

## Next steps (tomorrow)
1. Run v2 validator on real_teams/ (catches dup moves + bad abilities).
2. Lock in baseline with 10-seed eval for a defensible final number.
3. Decide: accept baseline, or build role-based GA.

## 2026-10-10 21:10 — END OF SESSION

### Locked-in baseline
- Baseline team: 63.3% vs 681 real teams, SimpleHeuristics pilot
- 10 seeds, 2100 battles, SE ~1.05%
- 95% CI: 61.2 - 65.4%
- This is the defensible number, replacing the README's 80% claim.

### Confirmed working stack
- ~/pokemon-ai/evaluate_team_v3.py (SH pilot, real teams)
- ~/pokemon-ai/baseline_team.txt (source of truth)
- ~/project/real_teams/ (681 validated teams)
- ~/pokemon-ai/validate_real_teams_v2.py (checks item+ability+move+species)

### Deprecated
- NeuralPlayer as evaluator (22pt handicap)
- Random-species GA (2-5% win rate; destroys synergy)
- 80% README claim

### Next session
1. Update READMEs to 63.3%.
2. Baseline_team.txt → champions/
3. Opponent-weakness analysis: which 20 teams does baseline lose to?
4. Role-based GA design (archetype-preserving swaps)
5. Long-term: rebuild NN pilot with richer observations

## 2026-10-10 21:40 — v5 launched with canonical DB
- regmc_db.json built from Showdown format dex (646 KB, authoritative).
- regmc_db.py provides validate_team(); 681/681 real teams pass.
- ga_set_v5.py: no legalize(), no dedupe — teams are legal by construction.
- Sanity: 100/100 random teams valid, seed team valid.
- GA v5 launched with POP=6, GENS=5, 105x2 battles/genome.
- Monitor: tail -f /tmp/ga_v5.log

## 2026-10-11 22:30 — counter-meta GA launched
- Scraped 400 top-cut teams from 4 Regionals (Baltimore, Brisbane, Frankfurt, Recife).
- Top meta species: Rillaboom 53%, Sneasler 40%, Incineroar 34%, Gholdengo 31%, Kingambit 31%.
- Umbreon is NOT in the regional top 20 — genuinely off-meta.
- ga_core.py — engine with slot constraints.
- ga_counter_umbreon.py — Umbreon locked in slot 0.
- ga_counter_free.py — no constraints.
- Fitness = win rate vs 400 regional teams (the actual meta).
- Pilot: 10 pop, 10 gens, 80 battles/genome, ~5 min each.
- Champions written to ~/project/champions/latest_ga.txt (overwritten each run).

## 2026-10-11 00:30 — MAJOR BREAKTHROUGH

### Head-to-head results (400 regional teams, 3 seeds, N=1200)
- baseline:                682/1200 = 56.8%
- Umbreon-locked champion: 843/1200 = 70.2%  (+13.4)
- Free champion:           787/1200 = 65.6%  (+8.8)

### Key findings
- Umbreon-locked beat free by 4.6 points. Surprising.
- Hypothesis: free GA converged to single Sand archetype by gen 12;
  Umbreon lock preserved diversity.
- Umbreon + Snarl + Yawn + Whimsicott Tailwind + Unburden Sneasler =
  real support shell.
- Items ARE meaningful (Focus Sash Arcanine, White Herb Sneasler are real
  competitive tech). Prior belief they were noise was wrong.

### Architecture upgrades for next run
- meta_items.json: empirical item distribution per species from 400 teams
- _pick_item_for: 70% weight on meta distribution
- Pool split: 300 train / 100 held-out (via pool_split.json)
- eval_head_to_head uses held-out pool
- battles/genome: 500 -> 800

### Tomorrow morning launch (one command)
nohup bash ~/pokemon-ai/ga_overnight.sh > /tmp/ga_overnight.log 2>&1 &
(chain: run1 5h → run2 5h warm-start → final eval vs held-out)

### Champions (saved)
- ~/project/champions/archive/2026-10-11/umb_70.2.txt
- ~/project/champions/archive/2026-10-11/free_65.6.txt
- ~/project/champions/archive/2026-10-11/eval.txt

### Open questions
- Does +13.4 hold on held-out 100? (tomorrow's eval answers this)
- Does Umbreon-lock advantage persist at 5h instead of 11 min?
- Does item optimization add measurable win rate?

# Pokémon AI Project — State

Last updated: 2026-10-11 01:00

## Current mission
Find a Reg M-C team that beats the elite tournament meta. Umbreon-constrained
search is the primary track (proved better than free search tonight).

## Headline result (2026-10-10 → 2026-10-11)
Head-to-head on 400 regional top-cut teams (3 seeds, N=1200 each):

| Team                    | Score | vs baseline |
|-------------------------|-------|-------------|
| baseline_team.txt       | 56.8% | —           |
| **ga_umbreon champion** | **70.2%** | **+13.4** |
| ga_free champion        | 65.6% | +8.8        |

Key finding: **Umbreon-constrained GA beat free GA by 4.6 points.**
Hypothesis: lock preserves diversity; free GA collapsed to a single
Sand archetype by gen 12.

## Next run (scheduled tonight ~01:00, unattended for 10h)
- Chain: `~/project/run/ga_overnight.sh`
- Islands: A=Umbreon-locked, B=free, C=free
- Config: 10 pop/island, 800 battles/genome, 5h per run × 2 runs
- 6 champions expected (~00:XX + 10h)
- Final eval uses held-out 100 teams (NOT the training 300)

### To launch (tomorrow morning):
    pkill -9 -f "ga_run\|ga_core" 2>/dev/null; sleep 1
    nohup bash ~/project/run/ga_overnight.sh > /tmp/ga_overnight.log 2>&1 &
    disown
    sleep 45
    tail -20 /tmp/ga_overnight.log
    # If you see "=== GEN 1/999 ===" — walk away

### To check later:
    ls -la /tmp/ga_overnight_done_* 2>/dev/null && echo "ALL DONE"
    cat /tmp/ga_final_eval.log
    ls ~/project/output/champions/ga_run*_island_*.txt

## Directory layout (refactored 2026-10-11)
    ~/project/
    ├── data/          read-only inputs (regmc_db.json, real/regional teams,
    │                  baseline_team.txt, meta_items.json, pool_split.json)
    ├── src/           Python modules (ga_core, ga_core_v6, regmc_db,
    │                  showdown_validator, eval scripts, audit)
    ├── run/           entry points (ga_run.py, ga_overnight.sh)
    ├── tools/         setup scripts (build DB, scrape, normalize)
    ├── ops/           server management (start/stop/watch)
    ├── output/
    │   ├── champions/
    │   └── checkpoints/v6/<run_id>/
    ├── docs/          this file + README + MORNING
    └── archive/       old bots, old GA versions, one-offs, replays

## Key paths (memorize these)
| Purpose             | Path                                             |
|---------------------|--------------------------------------------------|
| DB (source of truth) | ~/project/data/regmc_db.json                    |
| Baseline team       | ~/project/data/baseline_team.txt                 |
| Training pool       | ~/project/data/regional_teams/ (300 via pool_split) |
| Held-out pool       | same dir (100 via pool_split.json)               |
| Real teams (681)    | ~/project/data/real_teams/                       |
| Item prior          | ~/project/data/meta_items.json                   |
| GA engine           | ~/project/src/ga_core.py + ga_core_v6.py         |
| Showdown gate       | ~/project/src/showdown_validator.py              |
| Chain script        | ~/project/run/ga_overnight.sh                    |

## Data pipeline (how the DB was built)
- `~/project/tools/build_regmc_db.js` — extracts everything from Showdown's
  format dex. Rebuild with: `node ~/project/tools/build_regmc_db.js`
- Result: regmc_db.json = 391 species, 166 items, 515 moves, 316 abilities,
  25 natures, type chart. Authoritative.
- Regional teams scraped from limitlessvgc.com/tournaments/{441,442,443,444}
  and normalized (name mapping, item validation, ability validation).

## Architecture decisions locked in
- **Showdown format dex is the source of truth.** No hand-maintained JSON.
- **Every generated team passes through `showdown_validate.js`** before
  entering the population. This is a hard gate — illegal teams can't exist.
- **Island model** (3 independent populations + ring migration every 5 gens)
  prevents the diversity collapse we saw in single-population runs.
- **Stagnation restart** after 5 gens without improvement.
- **Diversity monitor**: inject 3 randoms if unique base species < 15.
- **Held-out eval**: fitness uses 300 training teams, final eval uses the
  other 100, so we can trust the final number.

## What worked
- Canonical DB eliminates the whack-a-mole of illegal teams.
- Showdown gate caught Greninja/Battle Bond, Meowstic/Competitive,
  Covert Cloak, Assault Vest, duplicate moves, unknown species.
- Umbreon-locked island > free island, proving diversity matters more
  than search space.

## What's still weak
- **Pilot is SimpleHeuristicsPlayer** (not NeuralPlayer). Our NeuralPlayer
  is 22 points worse. Fixing it is a multi-day project.
- **Items are under-optimized.** Fitness N=800 gives ~1.6% error; item
  effects are typically 1–4%, so we can't reliably evolve them. Mitigated
  by loading meta_items.json as a prior.
- **Opponent sample per genome is 800**, not full 300, so fitness is noisy.
- **Training pool is 300** — could be larger if we scrape more regionals.

## Tonight's key learnings
1. Random species swaps produce 2–5% teams. Catastrophic. Always use
   role/species constraints.
2. GA diversity collapses in ~12 generations without intervention.
3. Showdown format data has edge cases (Bond forms, transfer-only moves);
   only the validator catches them.
4. A 5h run per config is enough; 10h in one shot risks losing everything
   if the machine dies. Two 5h runs + checkpoints = recoverable.

## Tomorrow's plan (after results are in)
1. **Analyze:** which island won? What species? Does the Umbreon-lock
   advantage hold at 5h instead of 11 min?
2. **Fix convergence further:** add mutation rate floor, more aggressive
   immigration, or niching.
3. **Evaluate held-out honestly:** final eval already does this (100 teams).
4. **Consider:** role-based GA (each slot has an archetype) instead of
   species-locked slots.
5. **Long-term:** rebuild NeuralPlayer properly or adopt a stronger pilot.

## If something crashes overnight
    # Check where it stopped
    tail -40 /tmp/ga_overnight.log
    tail -40 /tmp/ga_run1.log
    tail -40 /tmp/ga_run2.log

    # Resume run1 from latest checkpoint
    cd ~/project && source ~/llm-env/bin/activate
    nohup python ~/project/run/ga_run.py run1 5 > /tmp/ga_run1_resume.log 2>&1 &
    disown
    # Auto-resumes from output/checkpoints/v6/run1/gen_NNNN.json

## Rollback (pre-refactor)
    ~/cleanup_2026-10-11/refactor_20261011_005140/project_before
    rm -rf ~/project
    cp -r ~/cleanup_2026-10-11/refactor_20261011_005140/project_before ~/project

## Session history
- 2026-10-09: initial bot + GA v1 (NeuralPlayer pilot)
- 2026-10-10: GA v2/v3, discovered NeuralPlayer exploit, pivoted to
  SimpleHeuristics pilot, canonical DB, Showdown gate, 70.2% champion
- 2026-10-11: island GA v6, refactored directory structure, launching
  10h overnight chain with 3 islands × 2 runs
