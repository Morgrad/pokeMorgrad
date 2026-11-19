# Structural fitness, part 2: priors, vocabulary and the soft/hard boundary

Part 2 of the Path A design (old `docs/STRUCTURAL_FITNESS.md` sections 9-15, 2026-10-15),
refreshed against the code 2026-11-18: which priors exist, who reads them, the GA's
genome "vocabulary" today, and the soft/hard design rule. Read it before changing how
`src/ga/genome.py` samples sets or how priors are built. Part 1 (sub-scores, composite) is
`structural-fitness.md`.

Last verified against code: 2026-11-18

## 1. Status of the prior files (2026-11-18)

| File | Built by | Keys today | Read by |
|---|---|---|---|
| `data/species_move_priors.json` | `tools/build_species_priors.py` (ladder replays, `training_data.jsonl`) | 191 species, `[{move, count}]` | GA `src/ga/genome.py::move_priors_for` (top 8) and the BC move mask (`src/bc_train.py`, `src/bc_player.py`) |
| `data/species_build_priors.json` | `tools/build_ev_priors.py` + `tools/blend_priors.py` (corpus + metavgc) | 540 keys: species and `"Species @ Item"` | opponent model only (`src/opp_model.py`) |
| `data/species_ability_priors.json` | same | 379 species | opponent model only |
| `data/species_item_priors.json`, `data/species_move_usage.json` | `tools/blend_priors.py` | per species | nothing in `src/` reads them (grep, 2026-11-18) |
| `data/species_archetypes.json` | `tools/build_archetypes.py` | 145 species | `src/archetypes.py` -> `src/opp_model.py` (opponent sets) |
| `data/meta_items.json` | regional teams | 94 species | GA `_pick_item_for` |

Consequences:
- **The GA genome does not use the build or ability priors.** `src/ga/genome.py::_random_mon`
  still gives every mon one of 3 fixed role spreads (physical `hp 2 / atk 32 / spe 32` Jolly,
  special `hp 2 / spa 32 / spe 32` Modest, support `hp 32 / def 20 / spd 14` Calm) and a
  uniform `random.choice` over legal abilities. `mutate_evs` scatters 66 points in 32-point
  chunks; `mutate_nature` picks any nature; `mutate_ability` any other legal ability;
  `mutate_item` any legal unused item (no meta bias).
- **Section 7 (prior source mismatch) is still open for the GA.** The tracked
  `species_move_priors.json` was last committed 2026-10-12 and is ladder-sourced.
  `tools/build_move_priors.py` (tournament source, `data/scraped/vgcpastes/teams`) exists but
  its output is not the tracked file. Running it would also replace the BC move mask, because
  both read the same file (the 2026-10-16 blended-priors work deliberately left it alone).
  `tools/build_move_priors.py` also hard-codes `Path.home() / "pokeMorgrad"` instead of
  `src/paths.py`.

## 2. Meta-data integration (2026-10-15)

Per-species aggregates (ability, move, item, spread, nature distributions, teammate
co-occurrence) are candidate priors. Decision: **soft priors, never hard filters** - hard
popular-choice rules would turn the GA into a meta sampler, while its value is finding teams
that beat the meta, including counter-meta picks. Prior-driven initial populations and
soft-probability mutations help convergence; hard constraints kill exploration.

Proposed after Path A: ability priors (built since, opponent side only), teammate priors
(`species_teammate_priors.json`, NOT built), real spread priors (built as the joint
EV+nature `species_build_priors.json`). Planned test: p5-A (no priors) vs p5-B (soft
priors), same pool and holdout; success = B's champion has a higher structural score and an
equal or better win rate. Never run.

## 3. Vocabulary expansion (2026-10-15)

The fitness signal is necessary but not sufficient; the GA also needs raw material. The gap
as measured then, still true for GA genomes today:

| Dimension | GA vocabulary | Real-world vocabulary | Gap |
|---|---|---|---|
| EV spreads | 3 canonical (one per role) | ~15-25 per species | huge |
| Natures | 1 per role | ~5-8 per species | moderate |
| Moves | top-8 priors, role-filtered | full pool + tech | moderate |
| Items | `meta_items.json` weighted | already good | low |
| Abilities | uniform over legal | often ~99/1 split | huge |

Example (Garchomp): Rough Skin ~99%, Sand Veil ~1% (GA: 50/50); 5 real spreads (GA: 1);
natures Timid / Adamant / Jolly about a quarter each (GA: Jolly only).

Why vocabulary alone does not help: if the pilot cannot tell two spreads apart, more spreads
are only noise. Vocabulary and a fitness signal that rewards coherent builds are complements.
Original sequence (not done for the GA): build spread / ability / nature priors -> wire them
into `_random_mon`, `mutate_evs`, `mutate_ability` -> Path A -> p5-A vs p5-B test.

## 4. Mega-form role divergence (2026-10-15)

Species alone does not fix a role when Mega forms differ: Garchomp's top spread
(2 HP / 32 SpA / 32 Spe Modest) is Mega Garchomp Z (special); regular Garchomp is physical.
Done since (opponent side, 2026-10-16): build priors keyed by `"Species @ Item"` with a
species fallback; set archetypes per (item, nature); `Build.form` / `form_stats` and Mega-aware
Speed in `src/speed_model.py`. Not done for the GA (by design, section 5): `_species_role`
uses the species' own base stats; `_random_mon` does not look up `(species, item)` priors.

## 5. Soft vs hard boundary (2026-10-15, still the rule)

As little hard-coding as possible; every legal genome must stay reachable.

HARD (legality only, enforced by the Showdown validator): species exists in `regmc_db`;
item exists and the species can hold it; move learnable; species clause, item clause, format
rules; Champions EV cap (0-32 per stat, 66 total). Structural fitness adds no hard rules.

SOFT (priors, sampled and mutable): which build per (species, item); which ability; which
moves (top-8 priors); which item (`meta_items.json`). A genome's role should be inferred from
its sampled build, not assigned by species. Mutation may break any pairing freely
(`mutate_item` Garchompite Z -> Rocky Helmet; `mutate_evs` physical -> special;
`mutate_ability` Rough Skin -> Sand Veil); structural fitness penalizes, the GA decides.

SOFT PENALTY (structural fitness, never reject): item-build coherence, ability vs team
context, role-committed movesets, coverage, anti-synergy, EV-role match.

Ruled out: no item-aware `_species_role` (role stays species-based for move filtering;
item-keyed roles only affect prior sampling); no "Garchompite Z requires a special build"; no
"Politoed requires Drizzle" (the prior samples it ~99%); no hidden ceilings. Garchomp end to
end: sample `Garchomp @ Garchompite Z` -> mostly Modest special; `mutate_item` to Garchompite
-> physical prior, incoherent spread is penalized; `mutate_evs` finds a Jolly physical spread
that wins -> survives; fitness decides which variant stays. "Correct because it wins, not
because we hard-coded it."

## 6. External data sources (robots.txt audit, 2026-10-15/16)

| Source | Use |
|---|---|
| limitlessvgc.com | primary tournament source (team lists; EVs not published) |
| VGCPastes Google Sheet + pokepast.es `/raw` | primary prior source (real EVs); read hyperlinks via XLSX + openpyxl |
| metavgc.com HTML `/pokemon/<slug>` | per-species usage tables, blended at N0 = 10; Z-blind, 12 regional forms distrusted |
| pokebase.app | HTML only for spot checks; `/api` disallowed, not scraped |
| pokemon-zone.com | Cloudflare challenge (403), not scraped |
| pokechamdb.com | explicit AI-crawler block: never scrape |

## 7. Prior cross-validation and source mismatch (2026-10-15)

Garchomp, ours vs pokebase.app: abilities (Rough Skin 98.9% vs 97%), top spread
(2 HP / 32 SpA / 32 Spe), natures and item order match. Moves diverge (pokebase Power Gem 52%,
Dragon Claw 39%; ours Dragon Pulse rank 3, Power Gem rank 6): tournament (VGCPastes) vs ladder
populations; both real. Decision then: keep priors; mutation can reach rank-6 moves; revisit if
champions fail for lack of a specific move.

Source mismatch found the same day: move priors from ~5000 ladder replays, build/ability
priors from tournament teams; 145 species had build+ability priors but no move priors and
fell back to role-random moves (the Copycat/Rest failure mode). Planned fix: rebuild move
priors from tournament teams (`tools/build_move_priors.py`). Status: see section 1 - script
exists, tracked file unchanged, BC mask coupling unresolved.

## Related docs

- [Structural fitness, part 1](structural-fitness.md)
- [Design decisions](decisions.md)
- [GA genome](../subsystems/ga-genome.md)
- [Damage, opponent model](../subsystems/damage.md)
- [Data pipeline runbook](../runbooks/data-pipeline.md)
- [Data files](../reference/data-files.md)
