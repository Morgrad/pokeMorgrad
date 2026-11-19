"""Tests for src/meta_weights.py and the GA weighted fitness (src/ga/fitness.py) (no server).

Run: pytest tests/test_meta_weights.py   (or: python tests/test_meta_weights.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import meta_weights as MW  # noqa: E402
from src.ga import fitness as F  # noqa: E402
from src.ga.config import DEFAULT  # noqa: E402
from src.ga.pools import regional_pool  # noqa: E402


def test_species_key_ignores_nicknames_gender_and_mega():
    assert MW.species_key("Rilla (Rillaboom) (M)") == MW.species_key("Rillaboom")
    assert MW.species_key("Indeedee-F") == MW.species_key("Indeedee")
    assert MW.species_key("Floette-Mega") == MW.species_key("Floette")
    assert MW.species_key("Rotom-Wash") == MW.species_key("Rotom")
    assert MW.species_key("Floette-Mega") == MW.species_key("Floette-Eternal")
    assert MW.species_key("Meowstic-F-Mega") == MW.species_key("Meowstic")
    assert MW.species_key("Charizard-Mega-Y") == MW.species_key("Charizard")


def test_replay_poke_line_species_matches_team_species():
    team = "Rilla (Rillaboom) (M) @ Sitrus Berry\nAbility: Grassy Surge\n- Fake Out\n"
    assert MW.team_keys(team) == [MW.species_key("Rillaboom, L50, M".split(",")[0])]


def test_team_weight_uses_usage_with_floor():
    usage = {"rillaboom": 0.4, "incineroar": 0.2}
    team = ("Rillaboom @ Assault Vest\nAbility: Grassy Surge\n- Fake Out\n\n"
            "Incineroar @ Sitrus Berry\nAbility: Intimidate\n- Fake Out\n\n"
            "Pikachu @ Light Ball\nAbility: Static\n- Surf\n")
    assert abs(MW.team_weight(team, usage, floor=0.02) - (0.4 + 0.2 + 0.02) / 3) < 1e-9


def test_weighted_rate_drops_none_and_weights():
    assert MW.weighted_rate([1, 0, None], [3, 1, 100]) == 0.75
    assert MW.weighted_rate([None], [1]) == 0.0
    assert abs(MW.effective_n([1, 1, 1, 1]) - 4) < 1e-9


def test_pool_weights_positive_and_deterministic():
    pool = regional_pool()
    w1 = [MW.team_weight(t) for t in pool]
    w2 = [MW.team_weight(t) for t in pool]
    assert w1 == w2 and min(w1) > 0


def test_ga_fitness_matches_weighted_rate():
    pool = regional_pool()[:4]
    outs = [1, 0, None, 1]
    fit, wins, n = F.weighted_fitness(outs, pool, DEFAULT.meta_weights)
    ws = [F.opp_weight(t, DEFAULT.meta_weights) for t in pool]
    assert (wins, n) == (2, 3)
    assert abs(fit - MW.weighted_rate(outs, ws)) < 1e-12
    assert F.weighted_fitness([None, None], pool[:2], DEFAULT.meta_weights) == (0.0, 0, 0)


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e!r}")
    sys.exit(1 if failed else 0)
