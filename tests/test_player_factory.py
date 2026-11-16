"""
test_player_factory.py — unit tests for player_factory module.
"""

from src.player_factory import make_player

def test_player_factory():
    """Test that make_player exists and returns an object."""
    # Test with heuristic pilot and dummy team string
    player = make_player("heuristic", "dummy_team_string", 1, "B", "gen9championsvgc2026regmc")
    assert player is not None
    print("PASS test_player_factory")

if __name__ == "__main__":
    test_player_factory()