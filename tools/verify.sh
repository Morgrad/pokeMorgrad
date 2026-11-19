#!/usr/bin/env bash
set -euo pipefail
cd ~/pokeMorgrad
if [ -f .venv/bin/activate ]; then source .venv/bin/activate; else source ~/venv-pokemorgad/bin/activate; fi

step() { echo; echo "=== $1 ==="; }

step "ruff";       ruff check src run tools tests
step "imports";    python -c "import src.ga.engine, src.ga.legality, src.ga.operators, src.eval, src.bc_train, src.bc_player, src.bc_model"
step "imports2";   python -c "import src.paths, src.regmc_db, src.state_encoder, src.audit_before_launch"
step "paths";      python -c "from src.paths import data_path; print(data_path('regmc_db.json'))"
step "pools";      python -c "from src.ga.pools import regional_pool, heldout_pool; print(len(regional_pool()), len(heldout_pool()))"
# One file per line. A failing file stops the script (a plain `a && b && c` chain
# would not: under `set -e` bash ignores failures inside && lists, so later files
# were silently skipped and the script still printed ALL PASS).
TESTS=(
  test_damage test_doubles_eval test_speed_model test_blend_priors test_archetypes
  test_mega_z_lines test_battle_memory test_vgc_pilot test_mega_model test_turn_sim test_turn_sim_paths
  test_support test_opp_actions test_ladder_opp test_meta_weights
  test_battle_hook test_battle_runner test_player_factory test_pilot_support
  test_replay_filters test_replay_log
  test_bc_state
  test_showdown_validator
  test_pools test_genome_clauses
  test_extract_champions
  test_ga_robust test_ga_config test_ga_eval_order test_ga_injection test_island_wiring test_ga_golden
)
step "tests"
for t in "${TESTS[@]}"; do
  echo "--- tests/$t.py"
  if ! python "tests/$t.py"; then
    echo "FAILED: tests/$t.py"
    exit 1
  fi
done
step "audit";      python -m src.audit_before_launch
echo "ALL PASS"
