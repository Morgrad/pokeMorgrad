# Structural Fitness — Design (Path A)

Status: design draft, 2026-10-15. Not yet implemented.
Related: STATE.md §5.14 (constraint stack), §5.20 (damage/smart_player).

## 1. Problem

The GA's fitness is `wins / battles_played`. `SimpleHeuristicsPlayer` — the
pilot those battles run against — cannot see EVs, items, abilities, or
team synergy. It only sees base stats, move base power, and type
effectiveness (verified 2026-10-15, `poke_env/baselines.py`).

Consequence: two genomes with identical win rates can differ dramatically
in team quality. p4's champions (2026-10-15) contained:

- Water Absorb Politoed on a Ninetales-Drought team (ability anti-synergy)
- 32 ATK EVs on Modest Gengar (EV-role anti-synergy)
- Roar + Body Slam on Modest Typhlosion (move-role anti-synergy)
- Rocky Helmet on special-attacker Clawitzer (item-role anti-synergy)

These flaws are legal, and the pilot doesn't punish them, so the GA has no
signal to avoid them. Structural fitness adds that signal.

## 2. Design philosophy

1. **Additive, not replacing.** Win rate stays the primary signal. Structural
   score is a bounded bonus/penalty, not a replacement metric.

2. **Soft penalties, not hard rejections.** The existing legality gate
   (`filter_legal_genomes`) handles illegal genomes. Structural fitness
   handles *bad* genomes and must not eliminate exploration. A Gengar with
   32 ATK EVs should score lower, not be rejected.

3. **Every sub-score has a physical meaning.** No black boxes. Each score
   is explainable in one sentence. When a genome loses fitness, we must be
   able to say why.

4. **Tunable weights.** We don't know the right mix a priori. Weights are
   constants at the top of the module and can be A/B'd.

5. **Testable in isolation.** Each sub-score is a pure function `genome -> [0, 1]`
   with unit tests. Composite is a weighted mean.

## 3. Sub-scores

Six, all normalized to [0, 1]. Weights sum to 1.0.

### 3.1 EV-role consistency (weight 0.25)

For each mon: does the EV spread match the species's committed role?

- **physical**: `atk EVs >= 16`, `spa EVs <= 8`
- **special**:  `spa EVs >= 16`, `atk EVs <= 8`
- **support**:  `hp + def + spd EVs >= 24`, offensive EVs <= 8

Penalty layers:
- Also check nature: physical prefers Jolly/Adamant, special prefers
  Modest/Timid, support prefers Calm/Bold/Impish/Careful
- Also check: no stat has EVs > 32 (Champions cap)

Score = fraction of mons that pass, averaged across the team.

*Fixes:* Gengar 32-ATK, Modest Gengar-type mismatches.

### 3.2 Ability consistency (weight 0.20)

For each mon: does the ability make sense in the team context?

Baseline rules:
- Ability is legal for the species (already enforced by legality gate)
- Weather teams: if team has Drizzle/rain, mons with abilities that benefit
  from rain (Swift Swim, Rain Dish, Hydration, Dry Skin) get bonus;
  Fire-type abilities on a rain team get penalty
- Ability-item prerequisite: Poison Heal requires Toxic Orb; Unburden
  requires a consumable item (Focus Sash, White Herb, Lum Berry, Sitrus)
- No "useless" abilities: e.g. Pickup on a team with no berries,
  Klutz with a held item

Score = fraction of mons that pass, averaged.

*Fixes:* Water Absorb Politoed on a sun team.

### 3.3 Move-role consistency (weight 0.20)

For each mon: do the 4 moves match the committed role?

- **physical**: at least 2 damaging physical moves
- **special**: at least 2 damaging special moves
- **support**: at least 2 status moves OR 2 moves with side effects
  (Fake Out, Follow Me, Helping Hand, Protect, etc.)

Penalty layers:
- No contradictory setup: Swords Dance + Nasty Plot on same mon
- No contradictory speed control: Tailwind + Trick Room on same team
- No self-defeating moves: Trick Room on a team whose slowest mon is fast

Score = fraction of mons that pass, averaged.

*Fixes:* Roar on Modest Typhlosion, Body Slam on Modest Typhlosion.

### 3.4 Item synergy (weight 0.15)

For each mon: is the held item appropriate for the role?

- Physical attacker: Life Orb, Choice Band, Choice Scarf, Focus Sash,
  Assault Vest (rare), Sitrus Berry
- Special attacker: Life Orb, Choice Specs, Choice Scarf, Focus Sash,
  Assault Vest, Sitrus Berry
- Support: Leftovers, Sitrus Berry, Rocky Helmet, Assault Vest,
  Covert Cloak, Covert Cloak-like

Penalty layers:
- No duplicate items (already enforced by item clause legality)
- No anti-synergy: Assault Vest + status move (illegal in Showdown anyway);
  Choice item + Protect / Fake Out (mandatory-lock trap); Rocky Helmet
  on an offensive special attacker

Score = fraction of mons that pass, averaged.

*Fixes:* Rocky Helmet Clawitzer.

### 3.5 Coverage score (weight 0.10)

Compute the set of offensive types the team can hit super-effectively
with at least one move of base power ≥ 70.

| distinct types | score |
|----------------|-------|
| 0-2 | 0.2 |
| 3-4 | 0.5 |
| 5-6 | 0.75 |
| 7+  | 1.0 |

Additional: check that at least 3 of the top-5 meta defensive typings
(Fairy, Steel, Water, Dark, Ghost — heuristic; adjust from
regmc_db / pool stats) are covered by at least one mon.

Score = min(type_count_score, meta_coverage_score).

### 3.6 Anti-synergy detection (weight 0.10)

Team-level patterns that should never appear. Each instance is a flat
-0.2 penalty from a starting score of 1.0:

- Swords Dance + Trick Room on same mon
- Two mons with Trick Room
- Tailwind + Trick Room on the same team
- More than one mon with Fake Out (some value, but rarely more than one)
- No Protect on any mon (should already be prevented by §5.14, verify)
- Zero spread moves on a doubles team

Score = max(0, 1.0 - 0.2 * count).

## 4. Composite

    structural_score = (
        0.25 * ev_consistency
      + 0.20 * ability_consistency
      + 0.20 * move_consistency
      + 0.15 * item_synergy
      + 0.10 * coverage
      + 0.10 * anti_synergy
    )

    fitness = win_rate + ALPHA * (structural_score - 0.5)

Where `ALPHA` is a module constant, initial value 0.15. Range:
- structural_score = 1.0 → fitness = win_rate + 0.075
- structural_score = 0.5 → fitness = win_rate (no change)
- structural_score = 0.0 → fitness = win_rate - 0.075

## 5. Testing

### Unit tests (`tools/test_structural.py`)
- For each sub-score: 3 known-good genomes (expect ≥ 0.9),
  3 known-bad (expect ≤ 0.1), 3 mixed (expect 0.3-0.7).
- Test inputs are hand-crafted or drawn from VGCPastes + p4 champions.

### Integration tests
- Score p4's champions. Expected: A_train and C_train score lower than the
  average VGCPastes training team (they have the flaws we're penalizing).
- Score the baseline team. Expected: high (it's well-built).

### Regression test
- Run one GA generation with `ALPHA=0` and `ALPHA=0.15`. Confirm:
  - `ALPHA=0` reproduces previous win rates exactly
  - `ALPHA=0.15` shifts selection pressure without collapsing win rate

### A/B calibration
- Run 15-min GA smokes with `ALPHA ∈ {0, 0.10, 0.15, 0.25}`. Compare:
  - Champion structural_score
  - Champion win rate vs real-EV holdout
- Pick `ALPHA` that maximizes structural quality without losing > 2%
  win rate.

## 6. What this does NOT fix

- **Team-level synergy** (Rillaboom + Grassy Glide is fine, Rillaboom +
  Grassy Glide + no other Grass-type users is under-explored). This is
  a Path D (LLM critic) problem.
- **Meta read** ("does this team counter the current top archetype?").
  Requires pool statistics we don't compute yet.
- **Pilot quality.** The GA still pilots against a heuristic. Path A
  changes what the GA *prefers*, not how its battles are played.

## 7. Implementation plan

Day 1 (this doc): design + review.
Day 2: `src/structural_fitness.py` with all 6 sub-scores + unit tests.
Day 3: integrate into `evaluate`, run A/B calibration smokes.
Day 4: pick `ALPHA`, launch p5 with structural fitness on real-EV pool.

## 8. Open questions (need decisions before Day 2)

1. **Hard vs soft on contradictory setup moves?** Swords Dance + Nasty Plot
   on the same mon is genuinely useless. Hard reject or soft penalty?
   Leaning soft (reject eliminates exploration of the mutation space).

2. **What is "support" role?** §5.14 defines it via base stats
   (peak < 80). Is that stable enough to key EV-role consistency on?
   Alternative: define support by move pool (>= 2 status moves).

3. **Coverage top-5 defensive typings** — hardcoded or computed from
   `regmc_db` / pool stats? Leaning hardcoded as v1 constant, revisit
   after one calibration run.

4. **Where do weights live?** Module constants are simple but require a
   code edit to tune. Env vars are flexible but harder to reason about.
   Leaning module constants for v1, since we'll A/B via git branches.
