"""src/poke_env_fixes.py: poke_env's KeyError: 'round' when a Round follows its partner's
Round (bare DoubleBattle, no server). Run: python tests/test_poke_env_fixes.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from poke_env.battle import DoubleBattle  # noqa: E402
from poke_env.battle.abstract_battle import AbstractBattle  # noqa: E402

from src import poke_env_fixes as FX  # noqa: E402

PARTNER_ROUND = ["", "move", "p2a: Banette", "Round", "p1a: Pelipper", "[from] move: Round"]


def _battle():
    b = DoubleBattle("battle-gen9championsvgc2026regmc-1", "me", logging.getLogger("test"), gen=9)
    b.player_role = "p1"
    for m in (["", "switch", "p2a: Banette", "Banette, L50, M", "100/100"],
              ["", "switch", "p2b: Typhlosion", "Typhlosion, L50, M", "100/100"],
              ["", "switch", "p1a: Pelipper", "Pelipper, L50, M", "167/167"],
              ["", "switch", "p1b: Kingambit", "Kingambit, L50, M", "160/160"],
              ["", "move", "p2b: Typhlosion", "Round", "p1b: Kingambit"]):
        b.parse_message(m)
    return b


def test_partner_round_is_parsed_and_counted_like_a_normal_round():
    FX.install()
    b = _battle()
    b.parse_message(list(PARTNER_ROUND))                       # raised KeyError: 'round' before
    banette = b.get_pokemon("p2a: Banette").moves
    typhlosion = b.get_pokemon("p2b: Typhlosion").moves
    assert list(banette) == ["round"]                          # revealed: it used Round
    assert banette["round"].current_pp == banette["round"].max_pp - 1 == \
        typhlosion["round"].current_pp                         # one use, same as the partner
    assert b._replay_data[-1] == PARTNER_ROUND                 # replay log keeps the message verbatim


def test_unpatched_poke_env_still_has_the_bug_this_fixes():
    # documents why the patch exists; if a poke_env upgrade fixes it, this test says so
    original = AbstractBattle.parse_message.__wrapped__ if hasattr(AbstractBattle.parse_message, "__wrapped__") \
        else AbstractBattle.parse_message
    b = _battle()
    try:
        original(b, list(PARTNER_ROUND))
        raised = False
    except KeyError:
        raised = True
    assert raised, "poke_env no longer raises KeyError: 'round': src/poke_env_fixes.py may be removable"


def test_only_the_partner_round_message_is_touched():
    assert FX.is_partner_round(PARTNER_ROUND)
    assert FX.is_partner_round(["", "move", "p2a: Banette", "Round", "p1a: Pelipper", "[from]move: Round"])
    assert not FX.is_partner_round(["", "move", "p2b: Typhlosion", "Round", "p1b: Kingambit"])
    assert not FX.is_partner_round(["", "move", "p2a: X", "Tackle", "p1a: Y", "[from] move: Copycat"])
    assert not FX.is_partner_round(["", "switch", "p2a: Banette", "Banette, L50", "100/100"])


def test_install_is_idempotent_and_done_by_player_factory():
    import subprocess
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    code = ("import src.player_factory\n"
            "from poke_env.battle.abstract_battle import AbstractBattle as A\n"
            "print(getattr(A.parse_message, '_pokemorgrad_fix', False))")
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert out.stdout.strip().endswith("True"), (out.stdout[-200:], out.stderr[-300:])   # fresh process
    first = AbstractBattle.parse_message
    FX.install()
    FX.install()
    FX.install()
    assert AbstractBattle.parse_message is first and first._pokemorgrad_fix
    assert not getattr(first.__wrapped__, "_pokemorgrad_fix", False)   # wrapped once, not twice


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e!r}")
    sys.exit(1 if failed else 0)
