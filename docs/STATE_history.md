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

---

## Day 4 — 2026-10-12 — Full consolidation + BC pilot fixes

**Goal:** clean the repo (many versioned scripts), unify into one working
pipeline per concern, fix the BC pilot, launch the first clean overnight GA.

**Work done:**

- **Package conversion.** `src/` became a real Python package (`__init__.py`,
  `pyproject.toml`, no `sys.path.insert` hacks). All imports are now
  `from src.X import Y`.
- **Version removal.** `state_encoder_v2.py` → `state_encoder.py`,
  `bc_train_v4.py` → `bc_train.py`. `ga_core.py` + `ga_core_v6.py` merged
  into one `ga_core.py`. Zero `_vN` suffixes in active code.
- **BC split.** `bc_train.py` split into `bc_model.py` (net + checkpoints +
  move masks), `bc_train.py` (dataset + loop), `bc_player.py` (poke_env
  Player). Player no longer imports the training pipeline.
- **Eval unified.** `eval_champion.py` + `eval_head_to_head.py` → `eval.py`
  with `--pilot heuristic|bc|both`.
- **Repo hygiene.** Root `README.md` added. `pyproject.toml`, `LICENSE` (MIT),
  `.gitattributes` added. `.gitignore` rewritten with `data/*` whitelist.
  `filter-repo` stripped a 144 MB file from history. 43 MB of replays moved
  out of git to `data/`. Dead code archived (`opponent_gen.py`,
  `ga_counter_*.py`). `__pycache__` untracked.
- **BC pilot fixes (5 bugs):**
  1. Move mask defaulted to all-1s; species missing from priors had
     fully-open masks → `Struggle` and off-list moves got picked.
  2. Inference used species priors instead of live moveset; fixed with
     `_live_moveset_mask` (O(4) lookups via precomputed map).
  3. Fallback selected 0-PP moves; filtered `current_pp > 0`.
  4. `choose_move` nested `choose_random_move` (a `DoubleBattleOrder`)
     inside another `DoubleBattleOrder` → 3-part invalid command.
  5. Doubles move orders lacked a target. Showdown rejects Yawn, etc.
     Fix: `move_target=slot_idx + 1` for single-target moves only;
     self/field/side/spread moves go without a target.
  - **Perf:** model cached across `BCPlayer` instances (was loaded per
    battle; 3× speedup for eval loops).
- **GA bug fixes:**
  - Island migration leaks Umbreon from the locked island into free
    islands. Fix: `_strip_species` replaces foreign locked species on
    entry. Species-clause safe.
  - Battle runners got retry-on-timeout (1 retry per failed battle).
- **New tool:** `tools/build_training_data.py` — driver that streams raw
  replays through `Tracker`, tags each decision with `side_won`, writes
  JSONL. Initial version had two bugs: (1) `parse_log` scanned ALL
  `|player|pN|` lines, including the empty ones at the log tail, so p1/p2
  ended up `""` and everything was skipped; (2) `startswith("|tie")` matched
  `|tier|`. Fixed → 5001 replays produce 72,048 rows with a 0.3% skip rate
  (13 `tracker_empty`). This is the training set for the Day-5 BC retrain.
- **BC training:** added outcome-weighted oversampling (`side_won` → 2x).
  First attempt on 28k rows reached only 49% move acc. Rolled back to v5
  (57.9%). Real fix is more data, see Day 5.
- **First overnight GA launched** at end of Day 4 with heuristic pilot:
  2 × 8h runs (warm-started), 3 islands (A locks Umbreon, B/C free),
  800 battles/genome. Fixed `run/ga_overnight.sh` to use
  `python -m run.ga_run` (the bare script path broke `from src...`
  imports under nohup).

**State at end of day:** repo is clean; pipeline is end-to-end runnable;
BC pilot works but is weak; GA about to run for 10 hours.

## Day 5 — 2026-10-13 — First real GA win + BC retrain verdict

**Headline: GA found a team that beats the meta by 7.4 points on 500 held-out battles.**

- **Island C champion** (`output/champions/CHAMPION_2026-10-12.txt`):
  64.4% vs 57.0% baseline on 100 held-out teams × 5 seeds (100/200/300/400/500).
  Team core: `Basculegion @ Choice Scarf / Salamence-Mega / Incineroar /
  Gholdengo / Rillaboom / Garchomp`.
- **Island B did not generalize.** 68% on the training pool collapsed to 58.7%
  held-out. Best-ever-on-training ≠ held-out quality. Lesson: always confirm
  champions on the held-out pool before trusting the score.
- **BC retrain (72k rows) regressed.** `bc_v6a.pt` = 52.7% val_move_acc vs
  v5's 57.9%. Root cause: the rebuilt dataset is ~half the size of v5's
  original (144 MB, estimated 150k+ rows). More epochs don't compensate for
  fewer rows. `bc_best.pt` remains v5.
- **BC pilot second bug wave** (uncovered by the eval run):
  - `Move` objects in poke_env do **not** expose `.disabled`. Our
    `getattr(mv, "disabled", False)` was always `False`, so disabled moves
    (Fake Out on turn 2+, Flare Blitz under Disable) still got proposed and
    Showdown rejected them, causing loops.
  - `Outrage needs a target` — `randomNormal` was missing from `needs_target`.
    Fixed this day.
  - **Redesign in progress:** stop hand-filtering `mon.moves.values()`.
    Use `battle.available_moves` (poke_env's parsed list of what's actually
    choosable) as the source of truth, and `mv.request_target` for targets.
    This is what poke_env's own `SimpleHeuristicsPlayer` does.
- **GA run2 launched** with warm-start from run1 champions (island A/B/C).
  Running 6h.

**Files touched:** `src/bc_player.py` (target fix), `src/bc_train.py`
(BC_OUT/BC_EPOCHS/BC_PATIENCE env overrides), `output/champions/*` (tracked).

**Open questions for Day 6:**
1. Does the redesigned pilot (using `available_moves`) eliminate loops?
2. Does BC pilot win rate vs held-out improve from 18.3% after the redesign?
3. Is 64.4% the plateau for the heuristic-pilot GA, or does run2 exceed it?
### Day 5 addendum — BC pilot v2 + target extraction

**Two milestones landed in the same morning:**

1. **BC pilot v2 — `battle.valid_orders`.** Two more bug classes (disabled
   moves, target-type mismatches) drove the final redesign: instead of
   hand-filtering `mon.moves` and guessing targets from the DB, the pilot
   now asks poke_env for `battle.valid_orders` — the per-slot list of every
   legal `SingleBattleOrder` (moves with all valid targets, plus switches,
   already filtered for PP/disabled/Encore/Torment/etc.). The model scores
   each option, argmax per slot, wraps in a `DoubleBattleOrder`. This is
   exactly what poke_env's own `choose_random_doubles_move` does. Result:
   zero Showdown rejections in a 6-turn diagnostic. File shrunk from 240 to
   180 LOC; the 60 removed lines were the buggy ones.

   - The `disabled` attribute does not exist on poke_env `Move` objects;
     `getattr(mv, "disabled", False)` was a silent no-op. `available_moves`
     exposes the correct per-turn list, but `valid_orders` is even better —
     it already accounts for targets too.
   - `randomNormal` was missing from `needs_target`, causing `Outrage needs
     a target` errors. Fixed before the redesign (commit 26771f2).

2. **Target labels in training data.** `tools/build_training_data.py` now
   extracts `target_a` and `target_b` per decision row, normalized to a
   5-class space: `0=our right, 1=our left, 2=none, 3=opp left, 4=opp right`.
   Enables a future target head in the model. 72,048 rows regenerated
   (0.3% skip), committed in 80e9520.

**Next step in progress:** `BCModelV3` — transformer over slot tokens +
field token. 5.5 M params (vs 1.5 M for v2). Adds a 5-way target head.
`BCModel` (v2) preserved unchanged so `bc_best.pt` keeps loading.

### Day 5 addendum 2 — Reg M-C corpus is exhausted + v3 training

**Data scrape result:** the format has only **5006 total replays on Showdown**.
We already had 5001; the date-sorted scrape added 5. The rating-sorted scrape
exhausted nothing (all above-1500 replays were already in the index). This is
the ceiling for Reg M-C training data — **72,048 rows is what this format
provides today.** More will only arrive as more games are played.

Implications:
- Can't scale v2/v3 by scraping more Reg M-C games.
- Data augmentation (perspective flip, target mirror) is the cheapest 2× gain.
- Waiting for the format to grow is a real option (weeks-timescale).

**v3 training started** on the 72k-row dataset. Two configurations were
launched by mistake; PID 2627 kept. Early signal (epoch 2):
- `vlm=0.560` (already close to v2's best 0.5787)
- `vltg=0.504` (target head is learning — never existed in v2)
- Train and val loss both dropping → **not overfitting yet**
- 22–30 s/epoch on the 7900 XTX

If v3 continues this trajectory, it beats v5 on move accuracy and adds a
whole new capability (target prediction).

### Day 5 addendum 3 — v3 verdict: doesn't help

**Result:** trained v3 (transformer + target head, 5.5M params) on the same
72k rows. Compared against v5 on the held-out 100 teams × 5 seeds with the
BC pilot:

| Model | move_acc | target_acc | pilot win rate |
|---|---|---|---|
| v5 (v2, 1.5M, MLP) | 0.5787 | n/a | **19.4%** |
| v3 (transformer + target, 5.5M) | 0.5814 | 0.5125 | **8.8%** |

**v3 is 10.6 points worse** in play despite slightly better move accuracy.

**Why:** the target head is only 51% accurate (vs ~47% for the trivial
"always no-target" predictor). Adding its log-prob to option scoring injects
noise that drowns the move-selection signal — v3 often picks a *worse move*
because the target head was confident about the wrong one.

**Lessons:**
1. Imitation accuracy is not the same as strategic quality. v3 imitates
   marginally better but plays meaningfully worse.
2. Bigger model + more heads ≠ better play when the training signal
   (human moves) is noisy at the decision level.
3. BC is close to its ceiling on this dataset. The next lever is NOT
   architecture — it's either better training signal (outcome-weighted,
   Elo-filtered) or a fundamentally different approach (search, RL, or
   hybrid).

**Also captured:** the "BC pilot ally-targeting" bug — v2's use of
`valid_orders` (which lists ally-target options first) was causing the pilot
to attack its own ally on every damaging move, dropping win rate to 0.3%.
Fixed with an ally-target penalty (5.0 log units) for moves not on an
ally-target allowlist. This restored v5 to 19.4% (vs its pre-refactor 18.3%).

**Also captured:** `bc_best.pt` was overwritten with v3 in a `cp` mishap
without 5-seed confirmation. Restored from `bc_v5_best_move.pt`. New rule
added to STATE.md §12: never overwrite `bc_best.pt` until the new model wins
5-seed pilot eval by >3 pts.


## Day 6 — 2026-10-14 — Parallel architecture + Louisville pool + val-overfit

**Two big things landed today.**

**1. Parallel architecture.** Serial GA was CPU-bound on one Python event
loop (110% CPU = 1 core maxed while 15 idle). Diagnosed via `top` under
load, confirmed by a 3-process throughput test at 2.78x aggregate. New
`run/ga_parallel.sh` + `run/ga_island.py` spawn one process per island on
its own Showdown port. `SHOWDOWN_PORT` env var patched into `battle.py`
and `ga_core.py` for port routing. 2.5h parallel run reached 130-148 gens
per island vs serial's ~30-50.

**2. Pool extended + val-selection overfit diagnosed.** Scraped 145
Louisville teams (5th tournament); normalized form-species names; fixed
one `Held Item:` artifact. Pool now 545 teams, regenerated split at
445/100. Island C (fully unconstrained) scored 71.6% on the new holdout,
+15.8 over baseline, CIs disjoint. Islands A/B (Umbreon slot 0) tied with
baseline — Umbreon lock caps them. Val best scores overfit held-out by
15-27 pts (30-team val slice sigma ~ 9 pts, selecting max-of-1300 draws).
This contradicts the Oct-13 finding that train overfits more than val.

**Dual-champion patch.** Write both val-selected and train-selected
champions so the next run settles the selection-rule question empirically.

**VGC noise filter.** `battle.py` suppresses benign poke_env CRITICAL
messages ("You cannot reject open team sheets...").

**Files touched:** `run/ga_parallel.sh`, `run/ga_island.py`,
`src/battle.py` (SHOWDOWN_PORT + filter), `src/ga_core.py` (SHOWDOWN_PORT
+ dual champion), `tools/scrape_louisville.py`,
`tools/normalize_louisville.py`, `tools/regenerate_split.py`,
`tools/throughput_test.py`, `tools/parallel_throughput_test.py`,
`data/pool_split.json`, `data/regional_teams/louisville_*.txt` (145 new).

**Overnight run launched:** `bash run/ga_parallel.sh 2.5 p2`. Eval on
`--opponents heldout` with the new 100-team holdout.

## Day 7 — 2026-10-15 — Parallel arch + VGCPastes pool + train-selection

**Headlines.**

**1. Parallel GA confirmed.** 3 processes, 3 Showdowns, 2.78x throughput.
p3 ran 2.5h at ~1.5 min/gen. Watchdog added (`watch_islands.py`) but has
an mtime-based flaw — a traceback loop looks "alive" — fix pending.

**2. Train-selection wins by +6 to +10 pts.** p3 empirical result:
- B: val 55.8% vs train 66.4% (+10.6)
- C: val 58.8% vs train 64.8% (+6.0)
- A: val 58.0% vs train 59.0% (+1.0)

`run_islands` patched to prefer `best_ever` (train).

**3. VGCPastes pool swap.** 445 mixed-EV teams -> 150 real-EV teams.
Holdout unchanged. Two bugs found:
- Google Sheets HYPERLINK formulas lose URLs in CSV export. Fix: XLSX +
  openpyxl.
- Pokepaste raw text is `/raw`, not `.txt`. First download 404'd 204/204.

Quality: 202/204 pass validate (99%). Dedup: 150 kept.

**4. Debugging.**
- Showdown died during p3 at ~gen 10; all 3 instances. Islands hung in
  ConnectionRefused loops. Watchdog didn't fire (mtime kept advancing).
- WSL sleep masked permanently.
- `extract_champions.py` recovers champions from checkpoints.
- Opponent-side Outrage still causes ~2 battle deaths/island (fix deferred).

**5. Baseline noise floor: ±5 pts on 500 battles.** Same baseline measured
54.8 / 55.0 / 55.8 / 57.2 / 60.6% across separate evals.

**Reference numbers (same holdout):**
| Run | Pool | Best |
|-----|------|------|
| p1  | 270 (inferred) | 71.6% (C) |
| p3  | 445 (mixed) | 66.4% (B train) |
| p4  | 150 (real EVs) | pending |

**Files touched:** `run/ga_parallel.sh`, `run/ga_island.py`,
`src/battle.py`, `src/ga_core.py`, `tools/watch_islands.py`,
`tools/extract_champions.py`, `tools/scrape_vgcpastes.py`,
`tools/swap_pool.py`, `tools/regenerate_split.py`,
`tools/scrape_tournament.py`, `tools/normalize_tournament.py`,
`data/pool_split.json`, `data/regional_teams/vgc_*.txt`.

### 2026-10-15 13:01 — damage.py base module

Champions stat formula (EV points -> max(2*p-1,0)) + base damage. Verified vs Showdown on Garchomp/Incineroar/Rillaboom. No modifiers yet.

Commit: d043744 src/damage.py: Champions stat + base damage formula; tools/log_milestone.py

### 2026-10-15 13:04 — damage.py modifiers

Added crit, burn, weather, terrain, stat stages, screens. Order matches Showdown battle-actions.modifyDamage. Verified: base/rain/-1Atk/+2Def/crit/burn/reflect all match expected values.

Commit: ddb13ff src/damage.py: add crit, burn, weather, terrain, stat stages, screens

### 2026-10-15 13:07 — poke_env API inspected

Heuristic's move scoring uses base_stats (no EVs), no KO detection, no return-damage calc. Pokemon.damage_multiplier() exposed. smart_player target: KO-aware scoring with damage.py.

Commit: ddb13ff src/damage.py: add crit, burn, weather, terrain, stat stages, screens

### 2026-10-15 13:09 — SmartPlayer prototype

Subclass of SimpleHeuristicsPlayer that scores damaging moves via damage.py (KO bonus, HP-fraction penalty, accuracy weighting). NOT yet verified in live battles. Falls back to parent on any exception.

Commit: 1378c82 smart_player: KO-aware heuristic pilot (unverified in battle)

### 2026-10-15 13:10 — docs: damage + smart_player + milestone workflow

STATE §5.20 documents damage.py and smart_player.py. GLOSSARY §18 adds terms. OPERATIONS §21 adds log_milestone workflow.

Commit: 2fd1a9d docs: add damage/smart_player/log_milestone to STATE §5.20, GLOSSARY §18, OPERATIONS §21
