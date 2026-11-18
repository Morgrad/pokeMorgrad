"""
showdown_server.py — probe and (re)start the local Pokémon Showdown server.

The Node server leaks memory/sockets over thousands of battles, so long runs
bounce it periodically (the GA every `showdown_restart_every` generations).
Port and install dir are passed in; callers own their configuration.
"""
import subprocess
import time
import urllib.request


def is_up(port):
    """True if something answers HTTP on localhost:`port` within 2 s."""
    try:
        urllib.request.urlopen(f"http://localhost:{port}", timeout=2)
        return True
    except Exception:
        return False


def restart(port, showdown_dir, wait_s=60, tries=2):
    """Kill and relaunch the local Showdown server, waiting for it to come back.

    Hard-kills any process on the port, relaunches detached with --no-security
    (local-only, trusted), then polls the HTTP port for up to `wait_s` seconds (a
    server a few hours old has taken >30 s to answer). Retries the whole
    kill+launch up to `tries` times. Returns True once it answers, False if it
    never came up.
    """
    for attempt in range(1, tries + 1):
        print(f"  [showdown] restarting on :{port} (attempt {attempt}/{tries})...")
        subprocess.run(["pkill", "-9", "-f", f"pokemon-showdown start {port}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        subprocess.Popen(
            ["node", "pokemon-showdown", "start", str(port), "--no-security"],
            cwd=showdown_dir,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(wait_s):
            if is_up(port):
                print("  [showdown] back up")
                return True
            time.sleep(1)
    print("  [showdown] FAILED")
    return False


def ensure(port, showdown_dir):
    """Make sure a server answers on `port`; raise RuntimeError if it cannot be (re)started."""
    if not is_up(port) and not restart(port, showdown_dir):
        raise RuntimeError(f"Showdown on :{port} is not answering and could not be restarted")
