"""Tactical rules layered on top of the neural player.

The v1 NN sees only (my_species, opp_species, turn). It cannot see:
- Whether it used Protect last turn (Protect fails on consecutive turns)
- Whether it just switched in (Fake Out only works turn 1)
- Its own stat drops (Make It Rain at -4 SpA is bad)
- Its own HP (should Protect when about to die)
- Its bench (should switch when in danger)

The RuleEngine intercepts the NN's move probabilities and applies
multipliers or vetoes based on visible game state.

Design:
- Rules can VETO (mult=0), WEAKEN (<1), or BOOST (>1)
- If all moves get vetoed, we fall back to NN's top legal move anyway
- State tracked per battle_tag for concurrent battle support
"""


# Move IDs whose user drops its own stats
SPA_DROP_MOVES = {"makeitrain", "dracometeor", "leafstorm", "overheat",
                  "fleurcannon", "psychoboost", "clangingscales"}
ATK_DROP_MOVES = {"superpower", "closecombat", "vcreate"}

# Setup moves
SETUP_MOVES = {"nastyplot", "swordsdance", "calmmind", "bulkup",
               "dragondance", "quiverdance", "shellsmash", "irondefense"}

# Priority moves (negative priority count as 0, they move last)
PRIORITY_MOVES = {"aquajet", "bulletpunch", "extremespeed", "fakeout",
                  "grassyglide", "iceshard", "machpunch", "quickattack",
                  "shadowsneak", "suckerpunch", "vacuumwave", "watershuriken",
                  "accelerock", "firstimpression", "jetpunch"}

# Status-inflicting moves that should not be used on already-statused foes
STATUS_INFLICTING = {"yawn", "thunderwave", "willowisp", "toxic",
                     "spore", "sleeppowder", "stunspore", "glare",
                     "hypnosis", "sing", "nuzzle", "poisongas"}


class RuleEngine:
    def __init__(self):
        # battle_tag -> { pokemon_ident -> {"turns_out": int, "protect_used_last_turn": bool} }
        self.state = {}

    def _battle_state(self, battle):
        tag = getattr(battle, "battle_tag", "default")
        if tag not in self.state:
            self.state[tag] = {}
        return self.state[tag]

    def _ident(self, mon):
        if mon is None:
            return None
        name = getattr(mon, "name", None)
        if name:
            return name
        return str(getattr(mon, "species", "unknown"))

    def observe(self, battle):
        """Called at start of choose_move. Increments turn counters."""
        state = self._battle_state(battle)

        actives = getattr(battle, "active_pokemon", None)
        if actives is None:
            return
        if not isinstance(actives, list):
            actives = [actives]

        for p in actives:
            if p is None:
                continue
            ident = self._ident(p)
            if ident is None:
                continue
            if ident not in state:
                # Freshly switched in this turn
                state[ident] = {"turns_out": 0, "protect_used_last_turn": False}
            else:
                state[ident]["turns_out"] += 1

    def record_move(self, battle, mon, action):
        """Called after choose_move picks an action for this slot."""
        if mon is None or action is None:
            return
        ident = self._ident(mon)
        if ident is None:
            return
        state = self._battle_state(battle)
        if ident not in state:
            state[ident] = {"turns_out": 0, "protect_used_last_turn": False}

        # Only track Protect for the "consecutive" rule
        action_id = getattr(action, "id", None)
        state[ident]["protect_used_last_turn"] = (action_id == "protect")

    def move_multiplier(self, battle, mon, move_id):
        """Return multiplier to apply to NN prob. 0 = veto."""
        if mon is None:
            return 1.0
        ident = self._ident(mon)
        state = self._battle_state(battle)
        info = state.get(ident, {"turns_out": 0, "protect_used_last_turn": False})

        hp = getattr(mon, "current_hp_fraction", None)
        if hp is None:
            hp = 1.0
        boosts = getattr(mon, "boosts", None) or {}
        spa = boosts.get("spa", 0)
        atk = boosts.get("atk", 0)
        my_status = getattr(mon, "status", None)

        # Opponent HP — find the weakest active foe
        opps = getattr(battle, "opponent_active_pokemon", None)
        if opps is None:
            opp_hps = [1.0]
        elif isinstance(opps, list):
            opp_hps = [(getattr(p, "current_hp_fraction", 1.0) or 1.0)
                       for p in opps if p is not None]
        else:
            opp_hps = [getattr(opps, "current_hp_fraction", 1.0) or 1.0]
        min_opp_hp = min(opp_hps) if opp_hps else 1.0

        # Opponent status (single or doubles)
        def _status_of(p):
            if p is None:
                return None
            s = getattr(p, "status", None)
            return s
        if isinstance(opps, list):
            opp_statuses = [_status_of(p) for p in opps if p is not None]
        else:
            opp_statuses = [_status_of(opps)]
        any_opp_statused = any(s is not None for s in opp_statuses)

        mult = 1.0

        # ===== Existing rules =====

        # RULE 1: Protect fails on consecutive turns
        if move_id == "protect":
            if info["protect_used_last_turn"]:
                return 0.0
            if hp < 0.35:
                mult *= 1.5

        # RULE 2: Fake Out only works on the turn the user switches in
        if move_id == "fakeout":
            if info["turns_out"] > 0:
                return 0.0

        # RULE 3: Avoid further stat drops when already heavily debuffed
        if move_id in SPA_DROP_MOVES and spa <= -2:
            mult *= 0.10
        if move_id in ATK_DROP_MOVES and atk <= -2:
            mult *= 0.20

        # RULE 4: Boost setup when healthy and just switched in
        if move_id in SETUP_MOVES:
            if hp > 0.7 and info["turns_out"] <= 1:
                mult *= 1.6
            elif hp < 0.5:
                mult *= 0.3

        # ===== NEW RULES v2 =====

        # RULE 5: Priority move boost when opponent is at KO range
        if move_id in PRIORITY_MOVES and min_opp_hp < 0.25:
            mult *= 1.7

        # RULE 6: Don't waste status-inflicting moves on already-statused foes
        if move_id in STATUS_INFLICTING and any_opp_statused:
            mult *= 0.05

        # RULE 7: Play aggressive when healthy
        if hp > 0.6 and move_id not in SETUP_MOVES and move_id != "protect":
            mult *= 1.15

        # RULE 8: Don't set up when at low HP
        if move_id in SETUP_MOVES and hp < 0.35:
            mult *= 0.05

        # RULE 9: Boost Protect hard when very low
        if move_id == "protect" and hp < 0.20:
            mult *= 2.0

        return mult

    def switch_base_score(self, battle, mon, slot_idx):
        """Return a base score for switching. 0 = don't consider."""
        if mon is None:
            return 0.0
        hp = getattr(mon, "current_hp_fraction", None)
        if hp is None:
            hp = 1.0

        # Only consider switching when clearly in danger
        if hp > 0.30:
            return 0.0

        # Check bench
        switches_field = getattr(battle, "available_switches", None)
        if not switches_field:
            return 0.0
        if isinstance(switches_field[0], list):
            slot_switches = switches_field[slot_idx] if slot_idx < len(switches_field) else []
        else:
            slot_switches = switches_field if slot_idx == 0 else []

        healthy = [p for p in slot_switches
                   if (getattr(p, "current_hp_fraction", None) or 0) > 0.5]
        if not healthy:
            return 0.0

        # Base score that can beat a weak move prediction
        return 0.15
