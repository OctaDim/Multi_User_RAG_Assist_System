# U7 serial implementation worker result

Created 2026-10-14. Application work evidence, not harness mechanism evidence.
Authoring and focused verification complete; parent-owned canonical commit, complete regression gate, separate manual walkthrough and U8 acceptance are pending. This is not a full lifecycle/MVP acceptance certificate.

Native CE serial worker `/root/u7_invalidation_implementation`, inherited model/effort unchanged; exact served model pin is unverified. No external engine, fallback, subdelegation, install, git-index write, commit, push, PR or deployment. Base HEAD verified `2f6597e276282f1a394495e5d60bdd1c817d682a`; branch `octadim/create-plan-1`. Mandatory startup and ordered common/project/rule/index intake passed. Parent-owned handoff, transport notes, initial raw evidence and immutable plan were preserved.

## Behavior and evidence strategy

`behavior_changed: true`. Proof-first for every newly changed behavior; characterization for already implemented terminal/recovery invariants. Existing tests inspected: test_admission.py, test_source_contract.py, test_rag_context.py, test_scheduler.py, test_stream_recovery.py, test_accounts.py, test_documents.py, test_http.py, test_service_recovery.py, runtime/test_production_runtime.py, integration/test_multi_process.py and browser issuer/document/answer tests. Existing HTTP assertions are retained: TestClient imports now use a real socket, production GuardedH11Protocol and httpx through tests/live_http.py. The generic ASGI fail-closed test explicitly still uses the real TestClient without an invented extension.

Production changes:

- The pinned asyncio/H11 handoff waits actual flow drainage outside every database transaction, then takes the common service barrier, checks session, resource ownership, role and tab proof/connection epoch, and serializes current private views. The ready-flow check and actual transport write have no suspension between them. Account/source mutations participate in this same barrier.
- Prepared account/library/settings/conversation JSON is replaced with its current authorized projection; deleted originals and PNGs are denied. Minted login tokens are checked at body delivery. OPTIONS login preflight remains public. Logout retains its minimal acknowledgement for blocked/expired/revoked sessions. Authorization bytes use Latin-1.
- SSE replay/output/fragments from interrupted or failed executions are replaced by an invalidation notification. Authorized historical snapshots retain original text and quotes with current exclusion/source flags. Actual fresh snapshot watermarks are returned to the stream generator, so replay begins strictly after what was handed off.
- A final synchronous clock check prevents natural session/tab expiry during serialization from granting a late write. Row locks alone cannot freeze time; the RED test proved a body escaping after expiry.
- Source publication updates versions and source-status events; request projections, terminal/output events and the UI show deleted/corrected flags. Source flags are batched for histories. Old handed-off frames cannot clear newer labels because the reducer checks versions before applying flags. Original quote/name data comes from immutable passports.
- OCR correction closes stale saver reads/writes/pending writes without cancelling the current question. Preparation obtains current eligible history and immutable source inputs once, packs and publishes dependencies atomically, then persists through the guarded graph. If correction closes persistence after preparation, the authorized current native generation uses only its locally prepared input; it does not retry, resume or write stale persistence. Correction of prior history after admission likewise keeps the accepted question and excludes that prior history.
- Admission rejects an irreducible oversized question before inserting history/occupancy, using the pinned vocabulary with no weights or native contexts. Authentication/dedupe precede CPU tokenization; all mutation locks are released during it and full admission authorization is repeated afterward. Native comparison proves identical tokenizer output and a weighted context surviving vocabulary close. The 4096 context/256 response reserve and native limits are preserved.
- Duplicate ACKs use the same citation/exclusion projection as snapshots. Existing schema columns already hold flags, messages, epochs and bindings; no schema extension was needed.

Current-generation packing uses synchronous tokenization under its source-read/dependency-publication transaction. Network drainage, E5 embedding and native inference are outside those transactions. No prompt cap, truncation policy, model, quality threshold or cancellation policy was lowered or replaced.

## U7 scenario matrix

The short names below refer to backend/tests/test_invalidation.py unless another file is named. Fixture-principal contract cases are component proof; they do not alone discharge G3/G4. New browser cases create actors through UI signup → real SMTP verification → login and upload a real scanned PDF; they run actual OCR/E5/Qwen and the real document publisher.

| Plan scenario | Concrete proof |
| --- | --- |
| 1 / AE9 | account_revoke_closes_prepared_body_before_real_handoff; current_session_fences_prepared_json_but_logout_ack_stays_minimal (logout/expiry/soft-delete); minted_login_token_is_fenced_before_private_body; real_database_output_races_account_revoke_without_late_publication; unchanged account issuer/browser and origin-session tests. Parent separate manual active block/soft-delete walkthrough remains owned by parent. |
| 2 / AE33 | prepared_sse_and_replay_rechecks_source_and_tab output-delete; browser/test_invalidation.py real mutation after-delete: committed partial text, interrupted/deleted flags, no continuation and actual next native context/checkpoint. |
| 3 / AE34 | prepared_sse fragments-delete; browser real before-delete: real native context paused before output, no empty assistant/message, no late token and one native release. |
| 4 / AE12 | existing RAG transitive-history test (delete/correction) unchanged; actual browser second question excludes prior request, old text and checkpoint prompt, with independent native allocations/releases. |
| 5 / AE37 | correction_marks_request_snapshot_and_notifies_all_tabs; prepared_snapshot_retains_old_quote_with_current_correction_flags; correction_between_preparation_and_pending_checkpoint_keeps_current_generation; correction_of_prior_history_after_admission_keeps_current_question; existing late-complete/checkpoint tests; actual browser after-correction completes old generation and uses corrected source in next input. |
| 6 / AE41 | test_service_recovery.py real_supervisor_reaps_native_process_before_replacement: actual decode abort callback, committed prefix, terminated ownership connection, blocked successor, physical reap, interrupted excluded saved prefix and no restart. |
| 7 / AE42 | real_coordinator_recovery_reconciles_all_pre_token_states_and_keeps_completed: accepted/searching/queued/generating reconciled by actual new supervisor, empty assistant not created, binding.started remains false. |
| 8 / AE43 | same recovery table retains completed text; application_service_lock_does_not_cancel_healthy_supervisor SHARE/UPDATE keeps epoch and native PID; existing API lifespan restart tests retained and pass. Parent full/manual alive-execution API restart remains an authoritative integration gate. |
| 9 | real_database_complete_races_invalidation_with_one_terminal_outcome timeout/delete: simultaneous independent DB operations, exactly one terminal; real_database_output_races_account_revoke_without_late_publication: revoke before release and no late output; existing delayed saver/correction tests plus new preparation pending-write race. |
| 10 | stop_old_request_races_new_admission_and_old_pending_writes_cannot_change_new_context: simultaneous connections, new request remains queued with independent checkpoint; existing scheduler logical-stop/physical-ACK test retained; actual browser native trace asserts exactly one old native allocation/release. |
| 11 | prepared resource/role/account JSON, file/PNG, source/tab SSE/replay and fresh snapshot cases use two actual H11 processes; real_socket_backpressure_revocation_holds_no_database_locks has five targets (JSON/file/PNG/SSE snapshot/replay), observed real pause_writing and real target drainage, mutation ACK before client drains, no unhanded private bytes. No synthetic flow pause/drain gate. |
| 12 | extended actual supervisor test freezes predecessor supervisor, terminates its advisory connection and attempts a real successor while native PID lives; successor cannot spawn. Live predecessor record also blocks replacement even after host lock release; actual replacement starts only after confirmed physical reap. |
| 13 | stop-old/new checkpoint test rejects both old checkpoint and pending writes while preserving current state; existing every-saver-operation/access/account-epoch tests unchanged; all current session/mutation tests retain DB history/checkpoints and deny subsequent use. |

## Final focused results and exact commands

These are worker self-checks, not the parent's complete acceptance gate. Heavy native workloads were serialized; vocabulary-only admission runs do not load another set of weights.

Common prefix: `uv run --project backend --frozen --cache-dir /tmp/rag-answer-lifecycle-uv-cache pytest -c backend/pyproject.toml`.
Environment when needed:

```sh
RAG_MODEL_PATH=/home/octadim/MyProjects/Multi_User_RAG_Assist_System/backend/.venv/rag-native-models/Qwen3.5-2B-Q4_K_M.gguf
RAG_E5_DIR=/home/octadim/MyProjects/Multi_User_RAG_Assist_System/backend/.venv/rag-native-models/e5
RAG_OCR_DIR=/home/octadim/MyProjects/Multi_User_RAG_Assist_System/backend/.venv/rag-native-models/ocr
```

1. All final transport/context/account assertions: common prefix + `backend/tests/test_invalidation.py backend/tests/test_http.py backend/tests/test_frontend_reducer.py backend/tests/test_accounts.py backend/tests/test_rag_context.py -k 'not real_e5 and not real_qwen' --basetemp=/tmp/u7-worker-final-transport-context-6`, all three environment values. **69 passed, 2 deselected, 177.20s**. The two pre-existing heavy E5/Qwen cases are deferred to the parent's full serialized gate; no skips were introduced. Log: 2026-10-14-transport-context-accounts-green-v6.log.
2. Real supervisor/recovery and weighted vocabulary comparison: common prefix + `backend/tests/test_service_recovery.py backend/tests/runtime/test_production_runtime.py -k 'test_service_recovery or admission_vocabulary' --basetemp=/tmp/u7-worker-native-final-2 -s --assert=plain`, model/E5 values. **6 passed, 5 deselected, 41.84s**. Five unrelated runtime cases are parent-owned full regression. Log: 2026-10-14-native-recovery-vocabulary-green-v2.log.
3. Real scanned-PDF/native mutation integration: `xvfb-run -a` + common prefix + `backend/tests/browser/test_invalidation.py --basetemp=/tmp/u7-worker-real-browser-4 -s --assert=plain`, all three values. **3 passed, 192.49s**. Log: 2026-10-14-real-browser-ocr-invalidation-green-v4.log. That original stdout mistakenly printed the second request's completed state in `first_state` for delete cases; assertions and native traces prove first-delete interrupted, then next completed. Only the print fields were corrected afterward to old_state/next_state; the original raw log is preserved, not rewritten.
4. True simultaneous DB terminal races: common prefix + `backend/tests/test_invalidation.py -k 'real_database or stop_old_request' --basetemp=/tmp/u7-worker-terminal-races-1`, model value. **4 passed, 30 deselected, 7.24s**. Log: 2026-10-14-terminal-races-characterization-v1.log; those same cases pass again in final run 1.
5. `git diff --check` passed. HEAD stayed at the required base; no worker canonical commit.

No full suite, complete harness regression, standalone simplification/review/shipping tail or manual human attestation was claimed. Parent must run the complete old/new application and active harness gate, manual walkthrough, then canonical commit. U8 joint load, held-out 30/30 multilingual quality and the known handwriting-crop miss remain outside this worker's acceptance.

## RED observations and resolved test/implementation failures

Raw logs are immutable; filenames saying green do not override their actual results. Functional REDs before their fixes: prepared role/account views; deleted original/PNG/library; missing ACK citations/source flags; stale source/tab SSE; irreducible question admission; source-status reducer; pending-write OCR cancellation; prior-history correction cancellation; already handed stale frame clearing a newer label; login preflight; fresh snapshot replay cursor; natural session expiry during serialization. Characterization (without a production change to the already working transition): four simultaneous DB races and native physical recovery/replacement invariants.

Resolved non-functional or intermediate failures: initial PDF test imported unavailable pymupdf (replaced with installed PIL PDF and reran functional RED); initial reducer lacked sessionStorage; initial pending-write pause watched the wrong channel; initial live snapshot used string UUIDs; removed unused build_graph import after folding its only caller; a preparing-guard await/comprehension produced an async generator (replaced by a direct SQL dependency check); initial pressure file ended with a tiny chunk, and PNG render finished after drainage (large final chunk and actual render prewarm prove the intended wait); initial login browser run exposed a real OPTIONS/CORS defect; later browser runs used asyncio.run inside Playwright's loop and observed an old completed card before second ACK (worker-thread checkpoint read/count-two observation fixed); the first final-clock mixed run omitted required RAG_MODEL_PATH for admission cases (correct final environment restored). None of these failed runs is counted as acceptance. Existing TestClient assertions were preserved during the real-H11 client migration. The prior root prepared-JSON revoke RED/GREEN files are inherited evidence, preserved without modification.

All observed run outcomes (including failures) and hashes are in 2026-10-14-worker-run-results-v1.json. Fourteen original native/browser subprocess logs were copied byte-for-byte to new dated files; source paths, sizes and SHA256 are in 2026-10-14-worker-proof-files-v1.json. Original temp files and historical harness logs were not deleted or overwritten.

## Actual application paths changed

- backend/app/answers.py
- backend/app/api/tabs.py
- backend/app/auth.py
- backend/app/events.py
- backend/app/generation.py
- backend/app/handoff.py
- backend/app/llama_runtime.py
- backend/app/main.py
- backend/app/rag.py
- backend/app/sources.py
- backend/tests/runtime/test_production_runtime.py
- backend/tests/test_accounts.py
- backend/tests/test_documents.py
- backend/tests/test_frontend_reducer.py
- backend/tests/test_http.py
- backend/tests/test_rag_context.py
- backend/tests/test_service_recovery.py
- backend/tests/browser/test_invalidation.py
- backend/tests/live_http.py
- backend/tests/test_invalidation.py
- frontend/src/conversations.js

Additional paths beyond U7's original declared files are traced to its contracts: api/tabs delivers the actual watermark/epoch; auth supplies the final session deadline; handoff implements KTD8's real transport; llama_runtime supplies exact vocabulary admission without weights; frontend renders eligibility; live_http and migrated endpoint tests exercise the actual supported transport. The runtime/browser additions supply actual proof rather than model/OCR result mocks.

Application source hashes and the immutable plan digest are in 2026-10-14-worker-changed-files-v1.json. That manifest lists worker evidence existing when it was written; this report and the manifest itself are additional new work records. Parent-owned continuation/transport-note files, initial packet/README and original RED/GREEN evidence were not edited. No protected harness/common, .agents/.codex, dependencies or lockfile path was modified.

## Considered and unbuilt

Generic ASGI/H2 or alternate transport support was not added: no irreversible barrier is proven there, and protected access fails closed. Automatic model retry, checkpoint resume, corrected-answer rewrite, automatic recheck and OCR-triggered current cancellation remain unbuilt because the settled contract excludes them. A persistent API vocabulary cache was not added: the small vocabulary-only per-admission lifecycle avoids shared global ownership and passed exact native comparison. No extra model/quality/capacity reductions or new cancellation policy were added.

`settled_decision_conflicts: []`; `blockers: []` for worker authoring/focused verification. `standalone_shipping_skipped: true`. U7 canonical acceptance remains caller-owned.
