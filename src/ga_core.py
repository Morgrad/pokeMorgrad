"""
ga_core.py — public face of the GA engine (implementation lives in src/ga/).

Evolves 6-mon teams against a pool of real top-cut teams, using a poke_env pilot
(VGCPilot vs the ladder-like opponent by default, see src/ga/config.py) to play
out battles for the fitness signal.

Entry point:
  run_islands(...)   multi-island GA with ring migration, stagnation restart,
                     and JSON checkpointing.            -> src/ga/engine.py

Where things live:
  src/ga/config.py      GAConfig (env + tuning knobs), FORMAT, UID_MAX, output dirs
  src/ga/genome.py      genome encoding, random genomes, mutation, crossover, pools
  src/ga/fitness.py     meta-weighted win rate (shared with src/eval.py)
  src/ga/evaluator.py   Evaluator: plays a genome vs opponents, early stop
  src/ga/population.py  Island (one sub-population) + ring migration
  src/ga/checkpoint.py  checkpoint / champion files
  src/ga/engine.py      run_islands
  src/showdown_server.py  probe / restart the local Showdown server

Vocabulary used throughout:
  genome       = list of 6 mon dicts {species, item, ability, nature, evs, moves}
  constraints  = {slot_idx: species_name} — "locked" slots that must hold a
                 given species and are never mutated/crossed away.
  fitness      = win rate of a genome vs a sampled slice of the opponent pool.

This module only re-exports: every name below existed here before the package
split and stays importable for run/, tools/, src/eval.py and the tests.
"""
from src import showdown_server
from src.ga import config as C
from src.ga import fitness as F
from src.ga.checkpoint import load_latest_checkpoint, save_checkpoint
from src.ga.engine import run_islands
from src.ga.genome import (
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
from src.ga.population import Island, _strip_species, ring_migrate

__all__ = [
    # driver
    "run_islands",
    # settings (values of src.ga.config.DEFAULT, read from the environment at import)
    "FORMAT", "UID_MAX", "CHECKPOINT_DIR", "CHAMPION_DIR",
    "BATTLE_TIMEOUT", "MIN_TURNS", "FITNESS_PILOT", "FITNESS_OPP", "META_WEIGHTS",
    "TRAIN_SAMPLE_SIZE", "EARLY_STOP_MIN_BATTLES", "EARLY_STOP_WIN_RATE",
    "SHOWDOWN_PORT", "SHOWDOWN_DIR",
    # genome
    "genome_to_text", "text_to_genome", "enforce_constraints", "build_random_genome",
    "filter_legal_genomes", "mutate", "crossover", "regional_pool", "heldout_pool",
    "_split_train_val", "_ITEMS", "_NATURES", "_REGIONAL_DIR", "_legal_items_for",
    "_BASE_SPECIES", "_SPECIES_BY_NAME", "_fresh_mon",
    # fitness
    "_fitness", "_opp_weight",
    # islands
    "Island", "ring_migrate", "_strip_species", "breed", "inject_immigrants",
    "count_unique_species",
    # checkpoints
    "save_checkpoint", "load_latest_checkpoint",
    # Showdown server
    "restart_showdown", "ensure_showdown", "_showdown_up",
]

FORMAT = C.FORMAT
UID_MAX = C.UID_MAX
CHECKPOINT_DIR = C.CHECKPOINT_DIR
CHAMPION_DIR = C.CHAMPION_DIR
BATTLE_TIMEOUT = C.DEFAULT.battle_timeout
MIN_TURNS = C.DEFAULT.min_turns
FITNESS_PILOT = C.DEFAULT.fitness_pilot
FITNESS_OPP = C.DEFAULT.fitness_opp
META_WEIGHTS = C.DEFAULT.meta_weights
TRAIN_SAMPLE_SIZE = C.DEFAULT.train_sample_size
EARLY_STOP_MIN_BATTLES = C.DEFAULT.early_stop_min_battles
EARLY_STOP_WIN_RATE = C.DEFAULT.early_stop_win_rate
SHOWDOWN_PORT = C.DEFAULT.showdown_port
SHOWDOWN_DIR = C.DEFAULT.showdown_dir


def _opp_weight(opp_text):
    """Meta weight of one opponent team under the GA's settings (GA_META_WEIGHTS)."""
    return F.opp_weight(opp_text, C.DEFAULT.meta_weights)


def _fitness(outcomes, opponents):
    """GA fitness: weighted win rate over the battles that returned a result; (fit, wins, valid_n)."""
    return F.weighted_fitness(outcomes, opponents, C.DEFAULT.meta_weights)


def count_unique_species(island):
    """Distinct base species on the island (see Island.unique_species)."""
    return island.unique_species()


def inject_immigrants(island, n):
    """Replace the `n` worst genomes with fresh random ones (see Island.replace_worst)."""
    return island.replace_worst(n)


def breed(island, immigration_rate=0.20):
    """Next generation of one island (see Island.breed)."""
    island.breed(immigration_rate)


def _showdown_up():
    return showdown_server.is_up(SHOWDOWN_PORT)


def restart_showdown(wait_s=60, tries=2):
    """Bounce the GA's Showdown server (SHOWDOWN_PORT); see showdown_server.restart."""
    return showdown_server.restart(SHOWDOWN_PORT, SHOWDOWN_DIR, wait_s=wait_s, tries=tries)


def ensure_showdown():
    """Make sure a server answers on SHOWDOWN_PORT; raise RuntimeError if it cannot be (re)started."""
    showdown_server.ensure(SHOWDOWN_PORT, SHOWDOWN_DIR)
