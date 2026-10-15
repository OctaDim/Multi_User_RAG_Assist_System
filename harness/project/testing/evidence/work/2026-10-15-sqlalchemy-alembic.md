# SQLAlchemy/Alembic implementation verification

Created: 2026-10-15. Status: current, task unfinished.
Plan: `harness/project/docs/plans/2026-10-15-1316-refactor-sqlalchemy-alembic-plan.md`.

## Planning

Read-only reference analysis completed. Five local ce-doc-review personas (coherence, feasibility, scope, security, adversarial) returned no findings. Optional external cross-model review not started: required acpx npm package absent locally; no extra installer introduced. Plan IDs/fences and quality-check ordering checked. Plan/analysis commit: `0c2d28a`.

## U1 — explicit Database and saver transaction proof

Behavior changed: added process-owned engine/session factory; existing runtime callers and migration runner are temporarily unchanged.
Existing evidence inspected: conftest, settings migration checks, rag-context tests, stock saver/psycopg implementation.
RED before production implementation: resource-owner test failed because Database did not exist.
Added tests: `backend/tests/test_database.py`, `backend/tests/test_saver_transaction.py`.
Authoritative command: `env UV_CACHE_DIR=/tmp/rag-u1-uv-cache uv run --project backend --frozen pytest -c backend/pyproject.toml backend/tests/test_database.py backend/tests/test_saver_transaction.py -q`.
Result: **10 passed in 2.82s**, real temporary PostgreSQL, host run after inspecting worker diff.
Covers independent sessions, pool disposal, cleanup-only session context, explicit commit/rollback, socket/credential DSNs, same physical saver transaction, pipeline/fallback, independent observer visibility, blob/writes/get/list/delete roundtrip, cancellation lock/checkout cleanup.
One initial test URI used plus for spaces; corrected test encoding to percent escaping, then reran. No production workaround.
Not yet verified: production GuardedSaver conversion, migration adoption, full caller regression. Those remain later units.

## U2 — separate models and catalog parity

Behavior changed: static ORM metadata now describes all 24 application tables; runtime callers unchanged until later units.
RED: registry import failed with missing app.models before implementation.
Authoritative command: `env UV_CACHE_DIR=/tmp/rag-u1-uv-cache uv run --project backend --frozen pytest -c backend/pyproject.toml backend/tests/test_models.py backend/tests/test_database.py backend/tests/test_saver_transaction.py -q`.
Result: **14 passed in 4.44s**. Previous tool output was truncated; repeated this focused check to obtain an observable result.
Alembic comparison reports no differences; supplemental catalog checks cover names/checks/defaults/identity/partial predicates. Import test forbids engine/network, vector comparator runs against PostgreSQL.
SQLAlchemy native defaults avoid evaluating volatile expressions during comparison. pgvector pinned at 0.5.1.

## Final quality stage

Not run. User requires 30/30 answers/citations only after all implementation stages and final commits. Quality failures are report-only and do not trigger fixes/refactoring on their own. Technical access/integrity tests remain implementation gates.
