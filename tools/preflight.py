"""preflight.py — pre-launch sanity checks for GA runs.

Runs in ~2 s. Catches every failure mode that has burned us at 17:00:
Showdown down, missing data, forgotten venv, unstaged source changes,
constraint code silently removed, no GPU.

Usage:
    python3 tools/preflight.py           # check only
    python3 tools/preflight.py --launch  # check, then launch the overnight run
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check(name, ok, detail=""):
    mark = "OK  " if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--launch", action="store_true",
                        help="if all checks pass, launch the overnight run")
    args = parser.parse_args()

    all_ok = True
    print("=== Pre-flight checks ===\n")

    # 1. Showdown reachable on :8000
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:8000", timeout=3)
        all_ok &= check("Showdown :8000", True)
    except Exception as e:
        all_ok &= check("Showdown :8000", False, str(e)[:60])

    # 2. Showdown process is present (not just port-open)
    r = subprocess.run(["pgrep", "-f", "pokemon-showdown start"],
                       capture_output=True)
    all_ok &= check("showdown process", r.returncode == 0)

    # 3. Required data files exist
    required = [
        "data/regmc_db.json",
        "data/baseline_team.txt",
        "data/pool_split.json",
        "data/meta_items.json",
        "data/species_move_priors.json",
    ]
    for f in required:
        p = ROOT / f
        all_ok &= check(f, p.exists())

    # 4. Source tree clean (no uncommitted changes to src/ or run/)
    r = subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet",
                        "src/", "run/"], capture_output=True)
    all_ok &= check("src/ and run/ committed", r.returncode == 0,
                    "clean" if r.returncode == 0 else "uncommitted changes — commit or stash")

    # 5. Constraint code present in ga_core (silent regression check)
    gc = (ROOT / "src" / "ga_core.py").read_text()
    for name in ["_species_role", "_preferred_pool", "_enforce_composition",
                 "move_priors_for", "CANONICAL_ITEMS", "VAL_POOL_SIZE",
                 "EARLY_STOP_MIN_BATTLES"]:
        all_ok &= check(f"ga_core.{name}", name in gc)

    # 6. Island spec configured with at least one constrained island
    gr = (ROOT / "run" / "ga_run.py").read_text()
    all_ok &= check("islands configured", "ISLANDS" in gr)

    # 7. GPU visible
    try:
        r = subprocess.run(["python3", "-c",
                            "import torch; print(torch.cuda.is_available())"],
                           capture_output=True, text=True, timeout=15)
        gpu_ok = "True" in r.stdout
        all_ok &= check("torch CUDA available", gpu_ok, r.stdout.strip()[:40])
    except Exception as e:
        all_ok &= check("torch CUDA available", False, str(e)[:60])

    # 8. Champion dir writable + has room
    ch = ROOT / "output" / "champions"
    ch.mkdir(parents=True, exist_ok=True)
    try:
        probe = ch / ".preflight_probe"
        probe.write_text("ok")
        probe.unlink()
        all_ok &= check("champions/ writable", True)
    except Exception as e:
        all_ok &= check("champions/ writable", False, str(e)[:60])

    # 9. Free disk space
    free_gb = shutil.disk_usage(str(ROOT)).free / 1e9
    all_ok &= check("disk free > 5 GB", free_gb > 5, f"{free_gb:.1f} GB free")

    # 10. GA concurrency env var resolved
    conc = os.environ.get("GA_CONCURRENCY", "3")
    all_ok &= check("GA_CONCURRENCY set", conc != "3",
                    f"value={conc} (3 is default; set to 8 for prod)")

    print()
    if all_ok:
        print("=== All checks passed ===")
        if args.launch:
            print("Launching overnight run...")
            os.chdir(str(ROOT))
            subprocess.Popen(
                ["nohup", "bash", "run/ga_overnight.sh"],
                stdout=open("/tmp/ga_overnight_launch.log", "w"),
                stderr=subprocess.STDOUT,
                env={**os.environ, "GA_CONCURRENCY": conc},
                start_new_session=True)
            print("  launched. tail -f /tmp/ga_run1.log to watch.")
    else:
        print("=== Some checks FAILED — fix above before launching ===")
        sys.exit(1)


if __name__ == "__main__":
    main()
