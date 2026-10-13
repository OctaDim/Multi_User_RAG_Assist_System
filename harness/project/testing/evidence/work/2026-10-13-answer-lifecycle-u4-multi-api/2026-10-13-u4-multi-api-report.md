# U4 bounded two-API / production coordinator proof

Created 2026-10-13. Status: focused proof passed; parent-owned canonical full regression, harness checks, review and commit still required. This is application evidence, not harness mechanism acceptance or completion of U4/U8/all MVP gates.

Authority: [active plan](../../../../docs/plans/2026-10-13-0244-feat-rag-answer-lifecycle-plan.md), bounded U4/KTD3/KTD4/KTD5/KTD8, R4/R5/R10/R28/R29 and AE10/AE27/AE28. Inherited native CE route. Starting HEAD f417842; parent-owned production U4 implementation was already present and dirty. Worker owned only backend/tests/integration/ and this new evidence directory. No production edits, dependency/install/lockfile changes, Git index writes, canonical commits, extra agents or downloads.

## Scope and method

The new test uses existing conftest.environment and connection: a unique local PostgreSQL database migrated by actual app.db.migrate, including migration 003. Principal/session/tab and READY source revision records are explicit contract fixtures; G3/G4 remain open. Existing seed_revision creates a published source projection with a real local E5 passage vector. Its 55 repeated factual budget paragraphs are used by every request. Query/passage cosine similarity was 0.8862648269811405, above the unchanged production threshold 0.75. Every passport passed the actual selected chunk and revision; production native allocation measured 2147 Qwen prompt tokens, including source, question, system prompt and thinking-off tail.

The test launches two independently running backend/.venv/bin/rag-api --port 0 processes and reads their actual listening ports from owned Uvicorn stdout. It launches the real app.generation.main supervisor entrypoint through a test-only bootstrap. That bootstrap enables existing DEBUG traces and replaces only the supervisor's worker command with the same bootstrap so its child also enables logging. It does not replace Coordinator, LlamaRuntime, retrieval, graph execution, allocation, decode, settings, cancellation, ACKs or fairness. Every native promotion here is an actual C prefill evaluation; long real prompts keep all requested contexts alive. Answer token/EOS/UTF-8/fault behaviors are owned by the existing U1 and parent U4 native/recovery tests, not re-proven by this focused prefill scenario.

Qwen SHA256: aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223. E5 uses the pinned U3 Xenova/multilingual-e5-small revision 761b726dd34fb83930e26aab4e9ac3899aa1fa78; the new test asserts actual model_quantized.onnx and tokenizer.json SHA256 values from U3 parent-assets-v1.json. No Qwen weights are loaded by the test parent; only the production native child owns Qwen weights.

## Observed contract

- Thirteen distinct conversations/operation keys/tab proofs are submitted through alternating HTTP APIs. The first client's actual HTTP response body is closed without consuming the ACK; replaying that same operation through the second API returns the existing request. Exactly 19 total requests, allocations and release ACKs exist after six later fresh submissions.
- Revision 0 retains twelve simultaneously live nonzero, distinct native pointers and leaves the thirteenth request queued. Four consecutive 3-wide native steps cover all twelve once: final run steps 34–37.
- Actual super_admin PATCH saves revision 1, max_active=6 and step_width=2; GET from the other API confirms applied_revision=1. All twelve pointers remain live and unchanged, and six consecutive 2-wide steps cover all twelve once: steps 38–43. The queued request remains queued.
- Six named active requests are stopped over HTTP and actual native_release traces leave six survivors; the thirteenth still waits. The seventh stop produces the seventh actual native close ACK. Only afterward is the thirteenth admitted: five old pointers remain, its allocation reports physical_active=6/max_active=6/revision=1. The test reconstructs the physical reservation timeline from real ACK traces rather than a logical DB counter.
- super_admin PATCH saves max_active=12/step_width=4/revision=2. Six fresh questions through both APIs restore twelve contexts without changing the retained five pointers or the epoch. Three consecutive 4-wide steps cover all twelve once: steps 53–55. The test checks each logged revision's configured width, promoted group size and unique members.
- API 1 is terminated/reaped and launched again while API 2 serves the existing request. All active pointers and native epoch remain unchanged, only one native_spawn occurs, and another full 4-wide round covers all twelve: steps 56–58. Restarted API GET confirms saved max_active=12/step_width=4 and revision=applied_revision=2.
- All nineteen owned requests are stopped through HTTP. The test waits for nineteen distinct actual native_release ACKs and an empty physical reservation set before shutdown. Every owned Popen is reaped; supervisor shutdown asserts its native child PID no longer exists in /proc.

Final run API process IDs were 164409 and 164430, replacement API 164596; native child 164378, epoch 2. One /proc/native-PID/statm observation with twelve contexts measured resident memory 3,492,691,968 bytes. This is a point measurement for the native process at twelve, not a peak, joint OCR/API/worker load benchmark or capacity claim above twelve. See [run-03-proof-summary.json](run-03-proof-summary.json).

## Verification evidence

behavior_changed: test-only; production behavior unchanged. Existing tests inspected: backend/tests/test_scheduler.py, test_service_recovery.py, test_http.py, conftest.py and runtime/test_generation_contract.py. Their production implementations/callers and current app/rag.py, app/settings.py, app/answers.py, API routers, app/generation.py and app/llama_runtime.py were inspected. Tests added: backend/tests/integration/test_multi_process.py. Existing tests were used unchanged; full-suite authority remains with the parent.

Evidence strategy: characterize the existing production mechanism before any proposed production change; no production change proved necessary. [run-01-pytest.log](run-01-pytest.log) records 1 failed in 46.99s: the test incorrectly expected snapshot.active rather than the API's existing requests[] contract. Before that test error, the real trace reached twelve pointers, default fair round and a hot-shrink fair round retaining all twelve. Only test snapshot access was corrected. [run-02-pytest.log](run-02-pytest.log) then records 1 passed in 70.30s. The first ACK scenario was strengthened to close the HTTP response without reading its body, and E5 pinned hashes plus exact allocation/ACK counts were added. [run-03-pytest.log](run-03-pytest.log) records the final version: **1 passed in 63.95s**. Python AST syntax check passed. There is no fabricated production RED failure and no test exception.

Focused invocation from backend (actual runs also set a fresh RAG_MULTI_API_RUN_NAME and this directory as RAG_MULTI_API_EVIDENCE_DIR to save raw subprocess stdout):

```sh
RAG_MODEL_PATH=/tmp/rag-answer-lifecycle-models/Qwen3.5-2B-Q4_K_M.gguf \
RAG_E5_DIR=/tmp/rag-answer-lifecycle-models/e5 \
.venv/bin/python -m pytest tests/integration/test_multi_process.py -q -s
```

Local PostgreSQL/HTTP/native subprocess execution used the already authorized escalated execution surface. No install was needed. Runs 01/02/03 each retain their original pytest/supervisor/API stdout files. The separate run-*-native-trace.jsonl files preserve the original native JSON lines verbatim, including the parent native_spawn; all raw files were created at new paths without overwrite. [2026-10-13-raw-hashes.json](2026-10-13-raw-hashes.json) records raw/summary SHA256s. Test defaults save logs to its unique pytest temporary directory; canonical full-suite reruns do not overwrite these evidence files.

## Parent handoff and limits

Changed paths: backend/tests/integration/test_multi_process.py, the integration README.human.md guide, and only this new evidence directory's human guide, report, summaries, immutable logs and hashes. The worker did not touch parent-owned production/test/evidence files. No settled decision conflicts or production blockers were found. Native slot is released after successful cleanup.

The parent must inspect the final files and rerun every earlier application regression test and every active harness test as explicitly requested by the user, then own canonical review/commit. This focused result supplements parent U4's mock scheduler/native/fault tests; it does not close all U4 or U8 acceptance by itself. Browser, frontend, SSE handoff barriers, real identity issuer, document/OCR publisher, deployment and joint resource-load acceptance were outside this bounded proof. Persisted settings are proved across a healthy API restart here; coordinator restart/ownership loss is covered by parent-owned existing tests rather than a second model restart in this scenario.
