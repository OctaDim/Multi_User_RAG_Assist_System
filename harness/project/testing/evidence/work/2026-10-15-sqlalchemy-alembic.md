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

## U4–U7 — coordinated runtime cutover (verification in progress)

The shared auth boundary now takes AsyncSession, so domain callers, transport handoff and process owners are transferred in one coherent commit boundary. All application queries use SQLAlchemy expressions. Dedicated connections retain advisory ownership; operation sessions retain explicit transaction boundaries. Existing raw test observers remain independent from application sessions.

First focused regression: accounts, settings, admission, source_contract, stream_recovery and rag_context — **93 passed in 112.08s**. Uses pinned native model/E5/OCR directories under backend/.venv/rag-native-models and real temporary PostgreSQL.

Added direct entrypoint/bridge checks: `test_migrations.py test_rag_context.py -k 'entrypoints_refuse or api_lifespan_initializes or runtime_saver_failure' -x -q` — **8 passed, 67 deselected in 8.81s**. Empty API bootstrap completes before readiness; API/document worker/generation supervisor/account CLI reject a damaged schema without replacing the lost table. Production GuardedSaver rolls back on error/cancellation/real backend termination, releases request locks and pool checkouts, invalidates the disconnected driver, and supports a fresh guarded read afterward.

ce-simplify-code pipeline completed with reuse, quality, efficiency, test-value and comment lenses. No code changes; one cosmetic comment deletion declined. Proof tests protected. Backend has no configured lint/typecheck command. Full technical regression and ce-code-review are still in progress; no completion claim yet.

Cutover wheel: online build could not resolve PyPI DNS; `uv build --offline --project backend --wheel --out-dir /tmp/rag-cutover-wheel` succeeded from the existing cache. Installed without dependency resolution into `/tmp/rag-cutover-installed`, exercised from `/tmp` using the existing backend dependency environment. Actual API lifespan initialized the empty DB before an invitation operation; independent SQL confirmed the committed invitation. Repeat migration, seven packaged revisions, absent runtime legacy SQL/legacy ledger and packaged Alembic check passed. This is an installed-wheel/resource check, not a clean dependency installation.

AST scan of application modules found no raw string execute/scalar calls, exec_driver_sql or create_all. This supplements, rather than replaces, query/transaction tests.

First broad non-browser run stopped after **72 passed / 1 failed in 547.69s**: the first test_http.py test reached LiveClient's existing 10-second API startup bound after native OCR tests. No startup exception was captured. Isolated `test_http.py -x -vv -o faulthandler_timeout=8` then passed **4 tests in 5.21s** without changes. Cause not established; retain this transient failure rather than claiming a single clean broad run. Remaining modules are being run separately with stack diagnostics; no test timeout or assertion was weakened.

Integration exclusion verified by collection: pytest rootdir is backend, so the exact argument is `--deselect=tests/integration/test_answer_lifecycle.py::test_frozen_thirty_questions_use_real_multilingual_documents`. Collection gives **27/28 tests (1 deselected)**. A first collect-only command with a backend/ prefix did not match; no quality test was executed.

Remaining non-browser modules (excluding the six already-passed prefix modules) completed: **188 passed in 277.73s**. This covers all 260 collected technical cases across the segmented broad runs, including the eight added startup/bridge cases. The isolated four HTTP cases overlap this result.

Review identified loss of the previous Supervisor `connect_timeout=5`. Restored that bound through libpq `make_conninfo` for both startup migration and keeper Database. Regression uses a real local ThreadingTCPServer that accepts TCP but never completes PostgreSQL handshake: fixed code **1 passed in 5.38s**; temporarily restoring only the unbounded pre-fix path gave **1 failed in 8.47s**, TimeoutError at the outer 8-second bound, then the fix was restored in finally. Initial async-server test helper hung during its own cleanup both before and after the fix and was discarded; those interrupted runs are not RED evidence. Affected ownership/recovery and native tests are being repeated after the fix.

After the timeout fix: `test_service_recovery.py test_service_ownership_lease.py tests/runtime -x -q` — **17 passed in 121.24s**. Includes actual supervisor recovery/lease-loss, silent TCP handshake timeout, native context fairness, EOS/UTF-8, cancellation/cleanup and vocabulary consistency.

First integration/browser attempt selected 49 cases and excluded the quality case. It stopped in the first authority matrix: final reactivation login returned 403 after four successful PATCH requests. The test reused an already-visible status message as a completion signal while showWorkspace asynchronously replaced account forms. Its two save boundaries now await the actual PATCH response (also asserting the requested flag in its JSON) and the prior form's detachment. All original permission/data-leak assertions remain. Focused authority matrix then passed **1 test in 13.23s**. No frontend or account policy change was made; the full remaining run has restarted.

Wheel rebuilt/reinstalled after the supervisor timeout fix; installed API/bootstrap, committed invitation visibility, repeat migration and Alembic check passed again from /tmp.

Restarted integration prefix: authority matrix passed, then damaged-PDF processing exceeded its existing 30-second polling bound (1 passed / 1 failed in 83.86s). Worker was loading real OCR; no application exception appeared in the captured worker log. Isolated unchanged document-boundaries scenario passed **1 test in 50.35s**. Exact cause of the transient deadline miss is not established; no timeout was relaxed. Remaining 47 selected cases run separately without stop-on-first-failure; quality case remains deselected.

Full ce-code-review receipt: run `20261015-142743-bd281e75`, `/tmp/compound-engineering-1000/ce-code-review/20261015-142743-bd281e75/review.json`; metadata stage receipt complete. Eleven local lenses, no open findings after the supervisor timeout repair. Verdict remains Not ready solely for pending U7 verification/documentation. External cross-model transport acpx was unavailable; local adversarial review ran, no external job/content transfer occurred.

Current long integration run: first four lifecycle-gap cases passed. During whole-PDF 20-page failure case, generation supervisor exited with `Coordinator ownership connection stalled`; OCR continued. Later live pg_stat_activity snapshot showed no waiting lock blockers. Host snapshot: 5783 MiB physical memory, 5484 MiB swap in use, memory full pressure avg10 7.53 and I/O full pressure avg10 15.85. These observations suggest resource pressure but do not establish causation. Source-only pre-cutover baseline at HEAD 76ddb63 was extracted into /tmp/rag-sqlalchemy-before for a potential controlled comparison; no baseline runtime test has yet run. Do not count this OCR case as passed while it is still processing.

Remaining integration/browser run completed: **40 passed / 7 failed / 1 deselected in 4267.96s**. Combined with the two isolated prefix passes, 42 of 49 selected integration/browser cases have passed so far. Failures retained: whole-PDF case reached 15 actual pages and the final healthy-neighbor answer wait failed after the supervisor had reported ownership stall; 30-account joint OCR case lost all 12 contexts to tab_timeout; print-only passport answer produced only "The annual budget is " within 30 seconds; old-snapshot case had no request heading within 5 seconds; all three OCR invalidation cases exceeded their existing 45-second ready bound. These are not declared passes or assigned a common cause. Print-only 15-page atomic failure, four-language publication/permission masks, independent process capacity, recovery/terminal/transport and other browser cases passed.

Read-only follow-up review found no changed ACK deadlines or lock ordering. A confirmed configuration difference is old psycopg pool max=4 versus SQLAlchemy defaults permitting 15 per process plus pre_ping; it is a candidate for comparison, not an established cause. A later no-blocker snapshot cannot exclude earlier blocking. Review of operations documentation and latest test synchronization/timeout changes found no substantive issues.

A controlled comparison of six shorter failed cases started in the isolated pre-cutover source snapshot `/tmp/rag-sqlalchemy-before` (HEAD 76ddb63), sequentially after the current suite. It reuses the installed dependencies/models and explicitly selects baseline app imports via PYTHONPATH. uv resynchronized the shared editable application to the baseline checkout; the original project must be resynchronized before subsequent current-code commands. No baseline result is available yet.

Pre-cutover comparison completed: **3 passed / 3 failed in 747.16s**. Thirty-account joint OCR, old-snapshot protection and before-delete invalidation passed. Print-only passport failed waiting for answer; its baseline generation.log explicitly reports `Coordinator ownership connection stalled` from the old psycopg implementation. After-delete and after-correction failed at the same existing 45-second OCR readiness bound as current code. This establishes that ownership stalls under OCR and OCR deadline misses also occur before the runtime cutover; it does not prove a specific hardware cause or clear the current-only failures. Baseline output: `/tmp/rag-precutover-baseline.log`; per-case logs under `/tmp/pytest-of-octadim/pytest-27`.

Shared editable installation was restored to the current checkout by uv before the next run. Current code now repeats those six cases in the same order, followed by whole-PDF, with unchanged assertions, pool settings and timeouts. Results pending.

Current matched-order follow-up has completed six shorter cases: thirty-account joint OCR, old-snapshot protection and actual OCR correction/context exclusion passed without code changes. Print-only passport and before-/after-delete cases failed again; precise follow-up assertions will be retained with the final output. Whole-PDF repeat remains in progress. No production tuning, pool-size change, timeout relaxation or assertion removal was used.

## Final technical accounting

Collection confirms **319 selected technical cases out of 320; the single 30-question answers/citations quality case is deselected**. Across the documented segmented runs and focused repeats, **315 unique technical cases have passed; four have no successful current-code result**:

- Whole-PDF 20-page fault scenario: original full run completed 15 native pages and passed the failed-file/source-exclusion checks, but the final healthy-neighbor answer did not appear after the supervisor lost ownership. The repeat logged ownership stall after its first page; it cannot complete because its fixture does not restart the dead supervisor.
- Print-only PDF answer passport: original current run produced only "The annual budget is " within the 30-second answer assertion; the matched follow-up again reported FAILED. Baseline failed the same test with an ownership-stalled supervisor.
- OCR invalidation before-delete and after-delete: original current failures were at the initial 45-second OCR-ready bound, before mutation assertions. Both matched follow-ups again reported FAILED. Baseline before-delete passed, while after-delete and after-correction failed at that same OCR readiness boundary.

The current matched follow-up conclusively passed the previously failed 30-account concurrency and old-snapshot cases, and actual after-correction invalidation/context exclusion. It has no final pytest summary: after the whole-PDF supervisor's irreversible failure, two SIGINT attempts did not end the runner; only its verified 12-process tree was terminated with SIGTERM (no SIGKILL needed), exit 143. The run's dedicated PostgreSQL under `/tmp/pytest-of-octadim/pytest-28/postgres0` was stopped separately. Do not treat the interrupted repeat as another completed full-case result or manufacture its exact failure stack traces. Its observed per-case progress is retained in `/tmp/rag-cutover-retry-progress.log`; the original complete run remains the authoritative source of the four failure assertions.

The baseline comparison proves these classes of loaded OCR/ownership failures predate the query cutover, but does not establish RAM, pool size or another specific root cause. No production performance workaround or weakened timeout/assertion was introduced. Full technical acceptance is therefore **not entirely green**; these four cases remain explicit limitations, not passes.

Post-run checks: git diff --check passed; outside-checkout import resolves the editable application back to the current project. All task test processes and the interrupted run's temporary PostgreSQL were stopped. No production DB was migrated. The quality suite was never executed and remains entirely excluded, including after any final commit.

Final report-only review refresh is complete: no open actionable code findings, verdict **Not ready** because U7 acceptance remains incomplete. The local commit is also pending under comm-commit-task-stages: “Missing Git/ce-commit or failed checks/commit: preserve changes, report the blocker.” No cutover changes were staged or committed; the existing U1–U3 commits remain intact.

One bounded diagnostic repeated only actual OCR invalidation `[before-delete]`, with unchanged code/assertions/timeouts: **1 failed in 73.36s**, again at the initial 45-second OCR-ready wait, before mutation. The supervisor did not log ownership loss in this run. A separate read-only observer collected 153 process/pressure/PostgreSQL samples over 77.065 seconds, with maximum sample gap 0.571 seconds. Five sampled transaction-lock waits had query ages 2–33 ms; the maximum sampled active query age with a PostgreSQL wait event was 90.307 ms. This does not exclude an unsampled stall. OCR major faults rose from 47 at 30 seconds to 65,594 at 71 seconds; available memory fell to about 321 MiB at the 40-second sample, with swap activity and memory/I/O pressure increasing. These observations narrow the investigation but do not establish a sole root cause or justify changing application pool/lease settings. No new pass was added: accounting remains **315/319**.

Diagnostic artifacts: `/tmp/rag-bounded-diagnostic.log`, `/tmp/rag-bounded-diagnostic.jsonl`, and per-process logs under `/tmp/rag-sqlalchemy-diag-one/test_real_ocr_mutation_preserv0/`. The diagnostic runner exited normally with status 1; its sampled child processes and temporary PostgreSQL were verified stopped. Further identical whole-suite retries are not warranted by this evidence. Remaining work is to resolve the four acceptance gaps with discriminating OCR/native-runtime evidence or an established external blocker; the database implementation has no demonstrated additional defect to repair.

## Later acceptance addendum: approved OCR changes, 2026-10-15

The preceding results retain their original failures and review verdict. Later user-authorized work is recorded separately in [the four-test timeout repeat](2026-10-15-sqlalchemy-timeout-repeat.md), [the root-cause investigation](2026-10-15-coordinator-ownership-root-cause.md), and [the OCR context/fragment report](2026-10-15-ocr-context-and-fragments.md).

The approved test-only deadlines (OCR readiness 300 s, answer appearance/completion 120–180 s, whole PDF 2000 s) cleared both before-/after-delete cases. The two remaining cases then passed after the user-requested printed context of 16384: **2 passed in 1042.48 s**. This was a plain current-source run without GC instrumentation or GC/pool/lease changes. The passport took 160.767 s; whole-pdf took 881.059 s and completed all fifteen real OCR pages, controlled page-16 failure, failed-source exclusion and the healthy-neighbor answer. Thus all **319 originally selected technical scenarios now have a successful result across segmented runs**. This is not a single clean whole-suite run, and one successful repetition does not prove the absence of all resource-pressure failures.

The root-cause investigation directly recorded a failed supervisor stalled on page-in beyond its five-second lease while PostgreSQL waited for its client after BEGIN. It also measured a long full GC with bulk page faults in a separate probe. It did not prove GC initiated every historical stall. The printed context was previously the model's full 131072-token training context; it is now explicitly 16384. Handwriting remains 4096. Lease remains 5 s; tab ACK 15 s plus grace 10 s. Reference TLT_TG_AggregatorManager remains read-only.

User-approved image fragmentation was implemented after the two-case repetition completed, preserving that configuration-only result. Large inputs are split before detection and OCR into at most 2400×2400, overlap 128, with whitespace cuts where possible. Handwriting masks are combined before printed recognition. Coordinates and nested detections are translated to the original page; duplicates use geometry, not matching text; native calls remain sequential; a failed/cancelled fragment cannot return a partial page. Original foreground thresholds are retained after masking. Original raster/masks still reside in memory, so this is not streaming raster decoding.

TDD: **16 expected failures** on pre-fragmentation code, then **16 passes**; an additional gray-paper regression failed before its repair, followed by **17 passes** including actual API/worker/PostgreSQL publication failure proof. Existing OCR regression plus actual native long-image proof: **19 passed in 113.26 s**. The native proof preserves both distant repeated lines, deduplicates the seam and verifies original-page geometry and text offsets. Two aborted attempts under the socket-restricted sandbox are retained as environment failures, not passes: a minimal asyncio/socketpair comparison and a successful unrestricted local native repeat established the cause without changing application code.

The final browser passport repetition with the completed fragment code failed in 196.82 s: HTTP 200 admitted the request, supervisor subsequently reported `Coordinator ownership connection stalled`, and the answer remained empty at the 120-second assertion. This reopens current acceptance despite the earlier successful two-case run. The previous full-depth code review had no open actionable implementation findings; its acceptance blocker was the then-unpassed four scenarios. Its report remains historical and is not retroactively relabelled.

User separately approved removing heavy inference imports from supervisor. `run_graph` now imports only in Coordinator, `E5Embedder` in the authorized native worker. Fresh-process VmRSS fell 142228→67988 KiB and GC objects 164378→90328; the import regression showed RED then GREEN. Ownership/recovery/scheduler/RAG/native regression: **46 passed in 156.19 s**. Both PDF scenarios then passed with this code: **2 passed in 963.69 s**, including all fifteen actual OCR pages and the final healthy-neighbor answer. Exact results and memory-measurement limits are in [the supervisor report](2026-10-15-light-supervisor.md). No GC, pool or five-second lease change was made.

## Completed implementation and verification

The final collection contains **338 selected technical tests out of 339**, with exactly the excluded quality30 case deselected. The original 319 technical scenarios and nineteen added OCR/import scenarios have successful results across the documented segmented runs. This is not a claim that all 338 ran together successfully; original failures and environment-aborted runs remain in their original reports. Latest focused results: OCR geometry/publication **17 passed**, OCR/native regression **19 passed**, supervisor/recovery/scheduler/RAG/native **46 passed**, PDF acceptance **2 passed**.

The final offline wheel was installed into a separate /tmp target and exercised outside the checkout: lightweight Supervisor import, packaged OCR helper operation, printed/handwriting contexts 16384/4096, seven packaged revisions. [Wheel evidence](2026-10-15-final-wheel-proof.json) records its SHA256 and the scope: existing pinned dependencies, no clean dependency installation and no production database operation. The final direct-raw-execute/create_all/exec_driver_sql AST supplement and git diff --check passed. Owned test processes exited; the original reference repository remains read-only.

Implementation units U1–U7 are complete. U1–U3 are already in `2acd2cc`, `6ab2e6b`, `76ddb63`; runtime cutover and lightweight supervisor are now in `4398854`, OCR/context/test deadlines in `ab0d15f`. This documentation and preserved raw evidence accompany the concluding documentation commit. The unrelated user documents database-options-history.md and project-overview.md remain outside these commits.

Residual limits: the host still uses swap under load; reduced supervisor heap and the successful repetition do not guarantee absence of all future memory-pressure stalls. Raster fragmentation bounds model inputs, while the original raster and masks still reside in memory. Production rollout/restore was not performed. Quality30 remains completely excluded, including after commits.
