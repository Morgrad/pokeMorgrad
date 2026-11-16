"""
player_factory.py — construct poke_env Players for battle.
"""

import logging as _logging
import os
import uuid

from poke_env import AccountConfiguration, ServerConfiguration
from poke_env.player import SimpleHeuristicsPlayer
from poke_env.player.battle_order import DoubleBattleOrder, ForfeitBattleOrder

from src.vgc_pilot import VGCPilot


# --- Suppress benign poke_env protocol noise --------------------------------
class _DropVGCNoise(_logging.Filter):
    _PATTERNS = (
        "cannot reject open team sheets",
        "already made your decision about agreeing to open team sheets",
    )

    def filter(self, record):
        try:
            msg = record.getMessage().lower()
        except Exception:
            return True
        return not any(p in msg for p in self._PATTERNS)


for _name in ("poke_env", "poke_env.ps_client", "poke_env.player"):
    _logging.getLogger(_name).addFilter(_DropVGCNoise())
# ---------------------------------------------------------------------------


# --- Multi-instance support -------------------------------------------------
_SHOWDOWN_PORT = os.environ.get("SHOWDOWN_PORT", "8000")
DEFAULT_SERVER = ServerConfiguration(
    f"ws://localhost:{_SHOWDOWN_PORT}/showdown/websocket",
    f"http://localhost:{_SHOWDOWN_PORT}/action.php?",
)


# --- TimeoutPlayer for early battle forfeit ---------------------------------
class TimeoutPlayer(VGCPilot):
    """Player that automatically forfeits battles when turn limit is exceeded."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def choose_move(self, battle):
        if hasattr(battle, "turn") and battle.turn > 50:
            return DoubleBattleOrder(
                first_order=ForfeitBattleOrder(), second_order=ForfeitBattleOrder()
            )
        return super().choose_move(battle)


RETRY_STRIDE = 999_983


def make_player(pilot, team_str, uid, prefix, battle_format):
    """Construct one poke_env Player for `pilot` on `team_str`."""
    if pilot == "bc":
        from src.bc_player import BCPlayer
        cls = BCPlayer
    elif pilot == "doubles":
        from src.doubles_pilot import DoublesPilot
        cls = DoublesPilot
    elif pilot == "ladder":
        from src.ladder_opp import LadderOpponent
        cls = LadderOpponent
    elif pilot == "vgc":
        from src.vgc_pilot import VGCPilot
        if prefix == "B":
            cls = TimeoutPlayer
        else:
            cls = VGCPilot
    else:
        cls = SimpleHeuristicsPlayer

    return cls(
        battle_format=battle_format,
        team=team_str,
        max_concurrent_battles=1,
        server_configuration=DEFAULT_SERVER,
        account_configuration=AccountConfiguration.generate(
            f"{prefix}{uid}_{uuid.uuid4().hex[:8]}", rand=True
        ),
    )
