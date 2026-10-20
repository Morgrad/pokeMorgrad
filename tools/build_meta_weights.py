"""Rebuild data/species_ladder_usage.json from the scraped ladder replays and summarise the pool weights.

  python tools/build_meta_weights.py [--replays data/showdown_replays]
Re-run whenever new replays are scraped; the GA reads the file at startup.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import ga_core as G  # noqa: E402
from src import meta_weights as MW  # noqa: E402
from src.paths import data_path  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replays", default=data_path("showdown_replays"))
    a = ap.parse_args()
    usage, sides = MW.usage_from_replays(a.replays)
    if not sides:
        sys.exit(f"no replays found in {a.replays}")
    MW.save_usage(usage, sides)
    top = sorted(usage.items(), key=lambda kv: -kv[1])[:12]
    print(f"{sides} team sides, {len(usage)} species -> {MW.USAGE_PATH}")
    print("top:", ", ".join(f"{k} {v:.3f}" for k, v in top))
    for label, pool in (("train", G.regional_pool()), ("holdout", G.heldout_pool())):
        w = sorted(MW.team_weight(t, usage) for t in pool)
        print(f"{label}: {len(pool)} teams, weight min {w[0]:.3f} median {w[len(w) // 2]:.3f} max {w[-1]:.3f}, "
              f"effective n {MW.effective_n(w):.0f}/{len(w)}")


if __name__ == "__main__":
    main()
