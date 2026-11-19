# QWEN.md

Project context for Qwen Code. The canonical agent guide is `AGENTS.md` (read it first),
then `docs/README.md` to pick the 1-3 docs your task needs. Agent workflow rules:
`.clinerules/00-core-rules.md`.

Quick facts: format `gen9championsvgc2026regmc` (doubles, Mega legal, no Tera, EVs 0-32 per stat,
66 total). Gate: `bash tools/verify.sh` must print `ALL PASS`. Never run long jobs (GA, paired
eval, BC training, scrapers) without explicit approval. Held-out pool never used for fitness.
