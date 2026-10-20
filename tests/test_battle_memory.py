"""BattleMemory: synthetic edge-case tests plus validation against real replay logs."""
import glob
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import battle_memory as B  # noqa: E402


def feed(m, text):
    for line in text.strip().split("\n"):
        m.feed(line.strip().split("|"))
    return m


def new(text=""):
    return feed(B.BattleMemory(), text) if text else B.BattleMemory()


# ---- Mega ----------------------------------------------------------------------------
def test_mega_form_and_stone_exact_for_z_line():
    m = new("""
|switch|p2a: Garchomp|Garchomp, L50, M|100/100
|turn|1
|detailschange|p2a: Garchomp|Garchomp-Mega-Z, L50, M
|-mega|p2a: Garchomp|Garchomp|Garchompite Z
|move|p2a: Garchomp|Earthquake|p1a: X""")
    r = m.mon("p2a: Garchomp")
    assert r.mega_form == "Garchomp-Mega-Z" and r.mega_stone == "Garchompite Z"
    assert r.item == "Garchompite Z" and r.mega_turn == 1
    assert not m.mega_available("p2") and m.mega_available("p1")
    assert m.turn_order(1)[-1].megaed


def test_mega_flag_not_carried_to_next_turn():
    m = new("""
|turn|1
|detailschange|p2a: A|Salamence-Mega, L50
|-mega|p2a: A|Salamence|Salamencite
|move|p2a: A|Tailwind|p2a: A
|turn|2
|move|p2a: A|Dragon Claw|p1a: X""")
    assert m.turn_order(1)[0].megaed and not m.turn_order(2)[0].megaed


# ---- action order edge cases -----------------------------------------------------------
def test_copied_moves_are_not_actions_but_lockedmove_is():
    m = new("""
|turn|1
|move|p1a: A|Fiery Dance|p2a: B
|move|p1b: C|Fiery Dance|p2a: B|[from]ability: Dancer
|move|p2a: D|Outrage|p1a: A|[from]lockedmove
|move|p2b: E|Sleep Talk|p2b: E
|move|p2b: E|Bite|p1a: A|[from]Sleep Talk""")
    assert [a.move for a in m.turn_order(1)] == ["fierydance", "outrage", "sleeptalk"]


def test_cant_counts_as_a_position_and_flinch_pair_is_not_double_counted():
    m = new("""
|turn|1
|move|p1a: A|Fake Out|p2a: B
|cant|p2a: B|flinch
|move|p2b: C|Tailwind|p2b: C""")
    assert [a.kind for a in m.turn_order(1)] == ["move", "cant", "move"]
    assert m.first_mover[1].move == "fakeout"


def test_switch_chosen_vs_pivot_vs_replacement():
    m = new("""
|turn|1
|switch|p1a: A|Incineroar, L50|100/100
|move|p2a: B|U-turn|p1a: A
|switch|p2a: C|Pelipper, L50|100/100
|faint|p1a: A
|upkeep
|switch|p1a: D|Garchomp, L50|100/100""")
    acts = m.actions[1]
    assert [(a.kind, a.chosen) for a in acts] == [("switch", True), ("move", True),
                                                  ("switch", False), ("switch", False)]
    assert [a.kind for a in m.turn_order(1)] == ["switch", "move"]


def test_drag_is_never_a_chosen_action():
    m = new("""
|turn|1
|move|p1a: A|Dragon Tail|p2a: B
|drag|p2a: C|Garchomp, L50|100/100""")
    assert [a.kind for a in m.turn_order(1)] == ["move"]


def test_speed_pairs_need_same_priority_and_untainted_turn():
    m = new("""
|turn|1
|move|p1a: A|Earthquake|p2a: B
|move|p2a: B|Dragon Claw|p1a: A
|move|p1b: C|Fake Out|p2a: B
|turn|2
|move|p1a: A|Earthquake|p2a: B
|-activate|p2a: B|move: After You
|move|p2a: B|Dragon Claw|p1a: A""")
    pairs = m.speed_pairs(1)
    assert len(pairs) == 1 and pairs[0][0].name == "A" and pairs[0][1].name == "B"
    assert m.speed_pairs(2) == [] and m.taint[2] == {"after_you"}


# ---- conditions ----------------------------------------------------------------------
def test_move_weather_turns_left_and_upkeep_does_not_restart():
    m = new("""
|turn|3
|move|p1a: A|Rain Dance|p1a: A
|-weather|RainDance
|-weather|RainDance|[upkeep]
|turn|4""")
    assert m.weather.start_turn == 3 and m.weather.source == "move"
    assert m.turns_left(m.weather) == (4, 7)       # turns 4..7 base, extended Damp Rock
    feed(m, "|turn|7\n|-weather|RainDance|[upkeep]\n|-weather|none\n|turn|8")
    assert m.weather is None and m.history[0].end_turn == 7
    assert m.history[0].end_turn - m.history[0].start_turn + 1 == 5


def test_ability_weather_at_battle_start_and_after_upkeep_start_next_turn():
    m = new("""
|switch|p1a: Pel|Pelikan, L50|100/100
|-weather|RainDance|[from] ability: Drizzle|[of] p1a: Pel""")
    assert m.weather.start_turn == 1 and m.weather.source == "ability: Drizzle"
    m = new("""
|turn|4
|upkeep
|switch|p1a: Pel|Pelipper, L50|100/100
|-weather|Sandstorm|[from] ability: Sand Stream|[of] p1a: Pel""")
    assert m.weather.start_turn == 5


def test_trick_room_tailwind_and_terrain_replacement():
    m = new("""
|turn|2
|-fieldstart|move: Trick Room|[of] p2a: A
|-sidestart|p1: Bob|move: Tailwind
|-fieldstart|move: Grassy Terrain|[from] ability: Grassy Surge|[of] p1b: R
|turn|3
|-fieldstart|move: Psychic Terrain|[from] ability: Psychic Surge|[of] p2b: I""")
    assert m.turns_left(m.condition("field", "Trick Room"), 3) == (4, 4)
    assert m.turns_left(m.condition("p1", "Tailwind"), 3) == (3, 3)
    assert m.condition("field", "Grassy Terrain") is None
    assert m.terrain().name == "Psychic Terrain" and m.terrain().start_turn == 3
    assert m.history[-1].name == "Grassy Terrain" and m.history[-1].end_reason == "replaced"
    feed(m, "|turn|4\n|-fieldend|move: Trick Room\n|-sideend|p1: Bob|move: Tailwind")
    assert m.turns_left(m.condition("field", "Trick Room")) == (0, 0)
    assert m.turns_left(m.terrain(), 4) == (4, 7)


def test_hazard_layers_open_ended():
    m = new("|turn|1\n|-sidestart|p1: Bob|Spikes\n|turn|2\n|-sidestart|p1: Bob|Spikes")
    c = m.condition("p1", "Spikes")
    assert c.layers == 2 and c.start_turn == 1 and m.turns_left(c) is None


# ---- Protect chain -------------------------------------------------------------------
def test_protect_chain_probabilities_and_fail_reset():
    m = new("""
|turn|1
|move|p1a: A|Protect|p1a: A
|-singleturn|p1a: A|Protect
|turn|2""")
    assert abs(m.protect_success_prob("p1a: A") - 1 / 3) < 1e-9
    feed(m, "|move|p1a: A|Protect|p1a: A\n|-singleturn|p1a: A|Protect\n|turn|3")
    assert abs(m.protect_success_prob("p1a: A") - 1 / 9) < 1e-9
    feed(m, "|move|p1a: A|Detect|p1a: A\n|-fail|p1a: A\n|turn|4")
    assert m.protect_success_prob("p1a: A") == 1.0
    assert m.mon("p1a: A").protect_fails == 1 and m.mon("p1a: A").protect_uses == 3


def test_protect_chain_resets_when_turn_skipped_or_other_move_used():
    m = new("|turn|1\n|move|p1a: A|Protect|p1a: A\n|-singleturn|p1a: A|Protect\n|turn|2\n"
            "|move|p1a: A|Tackle|p2a: B\n|turn|3")
    assert m.protect_success_prob("p1a: A") == 1.0
    m = new("|turn|1\n|move|p1a: A|Protect|p1a: A\n|-singleturn|p1a: A|Protect\n|turn|3")
    assert m.protect_success_prob("p1a: A") == 1.0


def test_wide_guard_does_not_use_stall_counter():
    m = new("|turn|1\n|move|p1a: A|Wide Guard|p1a: A\n|-singleturn|p1a: A|Wide Guard\n|turn|2")
    assert m.protect_success_prob("p1a: A") == 1.0


# ---- Open Team Sheet -----------------------------------------------------------------
OTS = ("|showteam|p1|Golisopod||Golisopite|EmergencyExit|LeechLife,CloseCombat,IronHead,Protect|Brave||F|||50|]"
       "Indeedee-F||RockyHelmet|PsychicSurge|Psychic,FollowMe,TrickRoom,HelpingHand|Bold||F|||50|]"
       "Kitty|Raichu|RaichuniteY|LightningRod|ZapCannon,Encore,Protect|Timid||F|||50|")


def test_ots_parsed_and_matched_by_species_including_mega_and_nickname():
    m = new(OTS)
    g = m.ots_set("Golisopod-Mega", "p1")
    assert g["item"] == "golisopite" and g["ability"] == "emergencyexit"
    assert g["moves"] == ["leechlife", "closecombat", "ironhead", "protect"] and g["nature"] == "Brave"
    assert m.ots_set("p1a: Whatever") is None
    assert m.ots_set("Raichu-Mega-Y")["item"] == "raichuniteY".lower()
    assert m.ots_set("Indeedee-F", "p1")["ability"] == "psychicsurge"
    assert m.ots_set("Garchomp") is None and len(m.ots["p1"]) == 3


# ---- speed-relevant flags --------------------------------------------------------------
def test_speed_flags_item_status_slow_start():
    m = new("""
|turn|2
|switch|p1a: Reg|Regigigas, L50|100/100
|-start|p1a: Reg|ability: Slow Start
|turn|5
|-status|p1a: Reg|par
|-enditem|p1a: Reg|Sitrus Berry|[eat]""")
    f = m.speed_flags("p1a: Reg")
    assert f == {"item_consumed": True, "status": "par", "slow_start": True,
                 "turns_since_switch_in": 3}
    feed(m, "|-end|p1a: Reg|Slow Start|[silent]\n|-curestatus|p1a: Reg|par")
    assert not m.speed_flags("p1a: Reg")["slow_start"] and m.speed_flags("p1a: Reg")["status"] is None


# ---- poke_env integration ------------------------------------------------------------
def test_repair_restores_z_form_stats_after_poke_env_overwrites_them():
    from poke_env.battle.pokemon import Pokemon
    mon = Pokemon(gen=9, species="garchomp")
    mon.mega_evolve("Garchompite Z")
    assert mon.base_stats["spe"] == 92            # poke_env wrongly applied Garchomp-Mega
    m = new("""
|switch|p2a: Garchomp|Garchomp, L50, M|100/100
|turn|1
|detailschange|p2a: Garchomp|Garchomp-Mega-Z, L50, M
|-mega|p2a: Garchomp|Garchomp|Garchompite Z""")

    class Bat:
        team = {}
        opponent_team = {"p2: Garchomp": mon}
    B.repair_mega_forms(Bat, m)
    assert mon.base_stats["spe"] == 151 and mon.base_stats["spa"] == 141


# ---- real replays --------------------------------------------------------------------
def _replays(n=600):
    fs = [f for f in sorted(glob.glob(str(ROOT / "data/showdown_replays/gen9championsvgc2026regmc-*.json")))
          if "meta" not in f]
    return fs[:n]


def _memories(n=600):
    for f in _replays(n):
        m = B.BattleMemory()
        for line in json.load(open(f))["log"].split("\n"):
            m.feed(line.split("|"))
        yield m


def test_real_replays_mega_always_exact_and_once_per_side():
    files = _replays()
    if not files:
        print("  (no replay data, skipped)")
        return
    megas = 0
    for m in _memories():
        per_side = Counter(r.side for r in m.mons.values() if r.mega_stone)
        assert all(v == 1 for v in per_side.values())
        for r in m.mons.values():
            if r.mega_stone:
                megas += 1
                assert r.mega_form and "Mega" in r.mega_form and B._id(r.item) == B._id(r.mega_stone)
    assert megas > 300


def test_real_replays_condition_durations_match_the_rules():
    if not _replays():
        return
    dur = {}
    for m in _memories():
        for c in m.history:
            if c.end_reason == "expired":
                dur.setdefault(c.kind, Counter())[c.end_turn - c.start_turn + 1] += 1
    tw = dur["Tailwind"]
    assert set(tw) == {4}
    for kind in ("Trick Room", "weather", "terrain"):
        total = sum(dur[kind].values())
        assert dur[kind][5] / total > 0.9, (kind, dur[kind])


def test_real_replays_protect_fails_two_thirds_on_second_consecutive_use():
    if not _replays(1):
        return
    tot = fails = 0
    for f in _replays(2000):
        m, pend = B.BattleMemory(), None
        for line in json.load(open(f))["log"].split("\n"):
            p = line.split("|")
            if pend is not None and len(p) > 1:
                tot += 1
                fails += p[1] == "-fail"
                pend = None
            if (len(p) > 3 and p[1] == "move" and B._id(p[3]) in B.PROTECT_FAMILY
                    and not any(t.startswith("[from]") for t in p[5:])
                    and abs(m.protect_success_prob(p[2]) - 1 / 3) < 1e-9):
                pend = True
            m.feed(p)
    assert tot > 100 and 0.58 < fails / tot < 0.75, (fails, tot)


def test_real_replays_ots_item_matches_the_stone_that_later_megas():
    seen = ok = 0
    for f in _replays(5006):
        text = open(f).read()
        if "|showteam|" not in text:
            continue
        m = B.BattleMemory()
        for line in json.load(open(f))["log"].split("\n"):
            m.feed(line.split("|"))
        assert set(m.ots) <= {"p1", "p2"} and all(len(v) == 6 for v in m.ots.values())
        for r in m.mons.values():
            if r.mega_stone:
                st = m.ots_set(r.mega_form.rsplit("-Mega", 1)[0], r.side)
                if st:
                    seen += 1
                    ok += st["item"] == B._id(r.mega_stone)
    assert seen > 10 and ok == seen, (ok, seen)


def test_real_replays_every_turn_has_a_consistent_first_mover():
    if not _replays():
        return
    for m in _memories(300):
        for t, a in m.first_mover.items():
            assert a.kind in ("move", "cant") and a.chosen


# ---- volatiles (Taunt / Encore / Yawn durations) -------------------------------------
def test_taunt_turns_left_and_clear_on_end():
    m = new("""
|switch|p2a: Milotic|Milotic, L50|100/100
|turn|3
|move|p1a: X|Taunt|p2a: Milotic
|-start|p2a: Milotic|move: Taunt
""")
    assert m.volatile_left("p2a: Milotic", "Taunt") == 3      # active turns 3, 4, 5
    feed(m, "|turn|4")
    assert m.volatile_left("p2a: Milotic", "Taunt") == 2
    feed(m, "|turn|5")
    assert m.volatile_left("p2a: Milotic", "Taunt") == 1
    feed(m, "|-end|p2a: Milotic|move: Taunt")
    assert m.volatile_left("p2a: Milotic", "Taunt") == 0


def test_volatiles_cleared_on_switch_and_faint():
    m = new("""
|switch|p2a: Milotic|Milotic, L50|100/100
|turn|2
|-start|p2a: Milotic|move: Taunt
|-start|p2a: Milotic|Encore
|switch|p2a: Sneasler|Sneasler, L50|100/100
|switch|p2a: Milotic|Milotic, L50|100/100
""")
    assert m.volatile_left("p2a: Milotic", "Taunt") == 0
    assert m.volatile_left("p2a: Milotic", "Encore") == 0
    feed(m, "|-start|p2a: Milotic|move: Yawn\n|faint|p2a: Milotic")
    assert m.volatile_left("p2a: Milotic", "Yawn") == 0


def test_yawn_pending_until_next_turn_end():
    m = new("""
|switch|p2a: Milotic|Milotic, L50|100/100
|turn|2
|-start|p2a: Milotic|move: Yawn|[of] p1a: X
""")
    assert m.volatile_left("p2a: Milotic", "Yawn") == 2
    feed(m, "|turn|3")
    assert m.volatile_left("p2a: Milotic", "Yawn") == 1       # falls asleep at the end of this turn


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e!r}")
    sys.exit(1 if failed else 0)
