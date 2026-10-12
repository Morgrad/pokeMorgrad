"""Tactical rules v3 — adds pro-player rules on top of v1.

Design principle: each rule is narrow and targeted. Boost multipliers
use max() stacking, never multiply, to prevent accidental compounding.

Rules:
  v1: Protect lockout, Fake Out lockout, stat-drop avoidance, setup boost
  v3 A: Choice item Protect veto
  v3 B: Spread move partner-damage avoidance
  v3 C: Tailwind / Trick Room awareness
  v3 D: Turn-1 Fake Out prediction
  v3 E: Priority awareness under Trick Room
  v3 F: Win-condition assessment (ahead vs behind)
  v3 G: Pivot move usage when low HP
"""

SPA_DROP_MOVES = {"makeitrain", "dracometeor", "leafstorm", "overheat",
                  "fleurcannon", "psychoboost", "clangingscales"}
ATK_DROP_MOVES = {"superpower", "closecombat", "vcreate"}
SETUP_MOVES = {"nastyplot", "swordsdance", "calmmind", "bulkup",
               "dragondance", "quiverdance", "shellsmash", "irondefense"}
PRIORITY_MOVES = {"aquajet", "bulletpunch", "extremespeed", "fakeout",
                  "grassyglide", "iceshard", "machpunch", "quickattack",
                  "shadowsneak", "suckerpunch", "vacuumwave", "watershuriken",
                  "accelerock", "firstimpression", "jetpunch"}
STATUS_INFLICTING = {"yawn", "thunderwave", "willowisp", "toxic",
                     "spore", "sleeppowder", "stunspore", "glare",
                     "hypnosis", "sing", "nuzzle", "poisongas"}

# --- v3 additions ---
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

# Type-immunity lookups for partner damage check
GROUND_IMMUNE_TYPES = {"Flying"}
GROUND_IMMUNE_ABILITIES = {"levitate"}
ELECTRIC_IMMUNE_TYPES = {"Ground"}
WATER_IMMUNE_ABILITIES = {"waterabsorb", "dryskin", "stormdrain"}
FIRE_IMMUNE_ABILITIES = {"flashfire", "wellbakedbody"}


class RuleEngine:
    def __init__(self):
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

    # ---------- helpers ----------
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
        partner_idx = 1 - slot_idx
        if partner_idx >= len(actives):
            return None
        p = actives[partner_idx]
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
        # Default: hits partner
        return True

    # ---------- main scoring ----------
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

        # --- protect_boost accumulator (max, not multiply) ---
        protect_boost = 1.0
        # --- attack_boost accumulator (max, not multiply) ---
        attack_boost = 1.0
        # --- veto ---
        veto = False

        # ===== v1 rules =====

        # R1: Protect fails on consecutive turns
        if move_id == "protect":
            if info["protect_used_last_turn"]:
                veto = True
            elif hp < 0.35:
                protect_boost = max(protect_boost, 1.5)

        # R2: Fake Out only works on switch-in turn
        if move_id == "fakeout" and info["turns_out"] > 0:
            veto = True

        # R3: Avoid further stat drops when heavily debuffed
        if move_id in SPA_DROP_MOVES and spa <= -2:
            attack_boost = min(attack_boost, 0.10)
        if move_id in ATK_DROP_MOVES and atk <= -2:
            attack_boost = min(attack_boost, 0.20)

        # R4: Setup when healthy + just switched in
        if move_id in SETUP_MOVES:
            if hp > 0.7 and info["turns_out"] <= 1:
                attack_boost = max(attack_boost, 1.6)
            elif hp < 0.5:
                attack_boost = min(attack_boost, 0.3)

        # ===== v3 rules =====

        # A: Choice item Protect veto
        item_norm = self._norm(str(getattr(mon, "item", "") or ""))
        if item_norm in CHOICE_ITEMS_NORM and move_id == "protect":
            veto = True

        # B: Spread move partner-damage avoidance
        if move_id in SPREAD_ALL_ADJACENT:
            partner = self._partner_of(battle, slot_idx)
            if self._partner_takes_damage(partner, move_id):
                attack_boost = min(attack_boost, 0.15)

        # C: Tailwind / Trick Room awareness
        opp_tail = self._side_has(battle, "opponent_side_conditions", "tailwind")
        our_tail = self._side_has(battle, "side_conditions", "tailwind")
        tr = self._field_has(battle, "trickroom")

        if move_id in ("tailwind", "trickroom"):
            if opp_tail and not our_tail:
                attack_boost = max(attack_boost, 1.5)  # reclaim speed control
            if tr and move_id == "trickroom":
                attack_boost = min(attack_boost, 0.2)  # TR already up
            if our_tail and move_id == "trickroom":
                attack_boost = min(attack_boost, 0.3)  # TR would cancel our speed

        # D: Turn-1 Fake Out prediction
        if battle.turn == 1:
            opps = getattr(battle, "opponent_active_pokemon", None)
            if opps is not None:
                opp_list = opps if isinstance(opps, list) else [opps]
                has_fo = any(
                    self._norm(str(getattr(p, "species", ""))) in FAKE_OUT_USERS
                    for p in opp_list if p is not None
                )
                if has_fo and move_id == "protect":
                    protect_boost = max(protect_boost, 1.4)

        # E: Priority under Trick Room
        if tr and move_id in PRIORITY_MOVES:
            # Under TR, priority moves still move first (they override TR)
            # except Fake Out which only works turn 1. Leave neutral.
            pass

        # F: Win-condition assessment
        my_team = getattr(battle, "team", None) or {}
        opp_team = getattr(battle, "opponent_team", None) or {}
        my_alive = sum(1 for p in my_team.values()
                       if not getattr(p, "fainted", False))
        opp_alive = sum(1 for p in opp_team.values()
                        if not getattr(p, "fainted", False))

        if opp_alive > 0 and my_alive > 0:
            if my_alive <= 2 and hp > 0.5:
                # Behind: close out, stop playing safe
                if move_id == "protect":
                    protect_boost = min(protect_boost, 0.4)
            elif my_alive - opp_alive >= 2:
                # Ahead: play safe
                if move_id == "protect":
                    protect_boost = max(protect_boost, 1.3)

        # G: Pivot moves when low HP
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
