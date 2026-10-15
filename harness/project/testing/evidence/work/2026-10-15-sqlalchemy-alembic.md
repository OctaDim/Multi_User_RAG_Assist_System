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

## U1–U2 simplification review

ce-simplify-code mode:pipeline reviewed the committed Database/model scope with reuse, quality, efficiency, test-value and comment reviewers. No actionable findings; no edits. All three proof-test files were protected. Authoritative 14-test result above remains applicable; no repeated test run after a read-only review. No lint/typecheck command is configured in backend/pyproject.toml.

## Уточнение U3 пользователем

Во время реализации пользователь потребовал перевести всю прежнюю историю в отдельные ревизии Alembic. Двухревизионный подход с исполнением старого SQL-суффикса отменён до коммита U3. Актуальное уточнение: `harness/project/docs/plans/2026-10-15-sqlalchemy-history-amendment.md`. Тесты промежуточного подхода не считаются окончательной проверкой U3.

## U3 — unified Alembic history, adoption and packaging

Final implementation follows the user's history amendment: six chronological application revisions plus 0007_checkpoints; original SQL moved byte-for-byte into test-only legacy fixtures. New databases create no lifecycle_migrations; existing journals remain unchanged after validated adoption. Subsequent prepared revisions have their own frozen contracts.

RED observations: original runner lacked alembic_version; concurrent async Alembic invocations exposed global context interference; translated numeric defaults initially differed from the original catalog. Fixed process serialization and SQL numeric literals without weakening frozen expectations.

Authoritative command: `env UV_CACHE_DIR=/tmp/rag-u1-uv-cache uv run --project backend --frozen pytest -c backend/pyproject.toml backend/tests/test_migrations.py backend/tests/test_resources.py backend/tests/test_models.py backend/tests/test_database.py backend/tests/test_saver_transaction.py -q`.
Result: **67 passed in 28.98s**. Covers every old prefix, repeat upgrade, history/schema corruption, lease/terminal data effects, checkpoint payload and interrupted DDL, concurrent processes, rollback/unlock, read-only current, historical upgrade target and prepared 7→8→repeat transition.

Wheel: `uv build --project backend --wheel --out-dir /tmp/rag-u3-wheel` succeeded. Installed with `uv pip install --no-deps --target /tmp/rag-u3-installed ...whl`; exercised from /tmp with installed app first on PYTHONPATH and the existing backend dependency environment. Verified seven packaged revisions, no runtime legacy SQL, empty bootstrap, repeat upgrade, absent legacy ledger and direct packaged-config Alembic check. All passed. This tests packaged application/resources, not independent dependency resolution.

Existing service characterization after U3: `test_accounts.py test_settings.py test_admission.py -q`, supplied existing RAG_MODEL_PATH/RAG_E5_DIR/RAG_OCR_DIR under backend/.venv/rag-native-models, **36 passed in 58.09s**. This is the pre-cutover behavior baseline for U4–U7.

All six legacy fixture SHA256 values match their prior Git versions. Frozen catalog profiles and live validation used PostgreSQL 16.2. No production database or read-only reference project was modified.

## Final quality stage

Not run. Latest user instruction excludes the 30/30 answers/citations quality suite entirely from this task, including after final commits. This supersedes the earlier final-stage/report-only instruction. Technical access/integrity tests remain implementation gates.
