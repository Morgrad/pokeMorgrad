"""Fixes for poke_env bugs that break real battles. Installed once by src/player_factory.py
(every battle player is built there), so all pilots and opponents get them.

1. Round sped up by its partner's Round (KeyError: 'round'), fixed 2026-11-18.
   When both mons of a side use Round, Showdown logs the second one as
       |move|p2a: Banette|Round|p1a: Pelipper|[from] move: Round
   ("[from] move: Round" = moved early because of the partner's Round). poke_env reads that
   tag as a move CALLED by another move (like Copycat / Metronome): it does not reveal
   Round, does not spend its PP, and looks Round up in the user's known moves, which raises
   KeyError: 'round' for a foe that has not shown Round before. The exception kills the
   player's message handler, the player stops deciding, and the battle hangs until its
   timeout and is replayed.
   Fix: parse that message without the misleading tag, i.e. as the ordinary Round it is
   (revealed, one PP spent, like the partner's), then put the verbatim message back into
   battle._replay_data so replay logs are unchanged.
"""
from poke_env.battle.abstract_battle import AbstractBattle

_FROM_ROUND = ("[from] move: Round", "[from]move: Round")


def is_partner_round(split_message) -> bool:
    """True for a Round that moved early because its partner used Round (see above)."""
    return (len(split_message) >= 5 and split_message[1] == "move" and split_message[3] == "Round"
            and any(token in _FROM_ROUND for token in split_message[4:]))


def install() -> None:
    """Patch AbstractBattle.parse_message once (idempotent). The original stays reachable as
    AbstractBattle.parse_message.__wrapped__."""
    if getattr(AbstractBattle.parse_message, "_pokemorgrad_fix", False):
        return
    original = AbstractBattle.parse_message

    def parse_message(self, split_message):
        if not is_partner_round(split_message):
            return original(self, split_message)
        cleaned = [t for t in split_message if t not in _FROM_ROUND]
        replay = getattr(self, "_replay_data", None)
        n = len(replay) if isinstance(replay, list) else None
        try:
            return original(self, cleaned)
        finally:
            # poke_env appends a copy of the message it parsed; restore the original one
            if n is not None and len(replay) > n and replay[n] == cleaned:
                replay[n] = list(split_message)

    parse_message.__wrapped__ = original
    parse_message._pokemorgrad_fix = True
    AbstractBattle.parse_message = parse_message
