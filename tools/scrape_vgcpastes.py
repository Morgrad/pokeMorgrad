"""Scrape VGCPastes Champions M-C tab and download team pastes.

Usage:
    python3 tools/scrape_vgcpastes.py fetch-csv
    python3 tools/scrape_vgcpastes.py report
    python3 tools/scrape_vgcpastes.py filter-balanced
    python3 tools/scrape_vgcpastes.py fetch-teams

Sheet uses HYPERLINK formulas — CSV export loses the real URL.
Must use XLSX + openpyxl to read cell.hyperlink.target.
"""
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

import openpyxl

SHEET_ID = "1axlwmzPA49rYkqXh7zHvAtSP-TKbM0ijGYBPRflLSWw"
TAB_NAME = "Champions M-C"
RAW_DIR = Path("/tmp/vgc_raw")
OUT_DIR = Path("/tmp/vgc_scraped")
RAW_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

BALANCED_TOURNAMENTS = {
    "Baltimore Regional 2027",
    "Louisville Regional 2027",
    "2027 Global Challenge I (Seniors)",
    "2027 Global Challenge I",
    "Frankfurt Regional 2027",
    "Ranked Season M-6",
    "Brisbane Regional 2027",
    "Recife Regional 2027",
    "VR October Challenge",
    "VR September Challenge",
    "VR September Challenge #2",
    "VR October Challenge #2",
    "Local Tour",
}


def fetch_url(url, timeout=60, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", errors="replace")


def find_col(header, *needles):
    for k in header:
        lk = k.lower()
        if all(n.lower() in lk for n in needles):
            return k
    return None


def cmd_fetch_csv():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
    print(f"Fetching {TAB_NAME} as XLSX...")
    data = fetch_url(url, binary=True)
    xlsx_path = RAW_DIR / "m-c.xlsx"
    xlsx_path.write_bytes(data)
    print(f"  {len(data)} bytes -> {xlsx_path}")

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    if TAB_NAME not in wb.sheetnames:
        print(f"  ERROR: '{TAB_NAME}' not in workbook")
        print(f"  available: {wb.sheetnames}")
        sys.exit(1)
    ws = wb[TAB_NAME]

    header_row = None
    for r in range(1, 15):
        for c in range(1, 30):
            if ws.cell(row=r, column=c).value == "Team ID":
                header_row = r
                break
        if header_row:
            break
    if not header_row:
        print("  ERROR: no 'Team ID' header found")
        sys.exit(1)

    col_idx = {}
    for c in range(1, ws.max_column + 1):
        name = ws.cell(row=header_row, column=c).value
        if name:
            col_idx[str(name).strip()] = c

    print(f"  header row: {header_row}")
    print(f"  columns: {list(col_idx.keys())[:12]}")

    paste_col = col_idx.get("Pokepaste")
    if not paste_col:
        print("  ERROR: no 'Pokepaste' column")
        sys.exit(1)

    records = []
    hyperlinks_found = 0
    for r in range(header_row + 1, ws.max_row + 1):
        team_id = ws.cell(row=r, column=col_idx.get("Team ID", 1)).value
        if not team_id or not str(team_id).strip():
            continue
        rec = {}
        for name, ci in col_idx.items():
            v = ws.cell(row=r, column=ci).value
            rec[name] = "" if v is None else str(v).strip()
        cell = ws.cell(row=r, column=paste_col)
        if cell.hyperlink and cell.hyperlink.target:
            rec["Pokepaste"] = cell.hyperlink.target
            hyperlinks_found += 1
        records.append(rec)

    out = RAW_DIR / "m-c.csv"
    out.write_text(json.dumps(records, indent=1))
    print(f"  {len(records)} rows, {hyperlinks_found} hyperlinks resolved")
    print(f"  -> {out}")


def load_rows():
    path = RAW_DIR / "m-c.csv"
    if not path.exists():
        print("no data yet — run 'fetch-csv' first")
        sys.exit(1)
    return json.loads(path.read_text())


def cmd_report():
    rows = load_rows()
    header = list(rows[0].keys())
    col_rank = find_col(header, "rank") or ""
    col_tourn = find_col(header, "tournament") or find_col(header, "event") or ""
    col_evs = find_col(header, "evs") or ""

    print(f"{len(rows)} rows\n")
    ranks, tourns, evs = Counter(), Counter(), Counter()
    for row in rows:
        ranks[(row.get(col_rank) or "").strip()] += 1
        tourns[(row.get(col_tourn) or "").strip()] += 1
        evs[(row.get(col_evs) or "").strip()] += 1

    print("=== rank (top 20) ===")
    for k, v in ranks.most_common(20):
        print(f"  {(k or '(empty)'):<20} {v}")
    print(f"\n=== tournaments ({len(tourns)}, top 30) ===")
    for k, v in tourns.most_common(30):
        print(f"  {(k or '(empty)')[:60]:<60} {v}")
    print(f"\n=== EVs ===")
    for k, v in evs.most_common():
        print(f"  {(k or '(empty)'):<20} {v}")


def cmd_filter_balanced():
    rows = load_rows()
    header = list(rows[0].keys())
    col_teamid = find_col(header, "team", "id") or header[0]
    col_evs = find_col(header, "evs") or ""
    col_tourn = find_col(header, "tournament") or find_col(header, "event") or ""

    kept, drop_evs, drop_tourn = [], 0, 0
    for row in rows:
        tid = (row.get(col_teamid) or "").strip()
        if not tid:
            continue
        if (row.get(col_evs) or "").strip() != "Yes":
            drop_evs += 1
            continue
        if (row.get(col_tourn) or "").strip() not in BALANCED_TOURNAMENTS:
            drop_tourn += 1
            continue
        kept.append(tid)

    (RAW_DIR / "keep_ids.txt").write_text("\n".join(kept))
    print(f"Balanced filter: kept {len(kept)}")
    print(f"  dropped {drop_evs}  (EVs != Yes)")
    print(f"  dropped {drop_tourn}  (tournament not Tier 1+2)")

    keep_set = set(kept)
    c = Counter()
    for row in rows:
        tid = (row.get(col_teamid) or "").strip()
        if tid in keep_set:
            c[(row.get(col_tourn) or "").strip()] += 1
    print("\nKept by tournament:")
    for k, v in c.most_common():
        print(f"  {k[:50]:<50} {v}")


def extract_paste_id(url):
    m = re.search(r"pokepast\.es/([a-zA-Z0-9]+)", url or "")
    return m.group(1) if m else None


def cmd_fetch_teams():
    rows = load_rows()
    header = list(rows[0].keys())
    col_teamid = find_col(header, "team", "id") or header[0]
    col_rank = find_col(header, "rank") or ""
    col_tourn = find_col(header, "tournament") or find_col(header, "event") or ""
    col_evs = find_col(header, "evs") or ""
    col_paste = find_col(header, "pokepaste") or ""

    keep_path = RAW_DIR / "keep_ids.txt"
    keep_set = None
    if keep_path.exists():
        keep_set = set(keep_path.read_text().split("\n"))
        print(f"Using filter: {len(keep_set)} team IDs")

    metadata, todo = {}, []
    for row in rows:
        tid = (row.get(col_teamid) or "").strip()
        if not tid:
            continue
        if keep_set is not None and tid not in keep_set:
            continue
        paste_url = (row.get(col_paste) or "").strip()
        paste_id = extract_paste_id(paste_url)
        if not paste_id:
            continue
        metadata[tid] = {
            "team_id": tid,
            "rank": (row.get(col_rank) or "").strip(),
            "tournament": (row.get(col_tourn) or "").strip(),
            "evs": (row.get(col_evs) or "").strip(),
            "paste_url": paste_url,
            "paste_id": paste_id,
        }
        todo.append(tid)

    (RAW_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print(f"metadata for {len(todo)} teams")

    downloaded = skipped = failed = 0
    for i, tid in enumerate(todo):
        out = OUT_DIR / f"{tid}.txt"
        if out.exists() and out.stat().st_size > 50:
            skipped += 1
            continue
        paste_id = metadata[tid]["paste_id"]
        try:
            text = fetch_url(f"https://pokepast.es/{paste_id}/raw", timeout=30)
            if len(text) < 100:
                raise ValueError(f"response too short: {len(text)} bytes")
            # Strip Tera Type lines — Reg M-C disables Tera, and malformed
            # values ("None") crash poke_env's team loader.
            import re as _re
            text = _re.sub(r"^Tera Type:.*\n", "", text, flags=_re.MULTILINE)
            out.write_text(text)
            downloaded += 1
        except Exception as e:
            print(f"  FAIL {tid}: {type(e).__name__}: {e}")
            failed += 1
        time.sleep(0.5)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(todo)}  dl={downloaded} skip={skipped} fail={failed}")

    print(f"\nDone. downloaded={downloaded}  skipped={skipped}  failed={failed}")
    print(f"Output: {OUT_DIR}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    {
        "fetch-csv": cmd_fetch_csv,
        "report": cmd_report,
        "filter-balanced": cmd_filter_balanced,
        "fetch-teams": cmd_fetch_teams,
    }.get(cmd, lambda: print(f"unknown command: {cmd}"))()
