"""Rules every genome must satisfy before it enters a population.

- filter_legal_genomes: the Showdown legality gate (batched validator calls; illegal
  genomes are rebuilt up to MAX_REBUILD_TRIES times, then dropped), followed by
- _enforce_composition: at least one Protect user and one Fake Out / redirection user.
- enforce_constraints: locked slots ({slot: species}) hold their mandated species.

Split out of src/ga/genome.py on 2026-11-18 (code unchanged).
"""
import copy
import random

from src import showdown_validator as SV
from src.ga.genome import _SPECIES_BY_NAME, _fresh_mon, build_random_genome, genome_to_text
from src.ga.operators import repair_clauses

# --- Legality gate ---
MAX_REBUILD_TRIES = 20  # Illegal genome: rebuild from scratch up to N times before dropping it.

# --- Team realism constraints ---
# The GA optimizes for the heuristic pilot, which ignores items, Protect
# timing, and Fake Out priority. Left unconstrained, it produces champions
# full of dead items and no tactical moves. These constraints make champions
# look like top-cut teams without touching the model or the pilot.
PROTECT_MOVES = (
    "Protect", "Detect", "Spiky Shield", "King's Shield",
    "Baneful Bunker", "Silk Trap", "Burning Bulwark",
)

FAKEOUT_MOVES = ("Fake Out", "Follow Me", "Rage Powder")

# =============================================================================
# TEAM REALISM CONSTRAINTS
# =============================================================================
def _force_move_on_slot(genome, slot, candidate_moves):
    """Try to replace one of slot's moves with the first learnable candidate.

    Returns True if the swap succeeded, False if no candidate is learnable by
    that species. Preserves species identity; item/EV/nature untouched.
    """
    mon = genome[slot]
    sp = _SPECIES_BY_NAME.get(mon["species"])
    if not sp:
        return False
    learnable = [mv for mv in candidate_moves if mv in sp["moves"]]
    if not learnable:
        return False
    pick = learnable[0]
    if pick in mon["moves"]:
        return False  # already has it, nothing to do
    # Replace a move that isn't Protect-family and isn't the candidate
    for i, mv in enumerate(mon["moves"]):
        if mv not in PROTECT_MOVES and mv not in FAKEOUT_MOVES:
            mon["moves"][i] = pick
            return True
    # All 4 moves are Protect/FakeOut family — replace slot 0 anyway
    mon["moves"][0] = pick
    return True

def _enforce_composition(genome):
    """Ensure team has Protect coverage and turn-1 disruption.

    Soft constraints: if no mon on the team can learn the required move, the
    genome passes through unchanged. Idempotent: a genome that already has
    the coverage gets no edits.
    """
    if not genome or len(genome) != 6:
        return genome

    # --- Protect coverage ---
    has_protect = any(
        any(mv in PROTECT_MOVES for mv in (m.get("moves") or []))
        for m in genome if m
    )
    if not has_protect:
        # Try slots in a shuffled order so different genomes get different
        # Protect users — avoids every champion looking identical.
        slots = list(range(6))
        random.shuffle(slots)
        for slot in slots:
            if _force_move_on_slot(genome, slot, PROTECT_MOVES):
                break

    # --- Fake Out / redirection coverage ---
    has_fakeout = any(
        any(mv in FAKEOUT_MOVES for mv in (m.get("moves") or []))
        for m in genome if m
    )
    if not has_fakeout:
        slots = list(range(6))
        random.shuffle(slots)
        for slot in slots:
            if _force_move_on_slot(genome, slot, FAKEOUT_MOVES):
                break

    return genome

# =============================================================================
# SHOWDOWN LEGALITY GATE
# =============================================================================
def filter_legal_genomes(genomes, constraints):
    """Return only Showdown-legal genomes, rebuilding invalid ones in place.

    Each genome is validated by the real Showdown team validator (via SV). An
    invalid genome is replaced by a freshly built one, retried up to
    MAX_REBUILD_TRIES times; if none of the rebuilds pass, that slot is simply
    dropped (the population is topped back up by the caller). Output length may
    therefore be < len(genomes), and survivors keep their input order.

    Batched to cut subprocess spawns: SV.check_teams validates a whole list in a
    single Showdown process, so instead of one validator call per rebuild attempt
    (worst case n + MAX_REBUILD_TRIES·bad spawns per generation) we validate by
    *attempt index* — one batched call for the initial population, then one per
    rebuild round over only the still-failing slots, worst case
    MAX_REBUILD_TRIES+1 calls total.

    Equivalence note: initially-legal genomes pass through byte-identical and in
    order. Rebuilt genomes are random either way; batching consumes the RNG
    round-major instead of per-genome, so a specific replacement's identity can
    differ from the old path — but the per-genome pass/fail, the input ordering,
    and the MAX_REBUILD_TRIES-per-genome cap (a None build still burns a try) are
    preserved exactly.
    """
    # result[i] holds the legal genome for input slot i (original or a rebuild),
    # or None if that slot was dropped. Reassembled in input order at the end.
    result = [None] * len(genomes)
    verdicts = SV.check_teams([genome_to_text(g) for g in genomes])

    # Slots still needing a legal replacement, each with its remaining try budget.
    pending = {}
    for i, (g, (ok, _msg)) in enumerate(zip(genomes, verdicts)):
        if ok:
            result[i] = g
        else:
            pending[i] = MAX_REBUILD_TRIES

    while pending:
        # One attempt for every still-failing slot. Building consumes a try even
        # when build_random_genome returns None (mirrors the original loop, where
        # a None fresh still burned one of the MAX_REBUILD_TRIES iterations).
        fresh_by_idx = {}
        for i in list(pending):
            pending[i] -= 1
            fresh = build_random_genome(constraints)
            if fresh is not None:
                fresh_by_idx[i] = fresh

        # Validate this round's successfully-built candidates in one batched call.
        if fresh_by_idx:
            idxs = list(fresh_by_idx)
            round_verdicts = SV.check_teams([genome_to_text(fresh_by_idx[i]) for i in idxs])
            for i, (ok2, _msg) in zip(idxs, round_verdicts):
                if ok2:
                    result[i] = fresh_by_idx[i]
                    del pending[i]

        # Drop any slot that has exhausted its attempts without a legal rebuild.
        for i in list(pending):
            if pending[i] <= 0:
                del pending[i]

    legal = [g for g in result if g is not None]
    # Apply team-realism constraints once, on every genome that leaves the
    # gate. This is the single choke point shared by init_population and breed,
    # so nothing enters the population unconstrained.
    for g in legal:
        _enforce_composition(g)
    return legal

def enforce_constraints(genome, constraints):
    """Rebuild any locked slot whose species doesn't match, then repair the species /
    item clauses (operators.repair_clauses). Returns a new genome.

    The clause repair was added 2026-11-18 (refactor B2): a genome from another island
    (ring_migrate) or a seed file that already held the locked species in a free slot
    came out with that species twice and scored 0.0 as INVALID. For a genome that
    already obeys its locks and clauses (elites, the baseline seed) nothing changes and
    no random number is drawn."""
    if not constraints or not genome:
        return genome
    g = copy.deepcopy(genome)
    used_items = {m["item"] for m in g if m and m.get("item")}
    for slot, want in constraints.items():
        current = g[slot].get("species") if slot < len(g) else None
        if current != want:
            mon = _fresh_mon(want, used_items)
            if mon and slot < len(g):
                g[slot] = mon
                used_items.add(mon["item"])
    if len(g) == 6 and all(g):
        repair_clauses(g, constraints)
    return g
