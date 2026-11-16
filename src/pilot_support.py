"""
pilot_support.py — support-move resolution logic for doubles pilot.
"""

from poke_env.battle import DoubleBattle, Move, Pokemon

# --- Support move resolution functions ----------------------------------------

def _resolve_taunt(battle: DoubleBattle, mon: Pokemon, move: Move, slot: int) -> None:
    """Resolve Taunt effect."""
    # Taunt prevents the opponent from using status moves for 3 turns
    if "taunt" in mon.effects:
        # Check if the move is a status move
        mv = battle._get_move(move.id)
        if mv and mv.get("category") == "Status":
            # Remove the taunt effect or it will be applied to this turn's move
            pass  # The taunt effect is handled by poke_env


def _resolve_heal(battle: DoubleBattle, mon: Pokemon, move: Move, slot: int) -> None:
    """Resolve Heal effect."""
    # This function might need to update the Pokemon's HP based on healing
    # Implementation depends on specific healing mechanics
    pass


def _resolve_helping_hand(battle: DoubleBattle, mon: Pokemon, move: Move, slot: int) -> None:
    """Resolve Helping Hand effect."""
    # Helping Hand doubles the power of the next move used by an ally
    # This is handled by poke_env's battle mechanics


def _resolve_snarl(battle: DoubleBattle, mon: Pokemon, move: Move, slot: int) -> None:
    """Resolve Snarl effect."""
    # Snarl reduces the special attack of opposing Pokémon
    # This is handled by poke_env's battle mechanics


def _resolve_charm(battle: DoubleBattle, mon: Pokemon, move: Move, slot: int) -> None:
    """Resolve Charm effect."""
    # Charm reduces the attack of opposing Pokémon
    # This is handled by poke_env's battle mechanics


def _resolve_foul_play(battle: DoubleBattle, mon: Pokemon, move: Move, slot: int) -> None:
    """Resolve Foul Play effect."""
    # Foul Play uses the opponent's defense instead of the user's attack
    # This is handled by poke_env's battle mechanics


def _resolve_support_move(battle: DoubleBattle, mon: Pokemon, move: Move, slot: int) -> None:
    """Resolve support-move effects for DoublesPilot."""
    # Resolve Taunt
    if "taunt" in mon.effects:
        _resolve_taunt(battle, mon, move, slot)

    # Resolve Heal
    if "heal" in mon.effects:
        _resolve_heal(battle, mon, move, slot)

    # Resolve Helping Hand
    if "helpinghand" in mon.effects:
        _resolve_helping_hand(battle, mon, move, slot)

    # Resolve Snarl
    if "snarl" in mon.effects:
        _resolve_snarl(battle, mon, move, slot)

    # Resolve Charm
    if "charm" in mon.effects:
        _resolve_charm(battle, mon, move, slot)

    # Resolve Foul Play
    if "foulplay" in mon.effects:
        _resolve_foul_play(battle, mon, move, slot)
