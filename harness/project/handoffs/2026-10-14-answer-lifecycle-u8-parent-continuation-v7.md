# U8 parent continuation v7 — 2026-10-14

Original goal remains active: execute immutable answer-lifecycle plan through U8. No final acceptance, commit, push, PR or deployment. RAG-67 latest per-word/model OCR contract remains authoritative. Full application and full harness must pass after every U stage.

## Closed jobs and established failures

ALL application v2 closed session92332 exit1: **3 failed, 240 passed, 3608.01 seconds**. Unfiltered, nine actual assets, source freeze v2 135 paths unchanged throughout. ALL harness v2 closed exit0: **168 passed, 24.10 seconds**. All raw negative logs and source receipts retained. Do not promote historical v44 or v9 results to current final PASS.

Three failures: whole-pdf refresh button disabled for30seconds after two correct actual OCR pages; joint real30accounts memory sample had9 physicalcontexts rather than12 after three cancellations in prefill; frozen30 mechanical27/30, eng24 UUID citation, rus4/bel4 omitted slave trade despite correct source excerpts. No measured root cause yet for first two; discard speculation about OCR cache/OOM/model completion. Original RAG answer corpus/expected facts and matchers unchanged.

Read-only CE diagnosis agent /root/u8_stall_and_cancellation_diagnosis completed; report `2026-10-14-parent-native-stall-diagnosis-v1.json` in U8 evidence. No production rootcause established. FirstAPI previously DEVNULL; API2 logs don't describe UI service. Three releases while prefill128/128/96; natural answer completion excluded. Presence expiry remains hypothesis until real reason/ACK timing captured.

## Current source changes after frozen ALLv2 closed

- app/rag.py numeric primary source id plus retained trace_id UUID, existing exact numeric citation. Generic original wording instruction now includes every relevant clause. Meaningful new XML-attribute test RED observed before fix. GREEN **2passed2.78seconds**: new numeric/trace identity test and unchanged old actual Qwen overloaded prompt/passport test. Logs `parent-citation-identity-{red-v1,green-v3}.log`. Earlier green-v1 failed sandbox pgserver lock; green-v2 missing model environment: infrastructure negatives retained, never counted as product PASS.
- browser/test_accounts.py fixture captures first API stdout/stderr in api-first.log, reaps process then closes file.
- integrated_browser diagnostic launcher wraps async Coordinator.finish and logs native_finish_attempt reason/state without extra awaits/DB operations or changing decisions.
- new U8 diagnostic-only exception capture: whole-pdf pending refresh writes actual-refresh-stall-diagnostic.json with PG waits/blockers and document files. Joint memory mismatch writes actual-joint-interruption-diagnostic.json with requests reasons, real tabs ACK/deadlines and PG activity. Existing assertions/deadlines/capacity remain intact.

Current source no longer equals v2 freeze; do not mislabel v2 as current. New freeze v3 needed once actual fixes are done. Baseline144app/72harness namedtest function AST bodies must remain unchanged; fixture body and new U8 tests can change.

## ACTIVE exclusive native job

Root session **67903**: `python3 /tmp/rag-u8-parent-diagnostic-native-v1.py`, started with granted require_escalated because actual PostgreSQL pgserver lock and local browser/server ports require it. Runner contains exact owned sequential three pytest selectors: joint30accounts/12contexts first, whole-pdf20pages second, frozen30questions third. No other native/browser/server task may overlap. No PYTEST_ADDOPTS. Actual paths RAG_MODEL_PATH2BQ4_K_M/RAG_E5_DIR/RAG_OCR_DIR installedassets unchanged. Logs **2026-10-14-parent-diagnostic-native-v1.log** and eventual exit receipt **2026-10-14-parent-diagnostic-native-exit-v1.json** in U8 evidence. Basetemp `/tmp/rag-u8-parent-diagnostic-native-v1`. This is targeted diagnostic validation, not final ALL. Source edits must not occur while job runs.

Poll with write_stdin at most50sec and inspect small raw tails/diagnostics. Communicate Russian useful findings within60sec. If failures recur use actual request reason/firstAPI/PG evidence; don't invent causes or alter acceptance thresholds. New production fix only after meaningful causal RED. Need actual final frozen30 semantic/citation audit, final complete ALLapp+ALLharness, final source/assets/lib/oldtest preservation/resource checks, exact own staging and local U8 commit, then goal complete. No final answer until plan gates close.

## Staging and ownership

47 original owned paths staged in parent-review-staging-v2 receipt before ALLv2; current app/rag.py, fixture/diagnostic edits and new test_rag_context.py test are unstaged/new changes relative index. Evidence/handoffs currently ordinary untracked. Branch octadim/create-plan-1, HEAD122554c808d34ccb1ea679891efb58102b61a1a6. Do not broad gitadd, mutate completed evidence/immutable plan/corpus/AGENTS, or touch mechanism INDEX without applicable inbox. Existing RAG67 is discoverable via project decisions routing; no INDEX edit needed.
