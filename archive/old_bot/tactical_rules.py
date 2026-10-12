"""Tactical rules with per-rule toggles.

Enabled rules are read from environment variable TACTICAL_RULES.
Format: comma-separated list of rule IDs.
Default (empty) = v1 rules only.

Rule IDs:
  A: Choice item Protect veto
  B: Spread move partner-damage avoidance
  C: Tailwind / Trick Room awareness
  D: Turn-1 Fake Out prediction
  E: Priority under Trick Room (no-op currently)
  F: Win-condition assessment
  G: Pivot move usage when low HP
"""
import os

# Which extra rules to enable?
_ENV = os.environ.get("TACTICAL_RULES", "").strip()
ENABLED = set(x.strip() for x in _ENV.split(",") if x.strip())

# --- v1 core rules (always on) ---
SPA_DROP_MOVES = {"makeitrain", "dracometeor", "leafstorm", "overheat",
                  "fleurcannon", "psychoboost", "clangingscales"}
ATK_DROP_MOVES = {"superpower", "closecombat", "vcreate"}
SETUP_MOVES = {"nastyplot", "swordsdance", "calmmind", "bulkup",
               "dragondance", "quiverdance", "shellsmash", "irondefense"}

# --- v3 optional rules ---
CHOICE_ITEMS_NORM = {"choiceband", "choicespecs", "choicescarf"}
SPREAD_ALL_ADJACENT = {"earthquake", "surf", "discharge", "explosion",
                       "selfdestruct", "mistyexplosion", "brutalswing",
                       "boomburst", "sludgewave", "lavaplume", "searingshot",
                       "paraboliccharge", "diamondstorm"}
PIVOT_MOVES = {"uturn", "voltswitch", "flipturn", "partingshot",
               "teleport", "batonpass", "chillyreception"}
FAKE_OUT_USERS = {"incineroar", "rillaboom", "sneasler", "meowth", "meowthgalar",
                  "raichu", "persian", "persianalola", "ludicolo", "mienshao",
                  "hawlucha", "gothitelle", "kangaskhan", "ambipom", "weavile",
                  "hitmontop", "medicham", "lopunny", "grimmsnarl", "grapploct",
                  "falinks", "morpeko", "morgrem", "tsareena"}
GROUND_IMMUNE_ABILITIES = {"levitate"}
WATER_IMMUNE_ABILITIES = {"waterabsorb", "dryskin", "stormdrain"}
FIRE_IMMUNE_ABILITIES = {"flashfire", "wellbakedbody"}


class RuleEngine:
    def __init__(self, enabled=None):
        self.state = {}
        self.enabled = enabled if enabled is not None else ENABLED

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
                state[ident] = {"turns_out": 0, "protect_used_last_turn": False}
            else:
                state[ident]["turns_out"] += 1

    def record_move(self, battle, mon, action):
        if mon is None or action is None:
            return
        ident = self._ident(mon)
        if ident is None:
            return
        state = self._battle_state(battle)
        if ident not in state:
            state[ident] = {"turns_out": 0, "protect_used_last_turn": False}
        action_id = getattr(action, "id", None)
        state[ident]["protect_used_last_turn"] = (action_id == "protect")

    def _norm(self, x):
        return (x or "").lower().replace(" ", "").replace("-", "").replace("'", "")

    def _field_has(self, battle, key):
        fields = getattr(battle, "fields", None) or {}
        for f in fields:
            n = self._norm(getattr(f, "name", str(f)))
            if key in n:
                return True
        return False

    def _side_has(self, battle, side_key, cond_key):
        conds = getattr(battle, side_key, None) or {}
        for c in conds:
            n = self._norm(getattr(c, "name", str(c)))
            if cond_key in n:
                return True
        return False

    def _partner_of(self, battle, slot_idx):
        actives = getattr(battle, "active_pokemon", None)
        if not isinstance(actives, list) or len(actives) < 2:
            return None
        p = actives[1 - slot_idx]
        if p is None or getattr(p, "fainted", False):
            return None
        return p

    def _partner_takes_damage(self, partner, move_id):
        if partner is None:
            return False
        types = {self._norm(t) for t in (getattr(partner, "types", None) or [])}
        ability = self._norm(str(getattr(partner, "ability", "") or ""))
        if move_id == "earthquake":
            if "flying" in types:
                return False
            if ability in GROUND_IMMUNE_ABILITIES:
                return False
            return True
        if move_id == "discharge":
            if "ground" in types:
                return False
            return True
        if move_id == "surf":
            if ability in WATER_IMMUNE_ABILITIES:
                return False
            return True
        if move_id in ("lavaplume", "searingshot"):
            if ability in FIRE_IMMUNE_ABILITIES:
                return False
            return True
        return True

    def move_multiplier(self, battle, mon, move_id, slot_idx=0):
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

        veto = False
        protect_boost = 1.0
        attack_boost = 1.0

        # ===== v1 core rules (always on) =====
        if move_id == "protect":
            if info["protect_used_last_turn"]:
                veto = True
            elif hp < 0.35:
                protect_boost = max(protect_boost, 1.5)

        if move_id == "fakeout" and info["turns_out"] > 0:
            veto = True

        if move_id in SPA_DROP_MOVES and spa <= -2:
            attack_boost = min(attack_boost, 0.10)
        if move_id in ATK_DROP_MOVES and atk <= -2:
            attack_boost = min(attack_boost, 0.20)

        if move_id in SETUP_MOVES:
            if hp > 0.7 and info["turns_out"] <= 1:
                attack_boost = max(attack_boost, 1.6)
            elif hp < 0.5:
                attack_boost = min(attack_boost, 0.3)

        # ===== Optional v3 rules =====

        if "A" in self.enabled:
            item_norm = self._norm(str(getattr(mon, "item", "") or ""))
            if item_norm in CHOICE_ITEMS_NORM and move_id == "protect":
                veto = True

        if "B" in self.enabled:
            if move_id in SPREAD_ALL_ADJACENT:
                partner = self._partner_of(battle, slot_idx)
                if self._partner_takes_damage(partner, move_id):
                    attack_boost = min(attack_boost, 0.15)

        if "C" in self.enabled:
            opp_tail = self._side_has(battle, "opponent_side_conditions", "tailwind")
            our_tail = self._side_has(battle, "side_conditions", "tailwind")
            tr = self._field_has(battle, "trickroom")
            if move_id in ("tailwind", "trickroom"):
                if opp_tail and not our_tail:
                    attack_boost = max(attack_boost, 1.5)
                if tr and move_id == "trickroom":
                    attack_boost = min(attack_boost, 0.2)
                if our_tail and move_id == "trickroom":
                    attack_boost = min(attack_boost, 0.3)

        if "D" in self.enabled:
            if battle.turn == 1 and move_id == "protect":
                opps = getattr(battle, "opponent_active_pokemon", None)
                if opps is not None:
                    opp_list = opps if isinstance(opps, list) else [opps]
                    has_fo = any(
                        self._norm(str(getattr(p, "species", ""))) in FAKE_OUT_USERS
                        for p in opp_list if p is not None
                    )
                    if has_fo:
                        protect_boost = max(protect_boost, 1.4)

        if "F" in self.enabled:
            my_team = getattr(battle, "team", None) or {}
            opp_team = getattr(battle, "opponent_team", None) or {}
            my_alive = sum(1 for p in my_team.values()
                           if not getattr(p, "fainted", False))
            opp_alive = sum(1 for p in opp_team.values()
                            if not getattr(p, "fainted", False))
            if opp_alive > 0 and my_alive > 0:
                if my_alive <= 2 and hp > 0.5:
                    if move_id == "protect":
                        protect_boost = min(protect_boost, 0.4)
                elif my_alive - opp_alive >= 2:
                    if move_id == "protect":
                        protect_boost = max(protect_boost, 1.3)

        if "G" in self.enabled:
            if move_id in PIVOT_MOVES and hp < 0.5:
                attack_boost = max(attack_boost, 1.4)

        if veto:
            return 0.0
        return attack_boost * protect_boost

    def switch_base_score(self, battle, mon, slot_idx):
        if mon is None:
            return 0.0
        hp = getattr(mon, "current_hp_fraction", None)
        if hp is None:
            hp = 1.0
        if hp > 0.30:
            return 0.0
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
        return 0.15
