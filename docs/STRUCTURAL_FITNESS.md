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

## 9. Meta-data integration (open question, 2026-10-15)

The Champions UI exposes per-species aggregate stats: ability distribution,
move frequency, item frequency, EV-spread distribution, nature distribution,
teammate co-occurrence. This data is a candidate prior source.

Design decision: **soft priors, never hard filters.**

Rationale: hardcoding popular choices turns the GA into a meta sampler.
The GA's value is finding teams that beat the meta, including counter-meta
picks. Prior-driven initial populations + soft-probability mutations help
convergence; hard constraints kill exploration.

Proposed soft-prior additions (v2, after Path A):
- `species_ability_priors.json` — ability frequencies by species
- `species_teammate_priors.json` — top-N teammates by co-occurrence
- `species_ev_priors.json` — real spread distributions (already proposed
  2026-10-15, still not built)

Test: p5-A (no priors) vs p5-B (soft priors), same pool, same holdout.
Success = B's champion has higher structural score AND equal-or-better
win rate. Failure = B's win rate drops (priors over-constrained search).

Scraping status: unknown source. The UI shows data but scraping requires
either an in-game capture pipeline or locating the public API (if one
exists). Deferred pending Path A completion.

## 10. Vocabulary expansion (added 2026-10-15)

Fitness signal is necessary but not sufficient. The GA also needs raw
material to search over. Today the "vocabulary" is artificially narrow:

| Dimension | Current vocab | Real-world vocab | Gap |
|-----------|---------------|------------------|-----|
| EV spreads | 3 canonical (one per role) | ~15-25 per species | huge |
| Natures | 1 per role | ~5-8 per species | moderate |
| Moves | top-8 role-filtered | full pool + tech | moderate |
| Items | meta_items.json weighted | already good | low |
| Abilities | uniform random.choice(legal) | ~99/1 split | huge |

Example (Garchomp, from Champions UI aggregate data):
- Rough Skin 99.2%, Sand Veil 0.8%. Our code: 50/50 coin.
- 5 real spreads, top ones at 28%, 23.5%, 5.7%. Our code: 1 spread.
- Natures Timid 24.8%, Adamant 24%, Jolly 23.8%. Our code: Jolly only.

**Vocabulary expansion = build priors from VGCPastes data we already have.**

### Four new priors (Phase 1)

1. `species_ev_priors.json` — top-N spreads per species, weighted by
   frequency. Biggest single win.
2. `species_ability_priors.json` — abilities weighted by usage.
3. `species_nature_priors.json` — natures weighted by usage.
4. Extended move pool — top-16 (currently top-8).

### Why vocabulary alone doesn't help

If the pilot can't distinguish a 2/32/0/0/0/32 Garchomp from a
0/32/2/0/0/32 Garchomp (both hit the same hard with the heuristic's
`base_stats` estimation), then adding more spreads is just noise. The
GA has more to search over but no signal to prefer one.

**Vocabulary expansion and Path A structural fitness are complements.**

### Why vocabulary + signal does help

Given a fitness signal that rewards coherent builds, the GA will:
- Prefer species-canonical ability (Rough Skin over Sand Veil)
- Prefer spreads that score well in the structural check
- Explore off-canonical spreads when they win more

Synergies emerge when the pilot can distinguish them. Drizzle + Swift
Swim stops being a coin flip when ability_consistency rewards the pair.

### Sequencing

1. Build `species_ev_priors.json` (30 min, from existing data)
2. Build `species_ability_priors.json` (30 min)
3. Build `species_nature_priors.json` (15 min)
4. Wire into `_random_mon` + `mutate_evs` + `mutate_ability` (1 day)
5. Path A structural fitness (already designed)
6. p5-A vs p5-B smoke test to validate

Total ~3-4 days of work.

## 11. Mega-form role divergence (2026-10-15)

Species name alone is not sufficient to classify a mon's role when the
species has mega forms with different stat distributions.

Example: Garchomp's top spread in species_build_priors.json is
2 HP / 32 SpA / 32 Spe Modest (n=16) — that's Mega Garchomp Z, a
special attacker. Regular Garchomp is physical. Aggregating by species
mixes the two.

Fix (deferred to 2026-10-16):
1. Rebuild priors keyed by (species, item) with species-only fallback.
2. Patch _species_role to use the mega form's baseStats when the held
   item matches a mega stone.
3. Patch _random_mon to look up (species, item) first.

The three changes go together.

## 12. Soft vs hard boundary (2026-10-15)

Design principle restated after mega-form discussion: **as little
hardcoding as possible.** The GA's value is finding what beats the meta,
which requires that every legal genome remains reachable.

### HARD (unavoidable — already enforced by legality gate)

- Species exists in regmc_db
- Item exists, species can hold it
- Move exists, species can learn it
- Species clause, item clause, format rules
- Champions EV cap (0-32 per stat, total budget)

No new hard constraints are added by structural fitness. Ever.

### SOFT (priors, sampled and mutate-able)

- Which build to sample per (species, item): sampled from
  species_build_priors.json, weighted, capped at 25% per spread
- Which ability to sample: sampled from species_ability_priors.json
- Which moves to sample: sampled from species_move_priors.json (top-8)
- Which item to sample: sampled from meta_items.json
- Role of a genome: **inferred from the sampled build, not assigned by
  species.** Two Garchomp genomes can have different roles if their
  items/builds differ.

Mutation can break any of these pairings freely:
- `mutate_item` changes Garchompite Z → Rocky Helmet. Build becomes
  incoherent. Structural fitness penalizes. GA decides whether to
  revert, fix the spread, or push through.
- `mutate_evs` can flip a spread from physical to special. Role of the
  genome flips with it for downstream checks.
- `mutate_ability` can swap Rough Skin for Sand Veil. Ability prior
  penalty applies but the genome is still legal and playable.

### SOFT PENALTY (structural fitness — never reject)

- Item-build coherence
- Ability-consistency with team context
- Role-committed movesets (already in constraint stack as a soft rule)
- Coverage, anti-synergy, EV-role match

Every one of these is a weight in the fitness composite. None of them
prevents a genome from existing, playing, or reproducing. If a genome
with an unusual pairing wins enough battles to offset the penalties,
it survives — which is exactly the discovery mechanism we want.

### What this rules out (design decisions)

- **No item-aware `_species_role`.** Role stays species-based for the
  constraint stack's move filtering. Item-keyed roles only affect prior
  sampling, not move pool filtering.
- **No "Garchompite Z requires special build."** If the sampled build
  is special, the genome is special. If mutation flips the spread to
  physical, the pairing becomes incoherent and gets penalized, but the
  genome still plays.
- **No "Politoed requires Drizzle."** Drizzle is 99% of Politoed
  abilities in the data. Prior samples it 99% of the time. Mutation can
  still pick Water Absorb; the ability-consistency penalty applies.
- **No hidden ceilings.** If the meta shifts and off-meta builds
  become good, the GA can find them because mutation can produce them.

### The Garchomp example, end to end

1. Prior sampled for `Garchomp @ Garchompite Z` → mostly Modest
   2/32/32. Genome created with special role.
2. `mutate_item` swaps to `Garchompite` (regular Mega Garchomp X) →
   physical build is now the prior for that item. Structural fitness
   soft-penalizes incoherence if spread wasn't updated.
3. `mutate_evs` on the physical build finds a Jolly 2/32/32 spread that
   wins more battles against the real-EV pool. Genome survives.
4. `mutate_item` swaps back to Rocky Helmet → regular Garchomp,
   physical. Still coherent. Still playable.
5. The GA now knows all three variants; fitness decides which stays.

This is the design. Not "correct because we hardcoded it," but "correct
because it wins."

## 13. External data sources (2026-10-15)

Robots.txt audit:

| Source | HTML scrape | Notes |
|--------|-------------|-------|
| pokebase.app | allowed | API disallowed. Same pattern as MetaVGC. |
| pokemon-zone.com | allowed | API + TCG disallowed. Tournament pages OK. |
| pokechamdb.com | **disallowed** | Explicit AI-crawler blocks (GPTBot, ClaudeBot, etc.). Respect the intent, do not scrape. |
| metavgc.com | allowed at HTML, API disallowed | Champions UI data |
| limitlessvgc.com | allowed | Already the primary tournament source |
| VGCPastes Google Sheet | public | Primary prior source |

Plan:
- Use pokebase.app as a cross-check for our VGCPastes-based priors (spot verification)
- Use pokemon-zone.com for tournament-level win-rate weighting (deferred until p5 results)
- Never scrape pokechamdb.com given its clear AI-crawler stance

Primary data stays Limitless + VGCPastes. External sources are supplements,
not dependencies.

## 14. Prior cross-validation (2026-10-15)

Compared our VGCPastes-derived Garchomp priors against pokebase.app's
Champions Garchomp page.

Match:
- Abilities: Rough Skin 98.9% (us) vs 97% (them)
- Top spread: 2 HP / 32 SpA / 32 Spe (both)
- Natures: Modest/Adamant/Jolly/Timid (both, same set)
- Items: Garchompite Z > Choice Scarf > Life Orb (both, same order)

Diverge:
- Moves: Pokebase has Power Gem at 52% and Dragon Claw at 39%; ours has
  Dragon Pulse rank 3 and Power Gem rank 6.

Diagnosis: source-population effect. VGCPastes = tournament top-cuts
(Dragon Pulse for mirror/Dragon matchups). Pokebase = ladder/ranked
(Power Gem for Thundurus/Flying). Both are real; the priors match the
population our GA plays against (tournament teams).

Action: keep current priors. Mutation can reach rank-6 moves.

Revisit if: GA produces champions that fail specifically because of a
missing move — then scrape pokebase for move rankings as a supplement.
