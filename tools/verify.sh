#!/usr/bin/env bash
set -euo pipefail
cd ~/pokeMorgrad
source ~/venv-pokemorgad/bin/activate

step() { echo; echo "=== $1 ==="; }

step "ruff";       ruff check src run tools
step "imports";    python -c "import src.ga_core, src.eval, src.bc_train, src.bc_player, src.bc_model"
step "imports2";   python -c "import src.paths, src.regmc_db, src.state_encoder, src.audit_before_launch"
step "paths";      python -c "from src.paths import data_path; print(data_path('regmc_db.json'))"
step "pools";      python -c "from src.ga_core import regional_pool, heldout_pool; print(len(regional_pool()), len(heldout_pool()))"
step "tests";      python tests/test_damage.py && python tests/test_doubles_eval.py && python tests/test_speed_model.py && python tests/test_blend_priors.py && python tests/test_archetypes.py && python tests/test_mega_z_lines.py && python tests/test_battle_memory.py && python tests/test_vgc_pilot.py && python tests/test_mega_model.py && python tests/test_turn_sim.py && python tests/test_opp_actions.py && python tests/test_ladder_opp.py && python tests/test_meta_weights.py
step "audit";      python -m src.audit_before_launch
echo "ALL PASS"
