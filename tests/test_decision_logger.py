import json
import os
import shutil
import sys

# Ensure the root repo directory is in the path so `import src` works
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.decision_logger import DecisionLogger


def test_decision_logger():
    test_dir = "/tmp/test_decisions"
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)

    logger = DecisionLogger(test_dir, max_rows_per_battle=5)
    battle_id = "test_battle_1"

    # Log 10 rows (should truncate to 5)
    for i in range(10):
        logger.log_turn(
            battle_id=battle_id, island="A", gen=1, genome_fitness=0.5,
            outcome="win", our_team=["A"], opp_team=["B"],
            our_active=["A"], opp_active=["B"], our_hp=[1.0], opp_hp=[1.0],
            field={}, legal_moves=["move1"], chosen="move1",
            heuristic_choice="move1", target="opp1"
        )
    logger.close()

    filepath = os.path.join(test_dir, f"{battle_id}.jsonl")
    if not os.path.exists(filepath):
        print("FAIL test_decision_logger")
        return False

    with open(filepath, "r") as f:
        lines = f.readlines()

    if len(lines) != 5:
        print("FAIL test_decision_logger")
        return False

    try:
        for line in lines:
            json.loads(line)
    except json.JSONDecodeError:
        print("FAIL test_decision_logger")
        return False

    print("PASS test_decision_logger")
    return True

if __name__ == "__main__":
    if not test_decision_logger():
        exit(1)
