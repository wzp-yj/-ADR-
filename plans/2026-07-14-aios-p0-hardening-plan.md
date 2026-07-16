# AIOS P0 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Safely close the P0 foundation gaps without expanding into P1 product features.

**Architecture:** Use a dedicated PostgreSQL test engine and FastAPI dependency override for database isolation. Keep API semantics, Web error handling, mobile configuration, and environment reproducibility as separate tasks with disjoint file ownership.

**Tech Stack:** FastAPI, SQLAlchemy async, pytest-asyncio, PostgreSQL 16, React/Vite/TypeScript, Expo 52, Git.

---

### Task 1: Establish Version-Control And Environment Baseline

**Files:**
- Modify: `F:\AIOS\.gitignore`
- Create: `F:\AIOS\.python-version`
- Create: `F:\AIOS\.nvmrc`
- Create: `F:\AIOS\backend\.env.example`
- Create: `F:\AIOS\backend\requirements.in`

- [x] Expand `.gitignore` to exclude Python, coverage, Vite, Expo, environment, and build artifacts while preserving `.env.example`.
- [x] Set `.python-version` to `3.12.10` and `.nvmrc` to Node 20 LTS.
- [x] Add `.env.example` with `DATABASE_URL`, `DATABASE_URL_TEST`, `OPENAI_API_KEY`, and `OPENAI_MODEL` using non-secret local defaults.
- [x] Copy direct dependencies from `requirements.txt` into `requirements.in`; do not claim hash locking until it is generated under Python 3.12.
- [x] Run `git status --short --ignored` after repository initialization and confirm no `.env`, cache, `dist`, or `node_modules` content is tracked.

### Task 2: Isolate Database API Tests

**Files:**
- Modify: `F:\AIOS\backend\tests\conftest.py`
- Modify: `F:\AIOS\backend\tests\api\test_projects.py`
- Create: `F:\AIOS\backend\tests\db.py`
- Create: `F:\AIOS\backend\tests\test_database_safety.py`

- [x] Write a failing unit test proving a non-test DSN is rejected.
- [x] Add `tests/db.py` with a small `assert_test_database_url(url)` helper that accepts only a database name ending in `_test`.
- [x] Build a test-only async engine from `settings.database_url_test` with a short connection timeout.
- [x] Idempotently create schema only after static URL checks and live `current_database()` / `current_user` identity checks. Do not call `drop_all` from a test fixture.
- [x] Keep the generic `client` fixture database-independent and make it reject database-bound endpoints. Add `db_client`, override `get_db` with an `AsyncSession` bound to an outer transaction and `join_transaction_mode="create_savepoint"`; rollback after every test and restore `app.dependency_overrides`.
- [x] Change project API tests to request `db_client`; health and agent tests continue using `client`.
- [x] Run `python -m pytest tests/test_database_safety.py -q` and expect PASS without Docker.
- [x] With `db_test` running, run `python -m pytest tests/api/test_projects.py -q` and expect all project tests to pass repeatedly.

### Task 2B: Repair Async Alembic Execution

**Files:**
- Modify: `F:\AIOS\backend\alembic\env.py`
- Create: `F:\AIOS\backend\tests\test_alembic_config.py`

- [x] Add a failing test proving Alembic keeps the `postgresql+asyncpg` driver for online async migrations.
- [x] Stop stripping `+asyncpg` from `settings.database_url`; escape percent signs before assigning the URL to Alembic config.
- [x] Run the unit test, then set `DATABASE_URL` to the dedicated test database and run `alembic upgrade head`.
- [x] Run `alembic downgrade base` followed by `alembic upgrade head` against `aios_test`; never run this destructive migration check against the development database.

### Task 3: Correct Project PATCH And Web Error Semantics

**Files:**
- Modify: `F:\AIOS\backend\app\schemas\project.py`
- Modify: `F:\AIOS\backend\app\api\projects.py`
- Modify: `F:\AIOS\backend\tests\api\test_projects.py`
- Modify: `F:\AIOS\frontend\src\api\client.ts`
- Modify: `F:\AIOS\frontend\package.json`
- Create: `F:\AIOS\frontend\src\api\client.test.ts`

- [x] Add failing API tests for omitted description, explicit `null`, persisted clearing, and explicit `name: null` returning 422.
- [x] Update `ProjectUpdate` validation so omitted `name` is allowed but explicit `null` is rejected.
- [x] Update the route using `body.model_fields_set` so explicit `description: null` writes SQL NULL.
- [x] Add Vitest and a `test` script.
- [x] Add failing tests for string detail, structured 409 detail, FastAPI 422 arrays, and non-JSON responses.
- [x] Implement `ApiError` and deterministic error-message formatting; allow `VITE_API_BASE_URL` to override `/api/v1`.
- [x] Change the Web update type to `description?: string | null`.
- [x] Run `npm test -- --run` and `npm run build`; both must exit 0.

### Task 4: Make The Expo Shell Reproducible

**Files:**
- Modify: `F:\AIOS\mobile\package.json`
- Modify: `F:\AIOS\mobile\app.json`
- Modify: `F:\AIOS\mobile\App.tsx`
- Create: `F:\AIOS\mobile\package-lock.json`

- [x] Remove the missing `assets/icon.png` reference and the unsupported duplicate Web script ownership.
- [x] Declare `expo-status-bar` using the Expo 52-compatible version.
- [x] Replace the unverified connection claim with neutral shell-ready text.
- [x] Run `npm install`, `npx expo install --check`, `npx expo config --type public`, and `npx tsc --noEmit`.
- [x] Record any Node 24 or network blocker rather than claiming mobile verification.

### Task 5: Final Verification And Memory Checkpoint

**Files:**
- Modify: `F:\AIOS\docs\PROJECT_MEMORY.md`

- [x] Start `db_test`, verify its health, and run the complete backend suite.
- [x] Run `docker compose config --quiet`, `alembic heads`, Web tests/build, and mobile configuration/type checks.
- [x] Update project memory with exact commands, pass counts, runtime versions, current commit SHA, and any remaining blocker.
- [x] Run `git diff --check` and review the complete change set before the final commit.
