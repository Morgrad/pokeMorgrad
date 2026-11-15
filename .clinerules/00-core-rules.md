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
- **Linting (MANDATORY):** Code must pass `ruff`. Do NOT reformat untouched code just to make it look better. 
  - **Workflow:** After editing files, you MUST run `ruff check --fix <files>` (with the venv active) BEFORE running `tools/verify.sh`. This ensures import sorting and trailing whitespace are fixed automatically. 
  - If `tools/verify.sh` fails because of a `ruff` error, you are strictly forbidden from committing.

## 4. The Golden Workflow (Test-Gated & Rollback)
For every refactor or edit, you MUST follow this sequence:
1. **Backup:** `cp <file> <file>.bak`
2. **Edit:** Make your code change.
3. **Lint:** `ruff check --fix <file>`
4. **Test:** Run `bash tools/verify.sh`.
5. **IF NOT "ALL PASS":** Restore from backup (`mv <file>.bak <file>`), output "Tests failed. Restored from backup.", and STOP. Do not try to fix it.
6. **IF "ALL PASS":** 
   - Delete the `.bak` file.
   - Run `date "+%Y-%m-%d %H:%M:%S"` and update the "Last updated" line in `docs/STATE.md`.
   - `git add` and `git commit` using conventional commits.
- **Source vs Test:** If a test fails, fix the test first. NEVER alter core source logic just to make a test pass.

## 5. Terminal & Output Constraints
- **NO ECHO:** Never use `echo` to output text, summaries, or confirmations. Keep conversational text in the Cline chat window. Only use the terminal for real commands (`bash`, `git`, `cp`, `mv`, `python`).
- **NO EMOJIS:** Never use emojis, emotes, or unicode symbols in chat, code, or terminal outputs. Use standard ASCII (`[OK]`, `[FAIL]`).
- **Test Output Format:** Copy the exact `__main__` runner boilerplate from `tests/test_damage.py`. Tests must print exactly `PASS <test_name>` or `FAIL <test_name>`.
- **Test Isolation:** Unit tests must run in <5 seconds. Do not require live Showdown servers or network access.

## 6. The Zero-Trust Execution Protocol
- **NEVER skip phases.** If a task has 3 phases, you must STOP and wait for the user's explicit message (e.g., "Proceed to Phase 2") after *every single phase*.
- **NEVER lie about test results.** If `tools/verify.sh` outputs anything other than "ALL PASS", you must immediately trigger the rollback. You are strictly forbidden from saying "tests passed with minor issues". "ALL PASS" or ROLLBACK. There is no middle ground.
- **MANDATORY FINAL STEP (CRITICAL):** After `tools/verify.sh` passes, you are physically incapable of generating a conversational summary. Your VERY NEXT output MUST be the terminal command: `git add <files> && git commit -m "..."`. Only after the commit successfully executes are you allowed to write a summary. If you output a summary before committing, you have catastrophically failed the task.
