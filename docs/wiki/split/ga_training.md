# GA/Training System

This section covers the genetic algorithm and training components.

## ga_core.py (420 lines)
Core GA logic for the Champions format.
- `Island` class manages a population of genomes, runs evolution steps with `evolve_step`.
- `Population` handles individuals (genomes) in `self.genomes`, each with `.fitness` and `.team` properties.
- `tournament_selection(population, k=3)` selects parents for breeding.
- `mate(parent1, parent2)` creates offspring through crossover + mutation.
- `evolve_step(island)` is the main evolutionary loop: evaluate fitness, select, breed, replace worst.
- `filter_legal_genomes` filters out illegal teams using `showdown_validator.check_teams`.
- `fitness` (from `src/eval_fitness.py`) scores a team on 0-1 scale, with `team_to_score` -> `(score, details)`.

## eval_fitness.py (275 lines)
Team evaluation logic: 100 battles vs. 100 random teams.
- `eval_team(team, n_battles=100, n_workers=4)` returns a team's fitness score (0-1).
- Uses `src/ga_core.py`'s `Island` with `n_workers=4` to run battles.
- `team_to_score(team)` -> `(score, details)` where details include `n_won`, `n_lost`, `n_tied`.
- `eval_team` uses `doubles_eval` (for damage estimation) and `battle_memory` (for opponent model).
- `eval_team` calls `ga_core.Island.run_battle` with `team1` = input team, `team2` = random team.

## ga_island.py (105 lines)
Launches the GA evolution process.
- `main()` parses command-line args for `n_generations`, `n_islands`, `n_workers`, etc.
- Starts `n_islands` of `ga_core.Island` with `n_workers`.
- Each island runs `evolve_step` for `n_generations`.
- Uses `src/ga_core.py`'s `Island` class and `src/eval_fitness.py`'s evaluation functions.

## run/ga_parallel.sh (35 lines)
Parallel launcher for GA islands.
- Launches 3 Showdown servers on ports 8000, 8001, 8002.
- Starts 3 `ga_island.py` processes with different seed ranges.
- Uses `n_workers=4` per island (for 12 total workers).