"""Load real tournament teams (Showdown format text) from ~/project/real_teams/."""
import os, random, glob

REAL_DIR = os.path.expanduser("~/project/real_teams")
_cache = None

def load_real_teams():
    global _cache
    if _cache is not None:
        return _cache
    files = glob.glob(os.path.join(REAL_DIR, "*.txt"))
    teams = []
    for f in files:
        try:
            txt = open(f).read().strip()
            if txt and txt.count("@") >= 6:
                teams.append(txt)
        except Exception:
            pass
    _cache = teams
    return teams

def sample_real_team():
    teams = load_real_teams()
    return random.choice(teams) if teams else None
