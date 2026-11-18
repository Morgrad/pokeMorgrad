"""Golden-master harness for the GA engine (no Showdown server, no real battles).

Captures everything the GA produces from a seeded run: the population operators,
stdout, every checkpoint JSON and the champion files. tests/test_ga_golden.py
runs this in a subprocess (PYTHONHASHSEED=0, since the genome code iterates sets)
and compares the result with tests/golden/ga_golden.json.

Only hooks that are stable across refactors are used:
  - POKEMORGRAD_ROOT  -> a temp root (data/ symlinked) so output goes to a temp dir
  - SHOWDOWN_PORT     -> a tiny local HTTP server, so the "is Showdown up" probe passes
  - src.battle.run_battle            -> deterministic fake battle
  - src.showdown_validator.check_teams -> local DB check instead of node + Showdown

Regenerate the fixture ONLY when a behavior change is intended:
    PYTHONHASHSEED=0 python tests/golden/ga_harness.py --write
"""
import asyncio
import contextlib
import hashlib
import http.server
import io
import json
import os
import random
import re
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "ga_golden.json"


def _start_fake_showdown():
    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("localhost", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def _h(*parts):
    return int(hashlib.md5("|".join(parts).encode()).hexdigest(), 16)


class _BattleLog:
    def __init__(self):
        self.uids = []
        self.kwargs = set()


def _install_fakes(log):
    from src import battle as B
    from src import regmc_db as DB
    from src import showdown_validator as SV

    async def fake_run_battle(team, opp, uid, sem, fmt, **kw):
        log.uids.append(uid)
        log.kwargs.add((fmt, kw.get("pilot"), kw.get("opp_pilot"), kw.get("timeout"),
                        kw.get("min_turns")))
        if _h("none", team, opp) % 23 == 0:
            return None                       # timeout / desync
        strength = _h("str", team) % 100      # some teams are weak -> early-abort path
        return 1 if _h("win", team, opp) % 100 < strength else 0

    def fake_check_teams(texts):
        return [(DB.validate_team(t)[0], "stub") for t in texts]

    B.run_battle = fake_run_battle
    SV.check_teams = fake_check_teams


def _population_part(G):
    """Population operators on fixed fitness lists (deterministic given the seed)."""
    out = {}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        random.seed(7)
        a = G.Island("U", {0: "Umbreon"})
        a.init_population(6)
        b = G.Island("F")
        b.init_population(6)
        out["init_U"] = a.population
        out["init_F"] = b.population
        a.fitness = [0.05 * i for i in range(len(a.population))]
        b.fitness = [0.5 - 0.05 * i for i in range(len(b.population))]
        G.breed(a, immigration_rate=0.2)
        G.breed(b, immigration_rate=0.5)
        out["bred_U"] = a.population
        out["bred_F"] = b.population
        a.fitness = [0.1, 0.4, 0.2, 0.6, 0.3, 0.5]
        b.fitness = [0.3, 0.1, 0.6, 0.2, 0.5, 0.4]
        out["injected"] = G.inject_immigrants(a, 2)
        out["after_inject_U"] = a.population
        a.fitness = [0.1, 0.4, 0.2, 0.6, 0.3, 0.5]
        G.ring_migrate([a, b], n=2)
        out["migrated_U"] = a.population
        out["migrated_F"] = b.population
        out["uniq"] = [G.count_unique_species(a), G.count_unique_species(b)]
        a.best_ever = {"fit": 0.5, "genome": a.population[0], "gen": 3}
        d = json.loads(json.dumps(a.to_dict()))
        out["roundtrip_equal"] = G.Island.from_dict(d).to_dict() == d
        out["to_dict_U"] = d
        out["rng_after"] = random.random()
    out["stdout"] = buf.getvalue()
    return out


def _normalize(text, root):
    text = text.replace(str(root), "<ROOT>")
    text = re.sub(r"\d\d:\d\d:\d\d", "HH:MM:SS", text)
    text = re.sub(r"\(\d+\.\d min\)", "(M min)", text)
    return text


def _snapshot_outputs(root):
    files = {}
    for p in sorted((root / "output").rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(root))
            if p.suffix == ".json":
                d = json.loads(p.read_text())
                d.pop("saved", None)
                files[rel] = {"json": d, "keys": list(json.loads(p.read_text()).keys()),
                              "bytes_wo_saved": re.sub(r'"saved": "[^"]*"', '"saved": ""',
                                                       p.read_text())}
            else:
                files[rel] = p.read_text()
    return files


def _e2e_part(G, root, log):
    """Two run_islands calls: fresh run (small-pool path), then resume (early-stop path)."""
    from src.paths import data_path

    out = {}
    specs = [
        {"name": "A", "constraints": {0: "Umbreon"}, "seed_paths": [data_path("baseline_team.txt")]},
        {"name": "B", "constraints": {}, "seed_paths": []},
    ]
    runs = [
        # fresh: <=50 opponents per genome, aggressive diversity / stagnation rescue
        dict(seed=12345, generations=3, battles_per_genome=20, stagnation_limit=1,
             diversity_floor=40, migration_every=2),
        # resume from the gen-3 checkpoint
        dict(seed=999, generations=5, battles_per_genome=20, stagnation_limit=2,
             diversity_floor=10, migration_every=2),
        # resume again with >50 opponents: head/tail + early-abort path. (Before the
        # ordering fix this path was not deterministic, so it could not be recorded.)
        dict(seed=4242, generations=7, battles_per_genome=60, stagnation_limit=2,
             diversity_floor=10, migration_every=3),
    ]
    for i, r in enumerate(runs):
        buf = io.StringIO()
        log.uids.clear()
        random.seed(r["seed"])
        with contextlib.redirect_stdout(buf):
            asyncio.run(G.run_islands(
                specs, pop_per_island=6, generations=r["generations"],
                battles_per_genome=r["battles_per_genome"], concurrency=4,
                immigration_rate=0.2, stagnation_limit=r["stagnation_limit"],
                diversity_floor=r["diversity_floor"], migration_every=r["migration_every"],
                showdown_restart_every=10, run_id="golden"))
        out[f"run{i}_stdout"] = _normalize(buf.getvalue(), root)
        out[f"run{i}_files"] = json.loads(_normalize(json.dumps(_snapshot_outputs(root)), root))
        out[f"run{i}_battles"] = len(log.uids)
        # RNG consumption check: same draws regardless of which battle got which uid
        out[f"run{i}_uids_sha"] = hashlib.sha1(
            ",".join(map(str, sorted(log.uids))).encode()).hexdigest()
        out[f"run{i}_rng_after"] = random.random()
        out[f"run{i}_battle_kwargs"] = sorted(map(list, log.kwargs))
    return out


def run_all():
    tmp = Path(tempfile.mkdtemp(prefix="ga_golden_"))
    (tmp / "data").symlink_to(REPO / "data")
    os.environ["POKEMORGRAD_ROOT"] = str(tmp)
    os.environ["SHOWDOWN_PORT"] = str(_start_fake_showdown())
    for k in ("GA_PILOT", "GA_OPP", "GA_META_WEIGHTS", "GA_TRAIN_SAMPLE", "GA_CONCURRENCY"):
        os.environ.pop(k, None)
    sys.path.insert(0, str(REPO))

    log = _BattleLog()
    _install_fakes(log)
    from src import ga_core as G

    snap = {"population": _population_part(G), "e2e": _e2e_part(G, tmp.resolve(), log)}
    return json.loads(json.dumps(snap))   # normalize tuples -> lists


def main():
    if os.environ.get("PYTHONHASHSEED") != "0":
        sys.exit("run with PYTHONHASHSEED=0 (the genome code iterates sets)")
    snap = run_all()
    if "--write" in sys.argv:
        FIXTURE.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n")
        print(f"wrote {FIXTURE}")
    else:
        out = sys.argv[sys.argv.index("--out") + 1]
        Path(out).write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
