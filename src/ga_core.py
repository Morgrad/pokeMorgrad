"""
ga_core.py — GA engine for counter-meta VGC team search.

Evolves 6-mon teams against a pool of real top-cut teams, using a poke_env
pilot (VGCPilot vs the ladder-like opponent by default, see FITNESS_PILOT) to play out battles for the fitness signal.

Entry point:
  run_islands(...)   multi-island GA with ring migration, stagnation restart,
                     and JSON checkpointing.

Vocabulary used throughout:
  genome       = list of 6 mon dicts {species, item, ability, nature, evs, moves}
  constraints  = {slot_idx: species_name} — "locked" slots that must hold a
                 given species and are never mutated/crossed away.
  fitness      = win rate of a genome vs a sampled slice of the opponent pool.

Everything here is CPU/async orchestration; the only heavy dependency is
poke_env driving a local Showdown server (see restart_showdown / SHOWDOWN_PORT).
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import random
import subprocess
import time
import urllib.request

from src import battle as B
from src import meta_weights as MW
from src import regmc_db as DB
from src.ga_genome import (
    _BASE_SPECIES,
    _ITEMS,
    _NATURES,
    _REGIONAL_DIR,
    _SPECIES_BY_NAME,
    _fresh_mon,
    _legal_items_for,
    _split_train_val,
    build_random_genome,
    crossover,
    enforce_constraints,
    filter_legal_genomes,
    genome_to_text,
    heldout_pool,
    mutate,
    regional_pool,
    text_to_genome,
)
from src.paths import output_path, showdown_dir

__all__ = [
    "genome_to_text",
    "text_to_genome",
    "enforce_constraints",
    "build_random_genome",
    "filter_legal_genomes",
    "mutate",
    "crossover",
    "regional_pool",
    "heldout_pool",
    "_split_train_val",
    "_ITEMS",
    "_NATURES",
    "_REGIONAL_DIR",
    "_legal_items_for",
]

FORMAT = "gen9championsvgc2026regmc"
  # canonical format registry; battle.py callers pass this in
UID_MAX = 10**9   # upper bound of the random per-battle account id space

# -----------------------------------------------------------------------------
# Tuning knobs — every value here was hand-tuned against the Reg M-C pool.
# Grouped up top so a reviewer can find and adjust them without spelunking
# through the engine body. Changing one changes GA *behavior*, not correctness.
# -----------------------------------------------------------------------------



# --- Battle harness ---
BATTLE_TIMEOUT = 20     # seconds before a battle is abandoned as hung (returns None, not a loss).
MIN_TURNS = 3           # Battles ending < 3 turns are almost always a Showdown desync/forfeit,
                        # not a real game — discard so they don't poison the fitness signal.
# (The retry-uid stride lives in src/battle.py now — RETRY_STRIDE there.)
# Who plays in the fitness battles. Our side: "vgc" = VGCPilot (turn_sim on by default: +4.5 pts over the
# plain heuristic in paired runs); the opponent: "ladder" = heuristic + Protect / Fake Out at replay rates.
# GA_PILOT=heuristic GA_OPP=heuristic reproduces the pre-2026-10-16 environment (scores are NOT comparable).
FITNESS_PILOT = os.environ.get("GA_PILOT", "vgc")
FITNESS_OPP = os.environ.get("GA_OPP", "ladder")
# Fitness = win rate weighted by how much the ladder plays each opponent team (src/meta_weights.py,
# data/species_ladder_usage.json). GA_META_WEIGHTS=0 gives the plain win rate.
META_WEIGHTS = os.environ.get("GA_META_WEIGHTS", "1") == "1"

# Per-generation opponent sample size. When the train pool is larger than
# this, each generation samples TRAIN_SAMPLE_SIZE opponents from the full
# pool. Keeps per-gen fitness complexity bounded as the pool grows.
# Override via GA_TRAIN_SAMPLE env var.
TRAIN_SAMPLE_SIZE = int(os.environ.get("GA_TRAIN_SAMPLE", "250"))

# --- Early-stop ---
# A genome plays EARLY_STOP_MIN_BATTLES first; if that head score is below
# EARLY_STOP_WIN_RATE we skip the tail. Statistically: at 50 battles the Wilson
# 95% CI is ~±10 pts, so a genome truly at 30%+ has <1% chance of showing <15%.
# The abort catches the bottom third of a generation at negligible false-positive
# risk and saves ~85% of the wall time for those genomes.
EARLY_STOP_MIN_BATTLES = 50     # only meaningful when the pool is larger than this.
EARLY_STOP_WIN_RATE = 0.15      # abort when head score < this.

# Species with no meta_items.json entry pick from CANONICAL_ITEMS ∩ legal.
# Species WITH an entry pick only from that entry (usage-weighted).

# Priority-ordered: the first one in the list that a species learns gets used.

# Turn-1 disruption / redirection; first learnable wins.
































































# =============================================================================
# BATTLE
# =============================================================================
# The battle harness itself (player construction, timeout, retry, websocket
# cleanup) lives in src/battle.py, shared with eval. The GA passes this module
# semaphore, FORMAT, and its own knobs (BATTLE_TIMEOUT, MIN_TURNS) into it.
_SEM = None   # module-global concurrency gate; set by run_islands.


def _log_score(idx, total, fit, wins, valid_n, mons, tag=""):
    """One-line progress print. `tag` is an optional suffix like 'early-abort'."""
    ts = time.strftime("%H:%M:%S")
    species = ' / '.join(m['species'] for m in mons)
    suffix = f"  {tag}" if tag else ""
    print(f"  [{ts}] {idx+1:>2}/{total}  {fit*100:5.1f}%  ({wins}W/{valid_n}){suffix}  {species}",
          flush=True)


_OPP_WEIGHT_CACHE = {}


def _opp_weight(opp_text):
    if not META_WEIGHTS:
        return 1.0
    w = _OPP_WEIGHT_CACHE.get(opp_text)
    if w is None:
        w = _OPP_WEIGHT_CACHE[opp_text] = MW.team_weight(opp_text)
    return w


def __count_valid_outcomes(outcomes):
    """Count valid (non-None) outcomes from battles."""
    valid = [o for o in outcomes if o is not None]
    return len(valid), sum(valid)

def __calculate_win_rate(outcomes, opponents):
    """Calculate weighted win rate using meta weights."""
    return MW.weighted_rate(outcomes, [_opp_weight(t) for t in opponents])

def _fitness(outcomes, opponents):
    """Weighted win rate over the battles that returned a result; (fit, wins, valid_n)."""
    valid_count, wins = __count_valid_outcomes(outcomes)
    if valid_count == 0:
        return 0.0, 0, 0

    win_rate = __calculate_win_rate(outcomes, opponents)
    return win_rate, wins, valid_count


async def evaluate(mons, opponents, idx, total, save_filter=None, save_callback=None):
    """Fitness = win rate of one genome across all `opponents`, run concurrently.

    Two-phase: play EARLY_STOP_MIN_BATTLES first; if that head score is below
    EARLY_STOP_WIN_RATE, skip the tail and return the partial score. Partial (not
    0.0) so the genome still ranks correctly against other bad genomes — useful
    in early generations when the whole population is weak.

    Invalid genomes score 0.0 immediately. Battles returning None (timeout /
    desync) are dropped from the denominator, not counted as losses.

    Small pools (<= EARLY_STOP_MIN_BATTLES, e.g. smoke tests) skip the split and
    play everything in one batch.
    """
    text = genome_to_text(mons)
    ok, errs = DB.validate_team(text)
    if not ok:
        print(f"  [{idx+1}/{total}] INVALID: {errs[:2]}")
        return 0.0

    async def _battle_with_progress(opp, battle_num):
        """Run a single battle and print progress."""
        result = await B.run_battle(text, opp, random.randint(1, UID_MAX), _SEM, FORMAT,
                                    pilot=FITNESS_PILOT, timeout=BATTLE_TIMEOUT,
                                    min_turns=MIN_TURNS, opp_pilot=FITNESS_OPP,
                                    save_filter=save_filter, save_callback=save_callback)
        return result

    # Small pools: no early-stop possible, one batch.
    if len(opponents) <= EARLY_STOP_MIN_BATTLES:
        outcomes = await asyncio.gather(*[_battle_with_progress(o, i) for i, o in enumerate(opponents)])
        fit, wins, valid_n = _fitness(outcomes, opponents)
        if not valid_n:
            return 0.0
        _log_score(idx, total, fit, wins, valid_n, mons)
        print()  # New line at end
        return fit

    # Phase 1 — head batch.
    head, tail = opponents[:EARLY_STOP_MIN_BATTLES], opponents[EARLY_STOP_MIN_BATTLES:]

    # Launch all head battles as tasks
    head_tasks = [_battle_with_progress(o, i) for i, o in enumerate(head)]
    head_task_objects = [asyncio.create_task(task) for task in head_tasks]

    head_results = []
    head_wins = 0
    head_n = 0
    pending = set(head_task_objects)

    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            result = task.result()
            head_results.append(result)
            if result is not None:
                head_n += 1
                if result == 1:
                    head_wins += 1
        if len(head_results) >= EARLY_STOP_MIN_BATTLES and head_n > 0:
            head_fit, _, _ = _fitness(head_results, head[:len(head_results)])
            if head_fit < EARLY_STOP_WIN_RATE:
                for task in pending:
                    task.cancel()
                _log_score(idx, total, head_fit, head_wins, head_n, mons, tag="early-abort")
                print()
                return head_fit

    # Phase 2 — tail batch.
    # Launch all tail battles as tasks
    tail_tasks = [_battle_with_progress(o, i + len(head)) for i, o in enumerate(tail)]
    tail_task_objects = [asyncio.create_task(task) for task in tail_tasks]

    # Collect results with cancellation support
    tail_results = []

    # Wait for all tail tasks to complete (no cancellation needed as we're not implementing that complex logic)
    # The original code was already doing this correctly, so I'll keep the simpler approach for now
    # but maintain the progress logging and early abort logic in head phase.
    for task in asyncio.as_completed(tail_task_objects):
        result = await task
        tail_results.append(result)

    # Combine head and tail results
    all_results = list(head_results) + list(tail_results)
    fit, wins, valid_n = _fitness(all_results, opponents)
    if not valid_n:
        return 0.0
    _log_score(idx, total, fit, wins, valid_n, mons)
    print()  # New line at end
    return fit


# =============================================================================
# ISLAND MODEL
# =============================================================================
# The production GA: N semi-isolated populations ("islands"), each optionally
# locking a different species, evolving in parallel. Top genomes migrate around a
# ring every few generations; stagnant islands restart their worst half. State is
# JSON-checkpointed every generation so a multi-hour run survives a crash/restart.
CHECKPOINT_DIR = output_path("checkpoints", "v6")
CHAMPION_DIR = output_path("champions")
SHOWDOWN_DIR = showdown_dir()
SHOWDOWN_PORT = int(os.environ.get("SHOWDOWN_PORT", "8000"))




class Island:
    """One GA sub-population plus its evolve/checkpoint bookkeeping.

    constraints  = {slot: species} locked for this island (may be empty).
    best_ever    = all-time best genome seen here (survives stagnation restarts).
    stagnation   = generations since best_ever improved (drives the restart).
    to_dict/from_dict are the on-disk checkpoint shape (see save_checkpoint).
    """

    def __init__(self, name, constraints=None, seed_paths=None):
        self.name = name
        self.constraints = constraints or {}
        self.population = []
        self.fitness = []
        self.best_ever = {"fit": -1, "genome": None, "gen": None}
        # best_val_ever = best genome by validation-slice score (champion source)
        self.best_val_ever = {"fit": -1, "genome": None, "gen": None}
        self.stagnation = 0
        self.history = []
        self.seed_paths = seed_paths or []

    def init_population(self, size):
        """Fill the population to `size`: seed files first, then random genomes.

        Runs the legality gate once, then tops up again (the gate can drop
        genomes it couldn't legalize). The final list may still be short if the
        roster can't produce `size` legal genomes, which is acceptable.
        """
        self.population = []
        for path in self.seed_paths:
            if os.path.exists(path):
                try:
                    g = text_to_genome(open(path).read())
                    if g:
                        g = enforce_constraints(g, self.constraints)
                        self.population.append(g)
                        print(f"  [{self.name}] seeded with {os.path.basename(path)}")
                except Exception:
                    pass
        while len(self.population) < size:
            g = build_random_genome(self.constraints)
            if g:
                self.population.append(g)
        self.population = filter_legal_genomes(self.population, self.constraints)
        while len(self.population) < size:
            g = build_random_genome(self.constraints)
            if g:
                self.population.append(g)
        self.fitness = [0.0] * len(self.population)

    def to_dict(self):
        """Serialize to the JSON checkpoint shape (constraint keys → str for JSON)."""
        return {
            "name": self.name,
            "constraints": {str(k): v for k, v in self.constraints.items()},
            "population": self.population,
            "fitness": self.fitness,
            "best_ever": self.best_ever,
            "best_val_ever": self.best_val_ever,
            "stagnation": self.stagnation,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, d):
        """Rebuild an Island from a checkpoint dict (constraint keys → int again)."""
        isl = cls(d["name"], {int(k): v for k, v in d.get("constraints", {}).items()})
        isl.population = d["population"]
        isl.fitness = d.get("fitness", [0.0] * len(isl.population))
        isl.best_ever = d["best_ever"]
        isl.best_val_ever = d.get("best_val_ever",
                                   {"fit": -1, "genome": None, "gen": None})
        isl.stagnation = d.get("stagnation", 0)
        isl.history = d.get("history", [])
        return isl


def count_unique_species(island):
    """Count distinct base species across the island — the diversity metric."""
    seen = set()
    for g in island.population:
        if not g:
            continue
        for m in g:
            sp = _SPECIES_BY_NAME.get(m["species"])
            if sp:
                seen.add(DB.norm(sp["baseSpecies"]))
    return len(seen)


def inject_immigrants(island, n):
    """Replace the `n` worst genomes with fresh random ones. Returns count added.

    Diversity rescue: called when an island's unique-species count falls below
    the floor. Targets the lowest-fitness slots so we never evict a contender.
    """
    if not island.fitness:
        return 0
    ranked = sorted(range(len(island.population)), key=lambda i: island.fitness[i])
    added = 0
    for idx in ranked[:n]:
        fresh = build_random_genome(island.constraints)
        if fresh:
            island.population[idx] = fresh
            island.fitness[idx] = 0.0
            added += 1
    return added


def _strip_species(genome, species_set, constraints):
    """Replace any mon whose species is in species_set with a fresh random mon.
    Preserves species + item clauses. Never touches constrained slots.
    """
    if not genome:
        return genome
    stripped = copy.deepcopy(genome)

    # Build the set of base species we must avoid duplicating (excluding
    # the slots we're about to replace).
    def _bases(exclude_slots=()):
        s = set()
        for i, m in enumerate(stripped):
            if i in exclude_slots or m is None:
                continue
            sp = _SPECIES_BY_NAME.get(m.get("species"))
            if sp:
                s.add(DB.norm(sp["baseSpecies"]))
        return s

    for slot, mon in enumerate(stripped):
        if slot in constraints:
            continue
        if mon and mon.get("species") in species_set:
            used_items = {m["item"] for m in stripped
                          if m and m.get("item") and m is not mon}
            used_bases = _bases(exclude_slots=(slot,))
            cands = [s["name"] for s in _BASE_SPECIES
                     if s["name"] not in species_set
                     and DB.norm(s["baseSpecies"]) not in used_bases
                     and len(s["moves"]) >= 4]
            if not cands:
                continue
            new_sp = random.choice(cands)
            fresh = _fresh_mon(new_sp, used_items)
            if fresh:
                stripped[slot] = fresh
    return stripped


def ring_migrate(islands, n=2):
    """Copy each island's top `n` genomes into the next island's worst `n` slots.

    Migration runs around a ring (island i receives from island i-1). Incoming
    genomes are constraint-enforced for the destination, and any species that is
    locked on the SOURCE but not here is stripped — see the inline note below for
    the diversity-collapse bug that motivated it.
    """
    tops = []
    for isl in islands:
        if not isl.fitness:
            tops.append([])
            continue
        ranked = sorted(range(len(isl.population)), key=lambda i: -isl.fitness[i])
        tops.append([copy.deepcopy(isl.population[i]) for i in ranked[:n]])
    for i, isl in enumerate(islands):
        incoming = tops[(i - 1) % len(islands)]
        if not incoming:
            continue
        ranked = sorted(range(len(isl.population)), key=lambda j: isl.fitness[j])
        for j, genome in enumerate(incoming):
            if j >= len(ranked):
                break
            fixed = enforce_constraints(genome, isl.constraints)
            # Strip any species that is a lock on the SOURCE island but
            # not locked here. Without this, Umbreon leaks from island A
            # into B/C and diversity collapses over generations.
            src_constraints = islands[(i - 1) % len(islands)].constraints
            foreign_locks = set(src_constraints.values()) - set(isl.constraints.values())
            if foreign_locks:
                fixed = _strip_species(fixed, foreign_locks, isl.constraints)
            isl.population[ranked[-1 - j]] = fixed
            isl.fitness[ranked[-1 - j]] = 0.0


def _showdown_up():
    try:
        urllib.request.urlopen(f"http://localhost:{SHOWDOWN_PORT}", timeout=2)
        return True
    except Exception:
        return False


def restart_showdown(wait_s=60, tries=2):
    """Kill and relaunch the local Showdown server, waiting for it to come back.

    Called periodically mid-run because the Node server leaks memory/sockets over
    thousands of battles. Hard-kills any process on the port, relaunches detached
    with --no-security (local-only, trusted), then polls the HTTP port for up to
    `wait_s` seconds (a server a few hours old has taken >30 s to answer). Retries
    the whole kill+launch up to `tries` times. Returns True once it answers, False
    if it never came up.
    """
    for attempt in range(1, tries + 1):
        print(f"  [showdown] restarting on :{SHOWDOWN_PORT} (attempt {attempt}/{tries})...")
        subprocess.run(["pkill", "-9", "-f", f"pokemon-showdown start {SHOWDOWN_PORT}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        subprocess.Popen(
            ["node", "pokemon-showdown", "start", str(SHOWDOWN_PORT), "--no-security"],
            cwd=SHOWDOWN_DIR,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(wait_s):
            if _showdown_up():
                print("  [showdown] back up")
                return True
            time.sleep(1)
    print("  [showdown] FAILED")
    return False


def ensure_showdown():
    """Make sure a server answers on SHOWDOWN_PORT; raise if it cannot be (re)started.

    The island exits non-zero, so run/ga_parallel.sh respawns it from the last checkpoint
    instead of the GA scoring every genome 0.0 against a dead server.
    """
    if not _showdown_up() and not restart_showdown():
        raise RuntimeError(f"Showdown on :{SHOWDOWN_PORT} is not answering and could not be restarted")


def save_checkpoint(generation, islands, run_id="run1"):
    """Write a full-run checkpoint and prune old ones, keeping every 5th gen.

    Retention: the latest checkpoint is always kept; older ones survive only if
    their generation is a multiple of 5. This bounds disk use over a long run
    while still leaving periodic restore points. Returns the path written.
    """
    base = os.path.join(CHECKPOINT_DIR, run_id)
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"gen_{generation:04d}.json")
    state = {
        "generation": generation,
        "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
        "islands": [isl.to_dict() for isl in islands],
    }
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
    all_ckpts = sorted(f for f in os.listdir(base) if f.startswith("gen_"))
    for f in all_ckpts[:-1]:   # never prune the newest
        try:
            gen = int(f.split("_")[1].split(".")[0])
            if gen % 5 != 0:   # keep multiples of 5 as periodic restore points
                os.remove(os.path.join(base, f))
        except Exception:
            pass
    return path


def load_latest_checkpoint(run_id="run1"):
    """Path of the highest-numbered checkpoint for a run, or None if none exist."""
    base = os.path.join(CHECKPOINT_DIR, run_id)
    if not os.path.isdir(base):
        return None
    files = sorted(f for f in os.listdir(base) if f.startswith("gen_"))
    if not files:
        return None
    return os.path.join(base, files[-1])


def breed(island, immigration_rate=0.20):
    """Produce the next generation of one island: elites + crossovers + immigrants.

    Keeps the top third (≥2) as elites, then fills the rest by either injecting a
    fresh random genome (probability immigration_rate, for ongoing diversity) or
    breeding a mutated crossover of two elites. The new population is legality-
    gated and topped back up to the original size. Fitness resets to zero.
    """
    n = len(island.population)
    if n < 4:
        return
    ranked = sorted(range(n), key=lambda i: -island.fitness[i])
    n_elites = max(2, n // 3)
    elites = [enforce_constraints(copy.deepcopy(island.population[i]), island.constraints)
              for i in ranked[:n_elites]]
    new_pop = list(elites)
    while len(new_pop) < n:
        if random.random() < immigration_rate:
            fresh = build_random_genome(island.constraints)
            if fresh:
                new_pop.append(fresh)
            continue
        p1, p2 = random.sample(elites, 2)
        child = mutate(crossover(p1, p2, island.constraints), island.constraints)
        new_pop.append(child)
    new_pop = filter_legal_genomes(new_pop, island.constraints)
    while len(new_pop) < n:
        fresh = build_random_genome(island.constraints)
        if fresh:
            new_pop.append(fresh)
    island.population = new_pop[:n]
    island.fitness = [0.0] * len(island.population)


async def _eval_on_subset(genome, opponents, verbose=False):
    """One-shot fitness on a specific opponent list. No early-stop, no retry."""
    text = genome_to_text(genome)
    ok, errs = DB.validate_team(text)
    if not ok:
        return 0.0
    tasks = [B.run_battle(text, o, random.randint(1, UID_MAX), _SEM, FORMAT,
                          pilot=FITNESS_PILOT, timeout=BATTLE_TIMEOUT,
                          min_turns=MIN_TURNS, opp_pilot=FITNESS_OPP)
             for o in opponents]
    outcomes = await asyncio.gather(*tasks)
    return _fitness(outcomes, opponents)[0]


async def run_islands(
    island_specs,
    pop_per_island=10,
    generations=999,
    battles_per_genome=800,
    concurrency=int(os.environ.get("GA_CONCURRENCY", "3")),
    immigration_rate=0.20,
    stagnation_limit=5,
    diversity_floor=15,
    migration_every=5,
    showdown_restart_every=10,
    max_hours=None,
    run_id="run1",
    save_filter=None,
    save_callback=None,
):
    """Production GA driver: evolve N islands with migration, restart, checkpoints.

    Resumes from the latest checkpoint for `run_id` if one exists, else builds
    islands from island_specs. Each generation, per island: evaluate fitness,
    track the all-time best, rescue diversity (inject_immigrants) or escape local
    optima (stagnation restart), then breed. Every `migration_every` gens the ring
    migrates; every `showdown_restart_every` gens the server is bounced. Stops at
    `generations` or when `max_hours` elapses. Writes a champion file per island.
    """
    global _SEM
    _SEM = asyncio.Semaphore(concurrency)

    if META_WEIGHTS:   # fail now, not on the first evaluation
        try:
            MW.load_usage()
        except (OSError, ValueError, KeyError) as e:
            raise RuntimeError(f"meta-weight usage file {MW.USAGE_PATH} unreadable ({e}); "
                               "run tools/build_meta_weights.py or set GA_META_WEIGHTS=0") from e
    ensure_showdown()

    islands = []
    start_gen = 0
    ckpt = load_latest_checkpoint(run_id)
    if ckpt:
        try:
            state = json.load(open(ckpt))
            islands = [Island.from_dict(d) for d in state["islands"]]
            start_gen = state["generation"]
            print(f"RESUMED from {ckpt} at gen {start_gen}")
        except Exception as e:
            print(f"checkpoint load failed ({e}); fresh start")
            islands = []

    if not islands:
        print("Initializing islands...")
        for spec in island_specs:
            isl = Island(
                spec["name"],
                constraints=spec.get("constraints", {}),
                seed_paths=spec.get("seed_paths", []),
            )
            isl.init_population(pop_per_island)
            islands.append(isl)
            print(f"  [{isl.name}] {len(isl.population)} genomes, "
                  f"constraints={isl.constraints}")

    print(f"=== GA: {len(islands)} islands × {pop_per_island} ===")
    print(f"Gens {start_gen}..{generations}, {battles_per_genome} battles/genome")

    opp_pool = regional_pool()
    train_pool, val_pool = _split_train_val(opp_pool)
    print(f"Fitness environment: our pilot={FITNESS_PILOT}  opponent pilot={FITNESS_OPP}  "
          f"meta-weighted={META_WEIGHTS}")
    print(f"Fitness pool: {len(train_pool)} teams   "
          f"Validation slice: {len(val_pool)} teams")
    t0 = time.time()
    time_budget_seconds = (max_hours * 3600) if max_hours else None

    for gen in range(start_gen, generations):
        if time_budget_seconds and (time.time() - t0) > time_budget_seconds:
            print(f"\n=== TIME BUDGET REACHED ({max_hours}h) at gen {gen} ===")
            break
        if gen > start_gen and (gen - start_gen) % showdown_restart_every == 0 and gen > 0:
            if not restart_showdown():
                raise RuntimeError(f"Showdown on :{SHOWDOWN_PORT} did not come back after a restart")

        print(f"\n[{time.strftime('%H:%M:%S')}] === GEN {gen+1}/{generations}  "
              f"({(time.time()-t0)/60:.1f} min) ===")

        for isl in islands:
            n_sample = min(battles_per_genome, TRAIN_SAMPLE_SIZE, len(train_pool))
            gen_opps = random.sample(train_pool, n_sample)
            fits = await asyncio.gather(*[
                evaluate(g, gen_opps, i, len(isl.population), save_filter=save_filter, save_callback=save_callback)
                for i, g in enumerate(isl.population)
            ])
            isl.fitness = list(fits)
            best_idx = max(range(len(fits)), key=lambda i: fits[i])
            gen_best = fits[best_idx]

            if gen_best > isl.best_ever["fit"]:
                isl.best_ever = {
                    "fit": gen_best,
                    "genome": copy.deepcopy(isl.population[best_idx]),
                    "gen": gen + 1,
                }
                isl.stagnation = 0
                print(f"  [{isl.name}] NEW ALL-TIME (train): {gen_best*100:.1f}%")
            else:
                isl.stagnation += 1

            # Champion selection: evaluate this generation's training-best on
            # the held-back validation slice. Champions come from
            # best_val_ever, not best_ever — Island B (2026-10-13) showed
            # the training best overfits by ~10 points on held-out.
            val_fit = await _eval_on_subset(isl.population[best_idx], val_pool)
            if val_fit > isl.best_val_ever["fit"]:
                isl.best_val_ever = {
                    "fit": val_fit,
                    "genome": copy.deepcopy(isl.population[best_idx]),
                    "gen": gen + 1,
                }
                print(f"  [{isl.name}] NEW VAL BEST: {val_fit*100:.1f}% "
                      f"(train {gen_best*100:.1f}%)")

            isl.history.append({
                "gen": gen + 1,
                "best": gen_best,
                "avg": sum(fits) / len(fits) if fits else 0,
                "all_time": isl.best_ever["fit"],
                "stag": isl.stagnation,
            })

            uniq = count_unique_species(isl)
            if uniq < diversity_floor:
                added = inject_immigrants(isl, 3)
                print(f"  [{isl.name}] diversity low ({uniq}): injected {added}")

            if isl.stagnation >= stagnation_limit:
                n_restart = len(isl.population) // 2
                ranked = sorted(range(len(isl.fitness)), key=lambda i: isl.fitness[i])
                for j in ranked[:n_restart]:
                    fresh = build_random_genome(isl.constraints)
                    if fresh:
                        isl.population[j] = fresh
                        isl.fitness[j] = 0.0
                print(f"  [{isl.name}] STAGNATION: restarted {n_restart}")
                isl.stagnation = 0

            if gen < generations - 1:
                breed(isl, immigration_rate=immigration_rate)

            print(f"  [{isl.name}] gen {gen+1}: best={gen_best*100:5.1f}%  "
                  f"all-time={isl.best_ever['fit']*100:5.1f}%  stag={isl.stagnation}  "
                  f"uniq={uniq}")

        if (gen + 1) % migration_every == 0 and gen < generations - 1:
            ring_migrate(islands, n=2)
            print(f"  >> migration done at gen {gen+1}")

        ckpt_path = save_checkpoint(gen + 1, islands, run_id)
        print(f"  >> checkpoint: {os.path.basename(ckpt_path)}")

    os.makedirs(CHAMPION_DIR, exist_ok=True)
    print("\n=== DONE ===")
    for isl in islands:
        # Primary champion = train best (val-selection was dropped, see STATE.md);
        # fall back to the val best only if no train genome exists.
        best = isl.best_ever if isl.best_ever["genome"] else isl.best_val_ever
        label = "train" if isl.best_ever["genome"] else "val"
        if best["genome"]:
            path = os.path.join(CHAMPION_DIR, f"ga_{run_id}_island_{isl.name}.txt")
            open(path, "w").write(genome_to_text(best["genome"]))
            print(f"  [{isl.name}] champion ({label}): {best['fit']*100:.1f}% "
                  f"(train best {isl.best_ever['fit']*100:.1f}%) -> {path}")
        if isl.best_ever["genome"]:
            path = os.path.join(
                CHAMPION_DIR, f"ga_{run_id}_island_{isl.name}_train.txt")
            open(path, "w").write(genome_to_text(isl.best_ever["genome"]))
            print(f"  [{isl.name}] champion (train): "
                  f"{isl.best_ever['fit']*100:.1f}% -> {path}")
