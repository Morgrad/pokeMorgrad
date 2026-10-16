"""Scrape per-species usage tables from metavgc.com (Champions) into data/scraped/metavgc/.

Usage:
    python tools/scrape_metavgc.py fetch    # list page + every /pokemon/<slug> (cached, 1.5 s apart)
    python tools/scrape_metavgc.py parse    # raw html -> data/scraped/metavgc/species.json

Staging only: nothing here touches the prior files. Raw pages are cached so `parse`
can be re-run offline. Sections parsed: Top Moves, Top Natures (nature + EV spread),
Top Abilities, Top Items, each as [{name, spread?, pct}].
"""
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://metavgc.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) pokeMorgrad-research"
OUT = Path(__file__).resolve().parent.parent / "data" / "scraped" / "metavgc"
RAW = OUT / "raw"
DELAY = 1.5
SECTIONS = {"Top Moves": "moves", "Top Natures": "builds", "Top Abilities": "abilities", "Top Items": "items"}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def fetch() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    listing = RAW / "_list.html"
    if not listing.exists():
        listing.write_text(_get(f"{BASE}/pokemon"))
    slugs = set(re.findall(r'href="/pokemon/([^"/?#]+)"', listing.read_text()))  # list page is truncated
    from src import regmc_db
    slugs |= {re.sub(r"[^a-z0-9]+", "-", n.lower()).strip("-") for n in (s["name"] for s in regmc_db.all_species())}
    slugs = sorted(slugs)
    print(f"{len(slugs)} species pages")
    for i, slug in enumerate(slugs, 1):
        path = RAW / f"{slug}.html"
        if path.exists():
            continue
        try:
            path.write_text(_get(f"{BASE}/pokemon/{slug}"))
            print(f"[{i}/{len(slugs)}] {slug}")
        except urllib.error.HTTPError as e:
            print(f"[{i}/{len(slugs)}] {slug} HTTP {e.code} (skipped)")
        except Exception as e:
            print(f"[{i}/{len(slugs)}] {slug} FAILED: {e}")
        time.sleep(DELAY)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_page(page: str) -> dict:
    page = re.sub(r"<script.*?</script>", "", page, flags=re.S)
    out = {}
    for chunk in re.split(r"<h2[^>]*>", page)[1:]:
        title, _, body = chunk.partition("</h2>")
        key = SECTIONS.get(_text(title))
        if not key:
            continue
        entries = []
        for li in re.findall(r"<li[ >].*?</li>", body, flags=re.S):
            h3 = re.search(r"<h3[^>]*>(.*?)</h3>", li, flags=re.S)
            pct = re.findall(r"([\d.]+)\s*(?:<!-- -->)?\s*%", li)
            if not h3 or not pct:
                continue
            entry = {"name": _text(h3.group(1)), "pct": float(pct[-1])}
            spread = re.search(r"\b(\d+/\d+/\d+/\d+/\d+/\d+)\b", _text(li))
            if key == "builds" and spread:
                entry["spread"] = spread.group(1)
            entries.append(entry)
        out[key] = entries
    return out


def parse() -> None:
    species = {}
    for path in sorted(RAW.glob("*.html")):
        if path.stem.startswith("_"):
            continue
        species[path.stem] = parse_page(path.read_text())
    (OUT / "species.json").write_text(json.dumps(species, indent=1))
    empty = [s for s, d in species.items() if not d.get("moves")]
    print(f"{len(species)} species parsed; {len(empty)} with no moves: {empty[:10]}")


if __name__ == "__main__":
    {"fetch": fetch, "parse": parse}[sys.argv[1] if len(sys.argv) > 1 else "fetch"]()
