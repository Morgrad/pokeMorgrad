# 2026-10-11 — 10-hour island GA run

## Result (held-out 100 teams, 3 seeds, N=300 each)
- baseline:              175/300 = 58.3%
- ga_run1_island_A:      222/300 = 74.0%
- ga_run1_island_B:      230/300 = 76.7%
- ga_run1_island_C:      233/300 = 77.7%
- ga_run2_island_A:      236/300 = 78.7%  (best)
- ga_run2_island_B:      224/300 = 74.7%
- ga_run2_island_C:      222/300 = 74.0%

## CRITICAL FINDING — pilot is broken
Move-frequency probe (20 battles) showed:
- Protect:    0% of 276 decisions
- Fake Out:   0%
- Parting Shot: 0%
- U-turn/Volt Switch: 0%
- Follow Me/Tailwind/Trick Room: 0%
- Dig: 19.6% + Pass 19.6% (Dig charge/pass cycles)

SimpleHeuristicsPlayer clicks max-damage moves and nothing else.

## Interpretation
78.7% is real but measures "best team vs a broken pilot."
NOT "best team for VGC." All GA results from this session
are pilot-limited.

## Also found
- Umbreon constraint bug in ga_core_v6.py (migration didn't enforce constraints)
- Fixed in ga_core_v6.py at 22:22; not used in this run
- All 6 champions converged to same species: Noivern/Gliscor/Incineroar/Gholdengo/Rillaboom/Garchomp

## Decision
Pilot rebuild is next. Path: BC+RL on 2k+ Showdown replays
(PENDING verification that public replay data exists for our format).
