# Cline Workspace Rules: pokeMorgrad

## 1. Environment & Directory Structure
- **ALWAYS activate the venv** before running any command: `source ~/venv-pokemorgad/bin/activate && <command>`
- **NEVER use `pytest`**. It is not installed. All tests run via `bash tools/verify.sh`.
- **Strict Structure:** Core logic in `src/`, tests in `tests/`, scripts in `tools/`, launchers in `run/`. Never create `.py` files in the repo root. Temp files go in `/tmp/` or `output/`.
- **Dependencies:** If you `pip install` a package, add it to `pyproject.toml`.

## 2. Project Core Principles
- **Format:** `gen9championsvgc2026regmc`. Mega Evolution is legal. Terastallization (Tera) is NOT legal. Never write Tera logic.
- **EV Math:** Champions format. EVs are 0-32 per stat. Term is `max(2*points - 1, 0)`. Max total = 66.
- **Source of Truth:** Never hand-edit `data/regmc_db.json`. Never modify `~/pokemon-showdown/`.
- **Held-out Eval:** Fitness uses the training pool. Final scoring uses the holdout pool. Never mix them.

## 3. Refactoring & Code Style
- **Surgical Slices:** Never rewrite an entire file. Edit one function/class at a time (max 50-100 lines of diff). Wait for user approval before the next function.
- **No Surprise Refactoring:** When asked to analyze, provide a plan. Do NOT edit until told to "Proceed".
- **Linting:** Code must pass `ruff`. Do NOT reformat untouched code just to make it look better. Keep diffs minimal.

## 4. The Golden Workflow (Test-Gated & Rollback)
For every refactor or edit, you MUST follow this sequence:
1. **Backup:** `cp <file> <file>.bak`
2. **Edit:** Make your code change.
3. **Test:** Run `bash tools/verify.sh`.
4. **IF NOT "ALL PASS":** Restore from backup (`mv <file>.bak <file>`), output "Tests failed. Restored from backup.", and STOP. Do not try to fix it.
5. **IF "ALL PASS":** 
   - Delete the `.bak` file.
   - Run `date "+%Y-%m-%d %H:%M:%S"` and update the "Last updated" line in `docs/STATE.md`.
   - `git add` and `git commit` using conventional commits.
- **Source vs Test:** If a test fails, fix the test first. NEVER alter core source logic just to make a test pass.

## 5. Terminal & Output Constraints
- **NO ECHO:** Never use `echo` to output text, summaries, or confirmations. Keep conversational text in the Cline chat window. Only use the terminal for real commands (`bash`, `git`, `cp`, `mv`, `python`).
- **NO EMOJIS:** Never use emojis, emotes, or unicode symbols in chat, code, or terminal outputs. Use standard ASCII (`[OK]`, `[FAIL]`).
- **Test Output Format:** Copy the exact `__main__` runner boilerplate from `tests/test_damage.py`. Tests must print exactly `PASS <test_name>` or `FAIL <test_name>`. 
- **Test Isolation:** Unit tests must run in <5 seconds. Do not require live Showdown servers or network access.
