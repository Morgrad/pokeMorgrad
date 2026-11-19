# Design decisions and open questions

The decisions that shape pokeMorgrad (data, GA, fitness environment, pilots, BC), each with
its date, rationale and whether it still holds in the code, plus the questions that are still
open. Read this before changing a default, the fitness environment, the pool or the island
setup, so you do not undo a decision that was made on evidence.

Last verified against code: 2026-11-18

Format facts (always true): `gen9championsvgc2026regmc` (Reg M-C, Champions mod), doubles,
Mega Evolution legal, Terastallization NOT legal, EVs 0-32 per stat, total 66, stat term
`max(2*pts-1, 0)`. Dates are when the decision was made; details and measurements are in
`docs/history/` (file named after the date).

## 1. Data and format

| Date | Decision | Rationale | Status today |
|---|---|---|---|
| 2026-10-10/11 | Showdown is the source of truth. Every format fact comes from `data/regmc_db.json`, generated from Showdown's dex by `tools/build_regmc_db.js`. No hand-maintained format JSON. | Hand lists caused whack-a-mole illegal teams (Bond forms, transfer-only moves). | Holds. `src/regmc_db.py` reads the JSON; `regmc_db.normalize_species_name` canonicalizes names. |
| 2026-10-11 | Every generated team passes the real Showdown validator before entering a population (hard gate). | Only the validator catches edge cases (Greninja/Battle Bond, Meowstic/Competitive...). | Holds: `src/ga/legality.py::filter_legal_genomes` batches `src/showdown_validator.py::check_teams` (Node subprocess running `src/showdown_validate.js`). |
| 2026-10-12 | Big data stays local and gitignored (`data/*` whitelist in `.gitignore`); small canonical files are tracked so the pipeline runs without re-scraping. | `filter-repo` had to strip a 144 MB file from history. | Holds. Non-whitelisted `data/` files need `git add -f`. |
| 2026-10-12 | `src/` is a package (`from src.X import Y`); no versioned filenames in active code (git holds versions; `archive/` keeps old names). | Many `_vN` scripts had drifted apart. | Mostly holds. Exception: `run/ga_island.py` and `tools/*.py` insert the repo root into `sys.path` so they run as scripts. |
| 2026-10-13 | All file paths go through `src/paths.py` (`REPO_ROOT` from `POKEMORGRAD_ROOT` or the parent of `src/`; `SHOWDOWN_DIR` default `~/pokemon-showdown`). Pool entries resolve by basename. | Hard-coded `/home/morgrad/...` paths silently produced an empty opponent pool on a new host. | Holds. Two shell scripts still `cd ~/pokeMorgrad` (`run/ga_parallel.sh`, `tools/verify.sh`). |
| 2026-10-15 | Priors are meta-level vocabulary, so their corpus may include holdout and non-split teams. "Held-out is sacred" governs fitness and final eval only. | Priors answer "what does the meta look like", not "what is this team". | Holds. |
| 2026-10-15 | Do not scrape pokechamdb.com (explicit AI-crawler block); pokebase.app API and pokemon-zone.com (Cloudflare) not scraped either. Primary sources: Limitless, VGCPastes, metavgc HTML. | Respect robots.txt intent. | Holds. |
| 2026-10-16 | Blended opponent priors: `count = corpus_count + N0 * metavgc_share`, N0 = 10; max 10 spreads per species; a metavgc ability table is used only if >= 90% of it is DB-legal. | Our corpus dominates where it has evidence; metavgc fills thin species. | Holds (`tools/blend_priors.py`). |
| 2026-10-16 | Opponent builds come from set archetypes (`data/species_archetypes.json`, real sets grouped by item + nature) for species with >= 5 real sets; marginal blended priors otherwise. metavgc is not used for archetypes. | Marginal priors mixed regular Garchomp with Mega-Z Garchomp (metavgc pages are Z-blind). | Holds (`src/archetypes.py`, `src/opp_model.py::opponent_builds`). |

## 2. GA structure and selection

| Date | Decision | Rationale | Status today |
|---|---|---|---|
| 2026-10-10 | Never use random species swaps without constraints; the search needs structure. | Random-species genomes won 2-5% (N=210); the baseline was a strong local optimum. | Holds: species mutation keeps the species clause and roles; realism constraints below. |
| 2026-10-11 | Island model: independent populations, stagnation restart after 5 gens, diversity floor (inject 3 randoms below 15 unique species), immigration 20%, ring migration every 5 gens (serial only). | A single population collapsed to one Sand archetype in ~12 gens. | Holds: `src/ga/engine.py::run_islands` defaults (`stagnation_limit=5`, `diversity_floor=15`, `immigration_rate=0.20`, `migration_every=5`). |
| 2026-10-11 | Held-out eval is sacred: fitness uses `pool_split.json["train"]`, final eval uses `["holdout"]`; never mix. | Trustworthy final numbers. | Holds. Today train = 148 teams (30 held back as a validation slice, so 118 for fitness), holdout = 100. |
| 2026-10-14 | Parallel GA: one process per island, each with its own Showdown server (8000/8001/8002); no cross-process migration (`migration_every=999`). | One Python event loop maxed one core; 3 processes gave 2.78x throughput. | Holds (`run/ga_parallel.sh`, `run/ga_island.py`). Whether no-migration helps is unresolved (see open questions). |
| 2026-10-15 | Champion = training-best (`best_ever`), not validation-best. Both files are written (`ga_<run>_island_<X>.txt` primary, `..._train.txt`). | p3 held-out: train-selected beat val-selected by +6 to +10.6 pts; the 30-team val slice (sigma ~9 pts) overfits when picking max of ~1300 draws. | Holds in `src/ga/checkpoint.py::write_champions` (the comments in `src/ga/engine.py::_evolve_island` and `src/ga/pools.py` agree since 2026-11-18). |
| 2026-10-16 | `run_islands` is the only GA driver; the single-population `run_ga` was deleted. | It was an untested drifting copy. | Holds. |
| 2026-11-17 | Island specs: A = Umbreon locked in slot 0 + baseline seed, B = Umbreon locked, no seed, C = free. | Goal is the best team around Umbreon; C is the unconstrained ceiling reference. The lock was removed 2026-11-15 (pilot could not use Taunt/Yawn) and re-added 2026-11-17. | Holds in `run/ga_island.py::SPECS` and `run/ga_run.py::ISLANDS`; pinned by `tests/test_island_wiring.py`. |
| 2026-11-18 | Fitness-environment settings are a frozen `GAConfig` (`src/ga/config.py`) read from env once at import; per-run knobs stay `run_islands` kwargs. Outcomes are gathered in opponent order. | Makes settings explicit; completion-order collection had paired outcomes with the wrong opponent weights. | Holds; pinned by `tests/test_ga_golden.py`, `tests/test_ga_eval_order.py`, `tests/test_ga_config.py`. |

## 3. Fitness signal

| Date | Decision | Rationale | Status today |
|---|---|---|---|
| 2026-10-10 | Pilot for fitness: SimpleHeuristicsPlayer, not NeuralPlayer. | NeuralPlayer was 22 pts worse and exploitable (Modest Incineroar champions). | Superseded 2026-10-16. |
| 2026-10-13 | BC is not used as the fitness pilot. | BC v5 19.4% vs heuristic ~57-61% held-out; heuristic 3x better. | Holds. |
| 2026-10-14 | Team-realism constraint stack instead of fixing the pilot first: items from `data/meta_items.json` (else `CANONICAL_ITEMS`), forced Protect coverage, forced Fake Out/Follow Me/Rage Powder coverage, role-committed movesets (`_species_role`), moves sampled from top-8 priors. | Champions exploited pilot blind spots (Binding Band Umbreon, Heat Rock Garchomp, no Protect). | Holds (`src/ga/genome.py::_pick_item_for`, `_enforce_composition`, `_species_role`, `_random_mon`). Known gaps: type coverage, meta-species bias, synergy, natures. |
| 2026-10-14 | Soft constraints only (skip when the species cannot comply); hard rules only for legality. | Exploration must not die; every legal genome stays reachable. | Holds. Restated 2026-10-15 as the soft/hard boundary (`docs/design/structural-fitness.md`). |
| 2026-10-16 / 10-20 | Fitness environment: our side `VGCPilot` with `use_turn_sim` on, opponent `LadderOpponent` (heuristic + Protect/Fake Out at replay rates). `GA_PILOT=heuristic GA_OPP=heuristic` restores the old environment. | turn_sim gained +4.7 pts (n=17,941) vs heuristic and +4.5 pts (n=16,506) vs ladder, both p<0.001. Old scores are not comparable. | Holds (`GAConfig.fitness_pilot="vgc"`, `fitness_opp="ladder"`). |
| 2026-10-16 | Fitness is the meta-weighted win rate: each opponent team weighs the mean ladder usage of its six species (`data/species_ladder_usage.json`, unseen species 0.02). `None` results are dropped from the denominator, not counted as losses. | Rewards beating what the ladder actually plays; weights are mild (effective n 142/150). | Holds (`src/ga/fitness.py::weighted_fitness`, `src/meta_weights.py`). `GA_META_WEIGHTS=0` = plain win rate. |
| by 2026-10-13 (exact date unverified) | Early stop: a genome plays 50 battles first; below 15% the tail is skipped. | At n=50 the 95% CI is ~+/-10 pts; saves ~85% of wall time for bad genomes. | Holds (`GAConfig.early_stop_*`). With 50 opponents per genome (parallel islands) it never triggers. |
| 2026-11-14 | Parallel islands play 50 opponents per genome per generation; battles over 50 turns are dropped (`None`), and our `vgc` player forfeits after turn 50 (`src/player_factory.py::TimeoutPlayer`). | Protect/switch stalling made 60+ turn battles and ~1 h generations. | Holds. Unverified: the effect on fitness bias of dropping long battles. |

## 4. Pilots

| Date | Decision | Rationale | Status today |
|---|---|---|---|
| 2026-10-15 | DoublesPilot: vanilla heuristic decides, we re-allocate attacks of both slots jointly (`src/doubles_eval.py`). KO_BONUS = 1.0 (sweep plateau 2026-10-16), MIN_GAIN = 0.01. | +6.0 pts pooled over the heuristic (z ~3.8). | Holds (`src/doubles_eval.py::KO_BONUS`, `MIN_GAIN`). |
| 2026-10-16 | New VGC pilot plan (user): keep DoublesPilot until VGCPilot is ready; build order foundation -> Mega -> Protect -> Fake Out -> weather -> pivot -> switching; validate with scenario tests + action-rate counters, not per-feature win-rate A/B; opponent Speed = staged option B (`p_faster` from the prior mixture, observed order later); goal is ladder now, Bo3 later; OTS is used only when the opponent accepted it; never model Tera. | A real doubles pilot; per-feature A/B is too noisy (+/-5 pts per 500 battles). | Holds. Speed stage 2 and weather/pivot/switching features are not built. |
| 2026-10-16 | BattleMemory event source: override `_handle_battle_message` and feed every line before poke_env. | poke_env keeps no event log and gets Z-Mega forms wrong. | Holds (`src/battle_memory.py::BattleMemoryMixin`). |
| 2026-10-16 | Our Mega: on the first opportunity; with two candidates, Mega the larger offence gain (`mega_gain`). No "save the Mega" rule. | Replays: 79% Mega on first opportunity; win rate flat by timing; humans pick the larger offence gain 74% of the time. | Holds (`src/mega_model.py`). |
| 2026-10-16 / 10-20 | `use_turn_sim` on by default (`DOUBLES_TURN_SIM=0` turns it off); foe action odds on (`DOUBLES_FOE_ACTIONS`). | Paired results above. | Holds. |
| 2026-10-20 | Support values come from move data, not per species (Umbreon builds vary). Effects: foulplay, snarl, charm, helpinghand, taunt, heal. `SUPPORT_COST` 0.15 per pure-support action. | Slice 1 paired +4.6 pts (p=0.010) on Umbreon teams; plain-pool control +2.2 (p=0.124, no regression). | Holds. `DEFAULT_SUPPORT = "all"` since 2026-11-12 (commit 8b28efb). Toxic, Yawn, Will-O-Wisp, Wish, screens, Tailwind, redirection are NOT implemented. |
| 2026-10-20 | Multi-turn lookahead (`DOUBLES_LOOKAHEAD`) stays off. | Two paired runs pooled (~6000 pairs) neutral; +14% decision time; only matters vs Trick Room setters. | Holds (`src/support_value.py::DEFAULT_LOOKAHEAD = False`). |
| 2026-11-14 | `PASSIVE_COST` 0.15 -> 0.30 (cost of a Protect/switch in turn_sim, env `DOUBLES_PASSIVE_COST`). | Over-valued Protect/switch stalled battles. No paired run recorded. | Holds (`src/turn_sim_types.py::PASSIVE_COST`). |

## 5. BC track

| Date | Decision | Rationale | Status today |
|---|---|---|---|
| 2026-10-13 | Never overwrite `output/models/bc_best.pt` without a 5-seed held-out eval showing +3 pts. | A blind `cp` of v3 regressed the pilot (8.8% vs 19.4%). | Holds (policy). |
| 2026-10-13 | Select models on live win rate, not val_move_acc. | Higher imitation accuracy gave equal or worse play in 4 of 4 models. | Holds as rule; `src/bc_train.py` still saves on val_move_acc. |
| 2026-10-14 | No item/ability features in the encoder; stop BC-on-heuristic work; BC is kept only as a foundation for search/RL. | Items cut win rate 30% -> 23%; BC imitating the heuristic cannot beat it. | Holds. Tier 2 BC cleanup is still open (`docs/design/refactor-roadmap.md`). |
| 2026-10-13 | bf16 autocast not used for BC training. | No speedup at 1.5M params (launch-overhead bound). Re-test only for a much bigger model. | Holds. |

## 6. Open questions (current)

Old STATE.md section 8 questions, checked against later entries and code:

1. Should the GA use the BC pilot or the heuristic for fitness? RESOLVED 2026-10-16/20:
   neither; `VGCPilot` (turn_sim) vs `LadderOpponent`.
2. Should island migration preserve constraints? RESOLVED 2026-10-12: `_strip_species`
   (`src/ga/population.py`) replaces foreign locked species on entry; parallel runs do not
   migrate at all.
3. Is 57.9% BC move accuracy enough before a long GA run? RESOLVED 2026-10-13/14: moot, BC is
   at its ceiling and is not used for fitness.
4. Persistent server / cached accounts to speed up battles? OPEN, low priority. Every battle
   still creates two fresh accounts (`src/player_factory.py::make_player`, uuid names);
   throughput is bought with 3 parallel servers instead.

Still open (from later entries, verified not done in code):

5. Do the Umbreon-locked islands work with the current pilot? q5 (2026-11-15, old pilot
   path): A/B trained 85% -> held-out 47-49% vs baseline 53.6%; only C (62.4%) was usable.
   No long run in the VGCPilot/ladder environment has been reported since.
6. Does no-migration (parallel) help or hurt diversity/quality? Never isolated (2026-10-14).
7. Structural fitness (Path A): designed 2026-10-15, not implemented. Should it be built now
   that the pilot sees Protect/Fake Out/support moves?
8. Wire build/ability priors into the GA genome (`_random_mon` still uses 3 canonical spreads
   and a uniform ability)? See `docs/design/structural-fitness.md`.
9. Offensive type coverage, meta-species bias and team synergy constraints (2026-10-14
   known gaps): deferred design problems.
10. `PASSIVE_COST` (0.30) and `SUPPORT_COST`/`SUPPORT_HORIZON` were never swept in paired runs;
    a specials-off arm to split attack allocation from Protect/switch/Fake Out gains was never run.
11. Speed model stage 2 (reweight from observed move order) and Unburden / Quick Feet /
    Slow Start / Quick Claw / Custap / Lagging Tail: deferred (`src/speed_model.py` docstring).
12. Use OTS sets fully when the foe accepted Open Team Sheets: parsed (`BattleMemory.ots`),
    but `src/vgc_pilot.py::VGCPilot._foe_probs` only uses the sheet's moves for the foe
    Protect/Fake Out odds; builds, items and damage still come from priors/archetypes.

## Related docs

- [Structural fitness design](structural-fitness.md)
- [Refactor roadmap](refactor-roadmap.md)
- [Architecture](../reference/architecture.md)
- [Glossary](../reference/glossary.md)
- [History index](../history/README.md)
- [Operating policy](policy.md)
