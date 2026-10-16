# pokeMorgrad wiki

Knowledge base: what each module, script, data file and setting does. For project status and history see `../STATE.md`; for how to run a GA see `../OPERATIONS.md`; for terms see `../GLOSSARY.md`.

| Page | Covers |
|------|--------|
| [src-modules.md](src-modules.md) | Every module in `src/`: GA core, damage calc, pilots, opponent model, evaluation, gotchas |
| [run-and-tests.md](run-and-tests.md) | `run/` launchers, `ops/` server scripts, `tests/`, `tools/verify.sh` |
| [tools.md](tools.md) | `tools/` scripts: scraping, prior building, pool/split management, one-offs |
| [data-files.md](data-files.md) | `data/` and `output/` files: schema, generator, tracked or not |
| [config-and-env.md](config-and-env.md) | Paths, venv, Showdown ports, environment variables, GA knobs |

Conventions: `~/pokeMorgrad` is the repo, `~/venv-pokemorgad` the venv (`~/llm-env` was removed 2026-10-16; the `~/project` symlink to the repo is only kept while VS Code is still opened through it, delete it with `rm ~/project` after reopening at `~/pokeMorgrad`; nothing in the code uses either path). Format is `gen9championsvgc2026regmc`: Mega Evolution legal, Terastallization not legal. Line numbers in these pages were measured on 2026-10-16 and drift as code changes.
