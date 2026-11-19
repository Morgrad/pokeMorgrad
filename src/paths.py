"""Single source of truth for repo paths.

Resolution order for REPO_ROOT:
  1. POKEMORGRAD_ROOT env var (if set and valid)
  2. Parent of this file's directory (src/../)

All other paths derive from REPO_ROOT via data_path / output_path / src_path.
Showdown dir is separate — SHOWDOWN_DIR env (default ~/pokemon-showdown).
"""
import os
from pathlib import Path


def _resolve_repo_root() -> Path:
    env = os.environ.get("POKEMORGRAD_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if not (p / "data").is_dir():
            raise RuntimeError(
                f"POKEMORGRAD_ROOT={p} does not look like the repo "
                f"(no data/ subdir)"
            )
        return p
    return Path(__file__).resolve().parent.parent


REPO_ROOT: Path = _resolve_repo_root()


def data_path(*parts) -> str:
    return str(REPO_ROOT / "data" / Path(*parts))


def output_path(*parts) -> str:
    return str(REPO_ROOT / "output" / Path(*parts))


def src_path(*parts) -> str:
    return str(REPO_ROOT / "src" / Path(*parts))


def showdown_dir() -> str:
    return os.environ.get(
        "SHOWDOWN_DIR",
        os.path.expanduser("~/pokemon-showdown"),
    )


def showdown_port(env=None) -> int:
    """Port of the local Showdown server: env SHOWDOWN_PORT, default 8000.

    The single place SHOWDOWN_PORT is parsed. Read once at import by
    src/player_factory.py (battle sockets), src/ga/config.py (GAConfig.showdown_port:
    the port the GA probes and restarts) and run/ga_island.py (log header), so set it
    before Python starts. `env` is a mapping for tests (os.environ by default).
    """
    env = os.environ if env is None else env
    return int(env.get("SHOWDOWN_PORT", "8000"))
