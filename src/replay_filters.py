import random

TRIGGER_STRINGS = [
    "Psychic Terrain", "Grassy Terrain", "Electric Terrain", "Misty Terrain",
    "Sunny Day", "Rain Dance", "Sandstorm", "Snowscape",
    "Trick Room", "Tailwind"
]

def has_trigger(battle_history: list) -> bool:
    if not battle_history:
        return False
    for line in battle_history:
        if any(trigger in line for trigger in TRIGGER_STRINGS):
            return True
    return False

def default_ga_filter(fitness: float, outcome: str, genome_species: list,
                      battle_history: list, rng=None) -> bool:
    if rng is None:
        rng = random

    # Top performers
    if fitness > 0.75:
        return True

    # Near-best that lose (failure modes)
    if fitness > 0.65 and outcome == "loss":
        return True

    # Diagnostic triggers (terrain, weather, TR)
    if has_trigger(battle_history):
        return True

    # Unbiased random sample (2%)
    if rng.random() < 0.02:
        return True

    return False
