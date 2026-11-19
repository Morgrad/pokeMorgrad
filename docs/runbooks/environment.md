# Host environment

The machines this project runs on (Windows 11 + WSL2 Fedora 42), the AMD 7900 XTX / ROCm setup,
virtualenvs, Python and key dependency versions, Node / Showdown, the Windows Terminal paste-limit
workaround, and how to share the GPU with a local coding LLM. Read it when setting up a host, when
torch or ROCm misbehaves, or before running GPU work next to the LLM.

Last verified against code: 2026-11-18

## Hosts

| Item | GPU workstation (original) | Checkout verified 2026-11-18 |
|---|---|---|
| OS | Windows 11 + WSL2, Fedora Linux 42 | Windows 11 Pro + WSL2, Fedora Linux 42 (kernel 6.18.33.2-microsoft-standard-WSL2) |
| GPU | AMD Radeon RX 7900 XTX, 24 GB VRAM, ROCm | Intel Iris Xe only (no ROCm, no CUDA) |
| Repo | `~/pokeMorgrad` | `~/pokeMorgrad` |
| Venv | `~/venv-pokemorgad` (ROCm torch) | repo `.venv` |
| Python | 3.12 per old docs (Unverified) | 3.13.13 |
| torch | Old docs disagree: `2.14.1+rocm7.2` (OPERATIONS) vs "ROCm 6.x" (STATE). Unverified | `2.15.0+cpu` |
| Showdown | `~/pokemon-showdown`, ports 8000-8002 | not installed (no battles possible) |
| Node | Unverified | v22.22.0 |

Everything in the right-hand column was checked on 2026-11-18; the left-hand column comes from
old docs and could not be checked from that machine. On the CPU checkout: unit tests, ruff,
`tools/verify.sh` and the audit run; battles, evals, GA runs and BC training do not (no Showdown,
no `output/models/`, no `data/showdown_replays/`).

## GPU and ROCm (workstation)

- PyTorch's ROCm build exposes the AMD GPU under the `cuda` device name:
  `torch.cuda.is_available()` is True and code uses `"cuda"` (`src/bc_train.py::DEVICE`,
  `src/bc_player.py::DEVICE`, both falling back to `"cpu"`).
- Check: `python -c "import torch; print(torch.__version__, torch.cuda.is_available())"`.
  A version ending in `+cpu` means the CPU wheel is installed; `+rocm...` is the GPU build.
- Performance variables are NOT in the repo; they are appended to the venv's activate script
  (re-add them after recreating the venv):

```
cat >> ~/venv-pokemorgad/bin/activate <<'EOF'
export GPU_MAX_HEAP_SIZE=100
export GPU_MAX_ALLOC_PERCENT=100
export HSA_ENABLE_SDMA=0
export MIOPEN_FIND_MODE=2
export MIOPEN_FIND_ENFORCE=3
EOF
```

  (Values from the old docs; Unverified that the current workstation activate still has them.
  The repo `.venv` on the CPU checkout has none.)
- Harmless warning, ignore: `agent.cpp:608] sysfs nodes path '/sys/class/kfd/kfd/topology/nodes'
  does not exist` (ROCm probing under WSL2).
- `rocm-smi` may not exist under WSL; Unverified on the workstation.
- Measured 2026-10-13: bf16 autocast gave no BC training speedup (11.8 s vs 11.6 s per epoch at
  1.5M params, batch 256); the workload is launch-overhead-bound.

## Virtualenvs

- `tools/verify.sh` uses `~/pokeMorgrad/.venv` if it exists, else `~/venv-pokemorgad`.
- `run/ga_parallel.sh`, `run/ga_overnight.sh` activate the repo `.venv` if it exists, else
  `~/venv-pokemorgad`; `tools/paired_run.sh` defaults `PY` the same way (override with `PY=`).
  (Before 2026-11-18 all three hard-coded `~/venv-pokemorgad`.)
- `.clinerules/00-core-rules.md` tells the agent to activate `~/venv-pokemorgad` before every
  command (written for the workstation). On a checkout that only has `.venv`, activate
  `source .venv/bin/activate` instead; the rule's point is "always run inside the venv".
- `python` may not exist outside the venv; use `python3` or activate first.
- `pip install -e ".[dev]"` (README, `quickstart.md`) installs the dependencies and makes
  `src` importable from any folder (checked 2026-11-18 in a scratch venv). The 2026-11-18
  `.venv` was set up without it, so there commands run from the repo root
  (`python -m src.eval`).

## Dependencies

- Declared (`pyproject.toml`): `torch>=2.0`, `numpy`, `poke-env>=0.8`; extras `dev` (ruff, pytest)
  and `scrape` (beautifulsoup4, openpyxl). `requires-python >=3.10`.
- Installed in the 2026-11-18 `.venv`: poke_env 0.17.0, numpy 2.5.5, torch 2.15.0+cpu,
  ruff 0.17.5, pytest 9.2.0, websockets 16.1.1, requests 2.34.2; bs4 / openpyxl missing (only the
  scrapers `tools/scrape_tournament.py`, `tools/scrape_vgcpastes.py` need them).
- torch is needed even for CPU work: `tools/verify.sh` imports `src.bc_train`, `src.bc_player`,
  `src.bc_model`, `src.state_encoder`. The GA and the heuristic / vgc evals never import torch.
- Rule: if you `pip install` a package, add it to `pyproject.toml`.

## Node and Showdown

- Showdown is a separate checkout at `~/pokemon-showdown` (`SHOWDOWN_DIR` overrides); never edit
  it. Servers: `node pokemon-showdown start <port> --no-security` on 8000-8002
  (see `showdown.md`). The team validator and DB builder load `<checkout>/dist/sim/*` directly.
- The format `gen9championsvgc2026regmc` (Champions mod, Reg M-C) must exist in that checkout:
  `node tools/build_regmc_db.js` exits with `Format not found` otherwise.
- Unverified (not reproducible on the CPU checkout): installing on a new host is
  `git clone https://github.com/smogon/pokemon-showdown ~/pokemon-showdown`, then
  `cd ~/pokemon-showdown && npm install`, with the first `node pokemon-showdown start` building
  `dist/`.
- Servers and `/tmp` logs do not survive a WSL restart or Windows reboot; restart them.
  Windows Update reboots have killed overnight runs; checkpoints survive, resume with the same run_id.

## Paste-limit workaround (Windows Terminal)

Windows Terminal warns on, and can silently truncate, multi-line pastes over about 5 KiB. This
mangled several files in this project. Fix 1: in Windows Terminal Settings JSON (top level, not in
a profile) add, then close every Windows Terminal window:

```
"multiLinePasteWarning": false,
"largePasteWarning": false,
"warning.multiLinePaste": false,
"warning.largePaste": false,
```

Fix 2 (if a WSL relay still truncates): paste the script into a new file in VS Code (no size
limit), save it under `/tmp/apply_X.py` (do not create `.py` files in the repo root), run
`python3 /tmp/apply_X.py` from the repo root, check `git diff`, delete the file.

## Running a local coding LLM on the same GPU

The user is moving the coding agent to a local Qwen3-Coder-30B (quantized) on the 7900 XTX
(24 GB). Facts for sharing the machine:

- The GA does not use the GPU. A GA run is CPU-bound: three `node` Showdown servers plus three
  `python -m run.ga_island` processes (poke-env, turn simulation). Importing `src.ga.engine` /
  `src.eval` does not load torch (checked 2026-11-18). Evals with `--pilot heuristic`, `vgc` or
  `doubles` and paired evals are CPU-only too. These can run while the LLM holds the VRAM; they
  still compete with the LLM for CPU time, so expect both to slow down.
- GPU users: `src/bc_train.py` (BC training), `src/bc_player.py` (the BC pilot: `--pilot bc`, and
  `python -m src.eval` with no `--pilot`, whose default is `both` = heuristic + BC),
  `GA_PILOT=bc`, `tools/bc_diagnostic.py`, `tools/encode_snapshot.py`,
  `tools/generate_heuristic_dataset.py` (imports the state encoder), and preflight check 7 (only
  imports torch briefly).
- Do not run BC training while the LLM occupies VRAM: both need the 24 GB card. Unload the LLM
  first, or schedule training for when the agent is idle. For evals, pass `--pilot heuristic` or
  `--pilot vgc` explicitly so the BC pilot is not loaded by default.
- Unverified: the exact VRAM footprint of the LLM (depends on quantization and context length),
  and whether `HIP_VISIBLE_DEVICES` hides the GPU from torch to force a CPU BC eval.
- Long runs still need the user's approval; the policy question "is the PC needed for other work
  during this window?" now includes the LLM agent.
- Context budget (estimate, not measured): a Q4 30B model leaves room for roughly 32K-64K
  tokens of context on 24 GB, and Cline's own system prompt takes 10K+. Python costs about
  10 tokens per line, so the code is kept in files of at most ~430 lines (largest in `src/`:
  `turn_sim.py` 434, `genome.py` 398; split 2026-11-18) and docs of at most 300 lines.
  `.clineignore` (repo root) keeps Cline out of `data/` big files, `output/`, `archive/`,
  `docs/history/`, `.venv/` and the 450 KB golden fixture. Entry points for the agent:
  `AGENTS.md` -> `docs/README.md` (router) -> 1-3 docs; `.clinerules/00-core-rules.md`.

## Related docs

- [health-check.md](health-check.md) - first checks; preflight check 7 needs CUDA/ROCm torch
- [showdown.md](showdown.md) - Showdown servers
- [failure-modes.md](failure-modes.md) - environment errors
- [bc-training.md](bc-training.md) - BC training (GPU)
- [../reference/config-and-env.md](../reference/config-and-env.md) - environment variables
- [../reference/config-and-env-constants.md](../reference/config-and-env-constants.md) - venvs, pyproject
- [../design/policy.md](../design/policy.md) - when to run what
