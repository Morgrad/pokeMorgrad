import json
import os


class DecisionLogger:
    def __init__(self, output_dir: str, max_rows_per_battle: int = 50):
        self.output_dir = output_dir
        self.max_rows_per_battle = max_rows_per_battle
        self.battle_turns = {}
        os.makedirs(self.output_dir, exist_ok=True)

    def log_turn(self, *, battle_id: str, island: str, gen: int, genome_fitness: float,
                 outcome: str, our_team: list, opp_team: list,
                 our_active: list, opp_active: list, our_hp: list, opp_hp: list,
                 field: dict, legal_moves: list, chosen: str,
                 heuristic_choice: str, target: str, battle_history: list = None) -> None:

        turn_index = self.battle_turns.get(battle_id, 0)
        if turn_index >= self.max_rows_per_battle:
            return
        self.battle_turns[battle_id] = turn_index + 1

        row = {
            "battle_id": battle_id,
            "island": island,
            "gen": gen,
            "genome_fitness": genome_fitness,
            "outcome": outcome,
            "our_team": our_team,
            "opp_team": opp_team,
            "our_active": our_active,
            "opp_active": opp_active,
            "our_hp": our_hp,
            "opp_hp": opp_hp,
            "field": field,
            "legal_moves": legal_moves,
            "chosen": chosen,
            "heuristic_choice": heuristic_choice,
            "target": target,
            "turn_index": turn_index,
            "battle_history": battle_history
        }

        filepath = os.path.join(self.output_dir, f"{battle_id}.jsonl")
        with open(filepath, "a") as f:
            f.write(json.dumps(row) + "\n")

    def close(self) -> None:
        pass
