# Structural fitness (Path A) - design

Design for adding a "is this a coherent VGC team" score to the GA fitness, next to the win
rate. Written 2026-10-15, refreshed against the code 2026-11-18. Read it before touching GA
fitness or genome sampling; the prior/vocabulary side and the soft/hard boundary are in
`structural-fitness-priors.md`.

Last verified against code: 2026-11-18

## 0. Status (2026-11-18)

**Not implemented.** There is no `src/structural_fitness.py`, no `ALPHA` constant and no
structural term anywhere in `src/ga/`. GA fitness today is only
`src/ga/fitness.py::weighted_fitness`: the meta-weighted win rate of the genome over the
battles that returned a result (`None` dropped), each opponent team weighted by the mean
ladder usage of its six species (`src/meta_weights.py`, unseen species 0.02).

What changed since this design was written (it assumed the old fitness environment):
- The fitness pilot is no longer `SimpleHeuristicsPlayer`. Since 2026-10-16/20 our side is
  `VGCPilot` (turn_sim: move order, KO odds, Protect, Fake Out, switches, Mega, support moves
  Foul Play / Snarl / Charm / Helping Hand / Taunt / heals) and the opponent is
  `LadderOpponent` (heuristic + Protect/Fake Out at replay rates). Some anti-synergies the
  design targets (no Protect, Choice item + Protect, useless support move) can now cost
  battles directly, so part of the motivation is weaker. Items, abilities (beyond immunity
  odds for foes), weather synergy and EV-role fit are still mostly invisible to fitness.
- The team-realism constraint stack (2026-10-14) already covers part of section 3:
  items from `data/meta_items.json`, forced Protect and Fake Out/redirection coverage,
  role-committed movesets (`src/ga/genome.py::_species_role`, `_preferred_pool`), moves from
  top-8 priors. These are soft constraints applied at build time, not fitness terms.
- q5 (2026-11-15, old pilot path) champions: Umbreon islands trained 85% -> held-out 47-49%,
  free island 62.4% vs baseline 53.6%. Overfitting to the pilot is still the core problem.

## 1. Problem

The GA fitness is a win rate. When the pilot cannot see a team flaw, two genomes with the same
win rate can differ a lot in quality. p4 champions (2026-10-15, heuristic pilot) contained:
- Water Absorb Politoed on a Ninetales-Drought team (ability anti-synergy)
- 32 Atk EVs on Modest Gengar (EV-role anti-synergy)
- Roar + Body Slam on Modest Typhlosion (move-role anti-synergy)
- Rocky Helmet on special attacker Clawitzer (item-role anti-synergy)

These are legal, the pilot does not punish them, so the GA has no signal to avoid them.
Structural fitness adds that signal.

## 2. Design philosophy

1. **Additive, not replacing.** Win rate stays primary; the structural score is a bounded
   bonus/penalty.
2. **Soft penalties, never hard rejections.** Legality stays the only hard gate
   (`src/ga/legality.py::filter_legal_genomes`, Showdown validator). A Gengar with 32 Atk EVs
   scores lower, it is not rejected.
3. **Every sub-score has a physical meaning**, explainable in one sentence.
4. **Tunable weights** as module constants, A/B-able.
5. **Testable in isolation:** each sub-score is a pure function `genome -> [0, 1]` with unit
   tests; the composite is a weighted mean.

## 3. Sub-scores (all in [0, 1], weights sum to 1.0)

**3.1 EV-role consistency (0.25).** Per mon, does the spread match the committed role?
physical: Atk EVs >= 16 and SpA <= 8; special: SpA >= 16 and Atk <= 8; support:
HP + Def + SpD >= 24 and offensive EVs <= 8. Also nature: physical Jolly/Adamant, special
Modest/Timid, support Calm/Bold/Impish/Careful; no stat above 32. Score = fraction of mons
that pass. Fixes: 32-Atk Gengar.
Note: GA-built mons always pass today (`_random_mon` uses fixed role spreads); only
`mutate_evs` (random 66 points in 32-point chunks) and `mutate_nature` (any nature) break it.

**3.2 Ability consistency (0.20).** Weather teams: rain abusers (Swift Swim, Rain Dish,
Hydration, Dry Skin) get a bonus with Drizzle, fire abilities on rain a penalty; ability-item
prerequisites (Poison Heal needs Toxic Orb, Unburden needs a consumable: Focus Sash, White
Herb, Lum, Sitrus); no useless abilities (Pickup without berries, Klutz with an item).
Fixes: Water Absorb Politoed on sun.

**3.3 Move-role consistency (0.20).** physical: >= 2 damaging physical moves; special:
>= 2 damaging special moves; support: >= 2 status or side-effect moves (Fake Out, Follow Me,
Helping Hand, Protect...). Penalties: Swords Dance + Nasty Plot on one mon, Tailwind + Trick
Room on one team, Trick Room on a team whose slowest mon is fast. Fixes: Roar / Body Slam on
Modest Typhlosion.

**3.4 Item synergy (0.15).** Physical: Life Orb, Choice Band, Choice Scarf, Focus Sash,
Assault Vest (rare), Sitrus. Special: Life Orb, Choice Specs, Choice Scarf, Focus Sash,
Assault Vest, Sitrus. Support: Leftovers, Sitrus, Rocky Helmet, Assault Vest, Covert Cloak.
Penalties: Choice item + Protect / Fake Out, Rocky Helmet on an offensive special attacker
(Assault Vest + status move is already illegal in Showdown; duplicates are blocked by the item
clause). Fixes: Rocky Helmet Clawitzer.

**3.5 Coverage (0.10).** Distinct types the team hits super-effectively with a move of base
power >= 70: 0-2 -> 0.2, 3-4 -> 0.5, 5-6 -> 0.75, 7+ -> 1.0. Also require that >= 3 of the
top-5 meta defensive typings (Fairy, Steel, Water, Dark, Ghost as a heuristic; better computed
from the pool) are hit by some mon. Score = min of the two. This is the "offensive type
coverage" gap noted in the 2026-10-14 constraint-stack entry (champions with zero
Water/Electric/Ice/Bug moves).

**3.6 Anti-synergy (0.10).** Start at 1.0, -0.2 per instance: Swords Dance + Trick Room on
one mon; two Trick Room users; Tailwind + Trick Room on one team; more than one Fake Out user;
no Protect anywhere (already prevented by `_enforce_composition`); zero spread moves.
Score = max(0, 1 - 0.2 * count).

## 4. Composite

    structural_score = (0.25 * ev_consistency + 0.20 * ability_consistency
                        + 0.20 * move_consistency + 0.15 * item_synergy
                        + 0.10 * coverage + 0.10 * anti_synergy)
    fitness = win_rate + ALPHA * (structural_score - 0.5)

`ALPHA` initial 0.15, so the term ranges -0.075 .. +0.075 around the win rate (0.5 = no
change).

Where it would plug in today (proposal, not code): after
`src/ga/fitness.py::weighted_fitness` inside `src/ga/evaluator.py::Evaluator._fitness`, or as
a separate term added in `Evaluator.evaluate`. It must NOT be applied in
`Evaluator.eval_on_subset` or `src/eval.py` if those numbers are reported as win rates. Any
change to fitness changes GA behavior, so `tests/test_ga_golden.py` will fail by design: run
it with `ALPHA = 0` first (must stay byte-identical), then regenerate the fixture for the
`ALPHA > 0` change.

## 5. Testing plan

- Unit (`tests/test_structural.py`, not written): per sub-score 3 known-good genomes
  (>= 0.9), 3 known-bad (<= 0.1), 3 mixed (0.3-0.7), from VGCPastes teams and old champions.
- Integration: old champions should score below the average VGCPastes training team; the
  baseline team should score high.
- Regression: one GA generation with `ALPHA = 0` reproduces previous outputs exactly (golden
  test); `ALPHA = 0.15` shifts selection without collapsing win rate.
- Calibration: short GA smokes with `ALPHA` in {0, 0.10, 0.15, 0.25}; compare champion
  structural score and held-out win rate; pick the largest `ALPHA` that costs < 2 pts of
  held-out win rate. Needs the user's go-ahead (GA runs).

## 6. What this does not fix

- Deep team synergy (e.g. Grassy Glide without other Grass users) - a "Path D" (critic)
  problem.
- Meta read ("does this team counter the top archetype?") - needs pool statistics.
- Pilot quality - Path A changes what the GA prefers, not how battles are played.

## 7. Open questions

1. Hard vs soft on contradictory setup (Swords Dance + Nasty Plot)? Leaning soft
   (consistent with the soft/hard boundary: only legality is hard).
2. What is "support"? Today `_species_role` says support when max(Atk, SpA) < 80 base. Keep,
   or define by move pool (>= 2 status moves)?
3. Top-5 defensive typings: hard-coded v1 or computed from `regmc_db` / pool usage?
4. Weights as module constants (leaning yes for v1) or env vars?
5. New since 2026-10-15: is Path A still worth it with `VGCPilot` as the fitness pilot, or
   should effort go into making the pilot see items/abilities? Decide after a long GA run in
   the current environment shows which flaws its champions still have.

## Related docs

- [Structural fitness, part 2: priors, vocabulary, soft/hard boundary](structural-fitness-priors.md)
- [Design decisions](decisions.md)
- [GA subsystem](../subsystems/ga.md)
- [GA genome](../subsystems/ga-genome.md)
- [Pilots](../subsystems/pilots.md)
