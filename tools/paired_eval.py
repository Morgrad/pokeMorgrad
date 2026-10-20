"""Paired live comparison: VGCPilot with use_turn_sim off vs on, same team matchups.

Each matchup (our team, heuristic opponent's team; both drawn from the held-out pool with a fixed
seed) is played once per arm, concurrently, so both arms always have the same sample size.

Run one shard per Showdown server (SHOWDOWN_PORT picks the server), or all three with the wrapper:
  bash tools/paired_run.sh ladder 5500          # restarts a crashed shard, resumes from its log
  SHOWDOWN_PORT=8000 python tools/paired_eval.py run --shard 0 --shards 3 --target 5500 --opp ladder
Progress / result:
  python tools/paired_eval.py status --opp ladder
  python tools/paired_eval.py report data/paired_eval/ladder_shard*.jsonl

Checkpointing: every finished matchup is one flushed JSONL line. Re-running the same command resumes:
matchups already logged with both arms finished are skipped, error rows are retried (the report keeps
the last row per matchup). `--target N` = matchups per shard to have in the log; `--minutes` only caps
this invocation. `--chunk N` stops after N newly finished matchups (the wrapper then restarts the
Showdown server and resumes: the Node server and long-lived asyncio loops slow down over thousands of
battles). Exit code 0 = target reached, 10 = chunk done (resume), 2 = aborted on repeated errors.
"""
import argparse
import asyncio
import json
import os
import random
import sys
import time
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "paired_eval"
MAX_CONSEC_ERRORS = 12
ARMS = ("off", "on")
FMT = "gen9championsvgc2026regmc"
TIMEOUT = 90
SEED = 2026
RETRY_STRIDE = 999_983


def matchups(n=100000):
    from src import ga_core as G
    pool = G.heldout_pool()
    rng = random.Random(SEED)
    out = []
    for _ in range(n):
        i, j = rng.sample(range(len(pool)), 2)
        out.append((i, j, pool[i], pool[j]))
    return out


async def one_battle(k, arm, ours, theirs, sem, opp="heuristic"):
    from src import battle as B
    flag = arm == "on"
    for attempt in range(2):
        uid = 1_000_000 + k * 2 + (1 if flag else 0) + attempt * RETRY_STRIDE
        async with sem:
            bot = foe = None
            t0 = time.time()
            try:
                bot = B.make_player("vgc", ours, uid, "B", FMT)
                bot.use_turn_sim = flag
                foe = B.make_player(opp, theirs, uid, "O", FMT)
                await asyncio.wait_for(bot.battle_against(foe, n_battles=1), timeout=TIMEOUT)
                if bot.n_finished_battles:
                    turns = getattr(list(bot.battles.values())[-1], "turn", 0)
                    return {"win": int(bot.n_won_battles > 0), "turns": turns, "secs": time.time() - t0,
                            "counters": dict(bot.stats_counter),
                            "foe": dict(getattr(foe, "stats_counter", {}))}
            except Exception as e:
                err = repr(e)[:120]
            else:
                err = "unfinished"
            finally:
                for p in (bot, foe):
                    try:
                        if p:
                            await p.ps_client.stop_listening()
                    except Exception:
                        pass
    return {"win": None, "error": err}


def load_rows(paths):
    """Last row per matchup k across the files; a truncated last line (killed mid-write) is skipped."""
    rows = {}
    for p in paths:
        if not os.path.exists(p):
            continue
        for line in open(p):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rows[r["k"]] = r
    return list(rows.values())


def finished(r):
    return all(r[a]["win"] is not None for a in ARMS)


async def run(args):
    ms = matchups()
    sem = asyncio.Semaphore(args.concurrency * 2)
    t_end = time.time() + args.minutes * 60 if args.minutes else float("inf")
    done = {r["k"] for r in load_rows([args.out]) if finished(r)}
    with open(args.out + ".plan", "w") as f:
        json.dump({"target": args.target, "opp": args.opp, "shard": args.shard, "shards": args.shards,
                   "started": time.time(), "resumed_with": len(done)}, f)
    print(f"shard {args.shard}/{args.shards} opp={args.opp}: {len(done)} done, target {args.target}", flush=True)
    todo = iter(k for k in range(args.shard, len(ms), args.shards) if k not in done)
    out = open(args.out, "a")
    if out.tell() and open(args.out, "rb").read()[-1:] != b"\n":
        out.write("\n")
    state = {"done": len(done), "consec_err": 0, "abort": False}
    start_done, t_start = len(done), time.time()

    async def worker():
        while (time.time() < t_end and state["done"] < args.target and not state["abort"]
               and (not args.chunk or state["done"] - start_done < args.chunk)):
            k = next(todo, None)
            if k is None:
                return
            i, j, ours, theirs = ms[k]
            res = await asyncio.gather(*(one_battle(k, a, ours, theirs, sem, args.opp) for a in ARMS))
            row = {"k": k, "ours": i, "theirs": j, "t": time.time(), **{a: r for a, r in zip(ARMS, res)}}
            out.write(json.dumps(row) + "\n")
            out.flush()
            if finished(row):
                state["done"] += 1
                state["consec_err"] = 0
            else:
                state["consec_err"] += 1
                if state["consec_err"] >= MAX_CONSEC_ERRORS:
                    state["abort"] = True

    await asyncio.gather(*(worker() for _ in range(args.concurrency)))
    if state["abort"]:
        print(f"ABORT: {MAX_CONSEC_ERRORS} consecutive unfinished matchups (server down?); rerun to resume", flush=True)
        return 2
    el = max(1.0, time.time() - t_start)
    print(f"shard {args.shard}: {state['done'] - start_done} matchups in {el:.0f}s = "
          f"{60 * (state['done'] - start_done) / el:.0f}/min; {state['done']} done", flush=True)
    if state["done"] >= args.target:
        return 0
    return 10 if args.chunk and state["done"] - start_done >= args.chunk else 3


def wilson(w, n, z=1.96):
    if not n:
        return 0.0, 0.0
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / d
    return c - h, c + h


def mcnemar_p(b, c):
    n = b + c
    if not n:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def report(paths):
    rows = load_rows(paths)
    print(f"matchups logged: {len(rows)}")
    for a in ARMS:
        ok = [r[a] for r in rows if r[a]["win"] is not None]
        w = sum(r["win"] for r in ok)
        lo, hi = wilson(w, len(ok))
        err = len(rows) - len(ok)
        secs = sum(r["secs"] for r in ok) / max(1, len(ok))
        print(f"  {a:3s}: {w}/{len(ok)} = {100 * w / max(1, len(ok)):.1f}%  95% CI [{100 * lo:.1f}-{100 * hi:.1f}]"
              f"  errors {err}  mean battle {secs:.1f}s")
    both = [r for r in rows if r["off"]["win"] is not None and r["on"]["win"] is not None]
    b = sum(1 for r in both if r["on"]["win"] and not r["off"]["win"])
    c = sum(1 for r in both if r["off"]["win"] and not r["on"]["win"])
    n = len(both)
    diff = (sum(r["on"]["win"] for r in both) - sum(r["off"]["win"] for r in both)) / max(1, n)
    se = ((b + c) / max(1, n) - ((b - c) / max(1, n)) ** 2) ** 0.5 / max(1, n) ** 0.5
    print(f"paired (both finished) n={n}: on-off = {100 * diff:+.1f} pts  95% CI [{100 * (diff - 1.96 * se):+.1f}, "
          f"{100 * (diff + 1.96 * se):+.1f}]  on-only wins {b}, off-only wins {c}, McNemar p={mcnemar_p(b, c):.3f}")
    ons = [r["on"]["counters"] for r in rows if r["on"]["win"] is not None]
    tot = {k: sum(c.get(k, 0) for c in ons) for k in ("turns", "overrides", "sim_turns", "sim_protect",
                                                       "sim_switch", "sim_fakeout", "errors")}
    print("flag-on counters:", tot)
    offc = [r["off"]["counters"] for r in rows if r["off"]["win"] is not None]
    for a in ARMS:
        fc = [r[a].get("foe", {}) for r in rows if r[a]["win"] is not None]
        if any(fc):
            print(f"opponent counters vs {a}:", {k: sum(c.get(k, 0) for c in fc) for k in ("turns", "protect", "fakeout", "errors")})
    print("flag-off counters: overrides", sum(c.get("overrides", 0) for c in offc),
          "turns", sum(c.get("turns", 0) for c in offc), "errors", sum(c.get("errors", 0) for c in offc))


def status(opp):
    now = time.time()
    tot_done = tot_target = 0
    rate = 0.0
    all_rows = []
    for p in sorted(OUT_DIR.glob(f"{opp}_shard*.jsonl")):
        rows = load_rows([str(p)])
        all_rows += rows
        good = [r for r in rows if finished(r)]
        plan = {}
        if os.path.exists(str(p) + ".plan"):
            plan = json.load(open(str(p) + ".plan"))
        stamps = sorted(r["t"] for r in rows if "t" in r)
        recent = [t for t in stamps if t > now - 300]
        span = min(300.0, max(30.0, now - stamps[0])) / 60 if stamps else 5.0
        r5 = len(recent) / span
        age = now - stamps[-1] if stamps else float("nan")
        tgt = plan.get("target", 0)
        tot_done += len(good)
        tot_target += tgt
        rate += r5
        flag = "RUNNING" if age < 120 else "STALLED/STOPPED"
        print(f"  {p.name}: {len(good)}/{tgt} done, {r5:.0f}/min (last 5 min), last write {age:.0f}s ago  [{flag}]")
    if not all_rows:
        print(f"no {opp}_shard*.jsonl in {OUT_DIR}")
        return
    left = max(0, tot_target - tot_done)
    eta = f"{left / rate:.0f} min" if rate else "n/a"
    print(f"total {tot_done}/{tot_target}, {rate:.0f}/min, ETA {eta}")
    both = [r for r in all_rows if finished(r)]
    wins = {a: sum(r[a]["win"] for r in both) for a in ARMS}
    b = sum(1 for r in both if r["on"]["win"] and not r["off"]["win"])
    c = sum(1 for r in both if r["off"]["win"] and not r["on"]["win"])
    n = max(1, len(both))
    d = (wins["on"] - wins["off"]) / n
    se = ((b + c) / n - ((b - c) / n) ** 2) ** 0.5 / n ** 0.5
    print(f"so far n={len(both)}: off {100 * wins['off'] / n:.1f}%  on {100 * wins['on'] / n:.1f}%  "
          f"paired {100 * d:+.1f} pts [{100 * (d - 1.96 * se):+.1f}, {100 * (d + 1.96 * se):+.1f}]  "
          f"McNemar p={mcnemar_p(b, c):.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--shard", type=int, default=0)
    r.add_argument("--shards", type=int, default=1)
    r.add_argument("--target", type=int, default=5500, help="matchups per shard to have in the log")
    r.add_argument("--chunk", type=int, default=0, help="stop after N new matchups (exit 10) so the wrapper can restart")
    r.add_argument("--minutes", type=float, default=0, help="cap for this invocation (0 = none)")
    r.add_argument("--concurrency", type=int, default=3)
    r.add_argument("--out", default=None)
    r.add_argument("--opp", default="heuristic", help="opponent pilot: heuristic or ladder")
    st = sub.add_parser("status")
    st.add_argument("--opp", default="ladder")
    q = sub.add_parser("report")
    q.add_argument("paths", nargs="+")
    a = ap.parse_args()
    if a.cmd == "report":
        report(a.paths)
    elif a.cmd == "status":
        status(a.opp)
    else:
        os.makedirs(OUT_DIR, exist_ok=True)
        a.out = a.out or str(OUT_DIR / f"{a.opp}_shard{a.shard}.jsonl")
        sys.exit(asyncio.run(run(a)))
