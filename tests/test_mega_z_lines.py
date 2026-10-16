"""Golden tests on the real data: Mega-Z lines (Garchomp, Lucario, Absol) must resolve to the right
set given spread + moves + item, and the speed model must use post-Mega Speed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import opp_model as O  # noqa: E402
from src import speed_model as S  # noqa: E402


def mass(builds, pred):
    return sum(b.weight for b in builds if pred(b))


def is_z(b):
    return b.item == "Garchompite Z"


def test_garchomp_no_info_is_mostly_z_special():
    bs = O.opponent_builds("Garchomp")
    assert abs(sum(b.weight for b in bs) - 1) < 1e-9
    assert 0.4 < mass(bs, is_z) < 0.8
    assert bs[0].item == "Garchompite Z" and bs[0].stats["spa"] > bs[0].stats["atk"]
    assert all(b.stats["atk"] > b.stats["spa"] for b in bs if not is_z(b))


def test_garchomp_scarf_or_life_orb_excludes_z():
    for item in ("Choice Scarf", "Life Orb"):
        bs = O.opponent_builds("Garchomp", item=item)
        assert mass(bs, is_z) < 0.05, item
        assert all(b.item == item for b in bs[:3]), item


def test_garchomp_special_moves_give_modest_z():
    for mv in ("Power Gem", "Draco Meteor", "Earth Power", "Flamethrower"):
        bs = O.opponent_builds("Garchomp", moves_seen=[mv])
        assert mass(bs, is_z) > 0.9, mv
        assert bs[0].nature == "Modest" and bs[0].evs.get("spa") == 32, mv


def test_garchomp_physical_moves_give_physical_set():
    for mv in ("Dragon Claw", "Stomping Tantrum", "Rock Slide"):
        bs = O.opponent_builds("Garchomp", moves_seen=[mv])
        assert mass(bs, is_z) < 0.15, mv
        assert bs[0].stats["atk"] > bs[0].stats["spa"], mv


def test_garchomp_mega_z_species_has_z_stats_and_levitate():
    bs = O.opponent_builds("Garchomp-Mega-Z")
    top = bs[0]
    assert top.item == "Garchompite Z" and top.nature == "Modest"
    assert top.stats["spe"] == 203 and top.stats["spa"] == 212
    assert O.ability_distribution("Garchomp-Mega-Z") == {"levitate": 1.0}
    assert top.form_stats is None


def test_plain_garchomp_mega_is_not_the_z_form():
    bs = O.opponent_builds("Garchomp-Mega")
    assert all(b.form == "Garchomp-Mega" for b in bs)
    assert "levitate" not in O.ability_distribution("Garchomp-Mega")


def test_pre_mega_z_build_carries_post_mega_stats():
    top = O.opponent_builds("Garchomp", moves_seen=["Power Gem"])[0]
    assert top.form == "Garchomp-Mega-Z" and top.stats["spe"] == 154
    assert top.form_stats["spe"] == 203 and top.form_stats["spa"] == 212


def test_item_and_move_distributions():
    d = O.item_distribution("Garchomp")
    assert d["Garchompite Z"] > 0.5 and abs(sum(d.values()) - 1) < 1e-9
    assert O.item_distribution("Garchomp", moves_seen=["Power Gem"])["Garchompite Z"] > 0.85
    assert O.item_distribution("Garchomp", moves_seen=["Dragon Claw"])["Garchompite Z"] < 0.1
    mv = O.move_distribution("Garchomp", item="Garchompite Z")
    assert mv["Power Gem"] > 0.5 and mv.get("Dragon Claw", 0) < 0.1


def test_speed_belief_uses_post_mega_speed_and_unrevealed_scarf():
    b = S.belief_for("Garchomp")
    assert b.p_faster(180) > b.p_faster(180, mega=True)     # Mega'd Z holder outspeeds 180; pre-Mega 154 doesn't
    z = S.belief_for("Garchomp", moves_seen=["Power Gem"])
    assert z.p_faster(190) > 0.99 and z.p_faster(190, mega=True) < 0.5   # 154 pre-Mega, 203 after
    assert z.p_faster(210, mega=True) > 0.9
    scarf = S.belief_for("Garchomp", item="Choice Scarf")
    assert any(h.scarf for h in scarf.hypotheses)
    assert S.belief_for("Garchomp", item="Life Orb").p_faster(220) > 0.99


def test_lucario_and_absol_z_lines():
    lu = O.opponent_builds("Lucario-Mega-Z")
    assert lu[0].item == "Lucarionite Z" and lu[0].stats["spe"] >= 200 and lu[0].stats["spa"] > lu[0].stats["atk"]
    ab = O.opponent_builds("Absol-Mega-Z")
    assert ab[0].item == "Absolite Z" and ab[0].stats["atk"] > ab[0].stats["spa"]
    pre = O.opponent_builds("Lucario")
    assert all(b.item == "Lucarionite Z" and b.form == "Lucario-Mega-Z" for b in pre)
    assert O.ability_distribution("Lucario-Mega-Z") == {"auraguard": 1.0}


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
