# U6 searching event and regression supplement — acceptance still open

The user requires every U to run ALL accumulated application regressions (including native, integration and browser tests) plus ALL active harness tests before advancement. No stage is accepted from a subset. U6 remains uncommitted and unaccepted; U7/U8 have not advanced.

## Changes and review

`Coordinator.prepare_next` changed requests to searching without increasing version or publishing an event. The new PostgreSQL regression reads through an independent connection at the actual graph embedding boundary: the searching state and matching event must already be committed, then the graph publishes the next queued version. RED showed searching/version1 instead of version2 (1 failed,1.94s). The minimum fix increments the version and inserts the existing state-event shape within the same guarded transaction, before graph work. No new abstraction, lock during CPU work, dependency or generation retry was added.

This is a component contract test using the existing deterministic embedding/tokenizer fixture; it is not native-generation, OCR or real-user acceptance proof. Existing actual native/browser proofs retain their separate classification.

The first wider focused run passed47 tests but had two setup errors because the command omitted RAG_E5_DIR and RAG_MODEL_PATH: `test_real_e5_mean_pooling_and_real_pgvector_retrieval`, `test_real_qwen_overloaded_prompt_fits_and_passport_reports_only_passed_fragments`. Its raw log is retained, not reported green.

The first complete nonbrowser run with model paths yielded138 passed and1 failed in397.72s: `test_real_supervisor_reaps_native_process_before_replacement`. Physical reap, preserved prefix, interrupted/execution_lost, excluded assistant and replacement-epoch assertions passed; the final historical counter incorrectly assumed only one state event. The recovery assertion now checks the exact ordered phases [searching,generating], preserving the prohibition on a second generation after replacement. It does not merely increase an aggregate count. All in-repo count/state assertions were searched; this was the sole caller needing adjustment.

The actual native crash/replacement test plus the searching regression passed2/2 in13.56s. Native predecessor269380 was reaped before replacement269443; epoch2→3; a committed prefix survived, no resumed generation. Exact three child logs are preserved here.

Inline review supplement (agent-thread limit remains): reuse follows existing answers.event and guard; quality verifies commit-before-embedding and one generation after crash; efficiency adds one durable event with no lock across graph compute. The only additional owned source paths are backend/tests/test_scheduler.py and backend/tests/test_service_recovery.py; backend/app/generation.py was already owned by U6. No changes were made during the final repeated run.

## Repeated intermediate verification

- ALL nonbrowser backend tests: **139 passed in406.85s**, exit0; real Qwen/E5/OCR assets, actual PostgreSQL and process recovery, no pytest skips/deselections inside this selected subset.
- ALL active harness tests: **168 passed in32.00s**, exit0. Earlier new run also passed168 in36.81s; both raw logs retained.
- Python compileall, all frontend JavaScript syntax checks, source-only git diff --check passed. No separate configured linter/typechecker.

The application command intentionally uses --ignore=backend/tests/browser because actual Chromium startup is blocked by the already documented WSL kernel condition. This is an explicitly incomplete intermediate run, NEVER the all-application U6 gate. Command:

```sh
RAG_MODEL_PATH=/tmp/rag-answer-lifecycle-models/Qwen3.5-2B-Q4_K_M.gguf RAG_E5_DIR=/tmp/rag-answer-lifecycle-models/e5 RAG_OCR_DIR=/tmp/rag-answer-lifecycle-models/ocr uv run --project backend --frozen --cache-dir /tmp/rag-answer-lifecycle-uv-cache pytest -c backend/pyproject.toml backend/tests --ignore=backend/tests/browser --basetemp /tmp/rag-u6-all-nonbrowser-v2 -q -s --assert=plain
uv run --project backend --frozen --cache-dir /tmp/rag-answer-lifecycle-uv-cache pytest -c pytest.ini --basetemp /tmp/rag-u6-all-harness-v3 -q
```

## Remaining work and blocker audit

This is the second consecutive goal turn with the same observed blocker. Own bwrap261860/261877/261981 remain D/rtnl_lock; no additional sandbox/browser namespace was launched. The user restart question is still pending. Approved direct commands and actual native/DB tests work; no automatic approval rejection occurred. All owned test/native/DB processes have finished; only the previously documented uninterruptible helper remnants cannot exit before kernel recovery. Do not force a WSL shutdown that would stop all user Linux processes.

After user-reported recovery, verify runtime state, finish the actual stale-snapshot/browser regression and separate fresh-DB manual full-answer desktop/mobile walkthrough, resolve remaining actual UI review findings, then run ALL backend tests with no ignore/skip/deselection and ALL harness tests on the final source. Only then accept/commit U6 and advance. U7 transport handoff fences, U8 joint/quality/AE acceptance and final shipping review remain required. General handwriting G4 remains open due to the documented missed crop; no quality thresholds or model/cap limits were lowered.

## Preserved raw evidence

- `2026-10-14-all-harness-v2.log`: SHA256 `6dbedc51ac2c7894d45a8896e80459b651b1a16e8ca2bf214e8b74e9be5375fe`, 261 bytes.
- `2026-10-14-all-harness-v3.log`: SHA256 `81b4f9bd9a0ae707fa3eab31468fb47bccc1e9c9475dacb93be2d5a8f5d29425`, 261 bytes.
- `2026-10-14-all-nonbrowser-v1.log`: SHA256 `70987ec88875a68ed15837b22f7707bb2685aec942d76caf365419e938c53f68`, 2014635 bytes.
- `2026-10-14-all-nonbrowser-v2-competing-supervisor.log`: SHA256 `da1ed740a9af14ee033fc2d51832a7a555d2d990e00d03413eccd2bd1ac8b2f8`, 1300 bytes.
- `2026-10-14-all-nonbrowser-v2-first-supervisor.log`: SHA256 `0c7a9caa9f600e37ebfb77bda690e33b4a887292b20a052280ce4c84012c370e`, 100918 bytes.
- `2026-10-14-all-nonbrowser-v2-second-supervisor.log`: SHA256 `7ee44b70cd178535c813e95aa9f759e913214235e59a34ed6bd657c4f4947549`, 56439 bytes.
- `2026-10-14-all-nonbrowser-v2.log`: SHA256 `a31dc25f073893ac77ca821dca387ed589cd90b4ca0d552b268fd85389a409ca`, 2009273 bytes.
- `2026-10-14-search-recovery-green-v1-competing-supervisor.log`: SHA256 `82a1f715c6f11ce6ed54da0299a6dac73318a4cae9646086ad597f47e717e16e`, 1307 bytes.
- `2026-10-14-search-recovery-green-v1-first-supervisor.log`: SHA256 `7d5fc87e6efbd0c2e8db39df2138f943543f4f79c2fc997184f3251a6599595b`, 100926 bytes.
- `2026-10-14-search-recovery-green-v1-second-supervisor.log`: SHA256 `cabb6daf9e2b4e601ee71d13c7df67b1d013907bbcb4ccc75155c414051bf6a6`, 56439 bytes.
- `2026-10-14-search-recovery-green-v1.log`: SHA256 `788b2c43375dcd5c0dfec7ade5db34d401f34aa85171cf526dab0ea451a57024`, 389 bytes.
- `2026-10-14-search-state-green-v1.log`: SHA256 `6f4d7ed63c9c952a4eb2d36022d7e9eb91ed2d0fd8b3ebea05d678f2955d7fac`, 2189 bytes.
- `2026-10-14-search-state-red-v1.log`: SHA256 `7323f2cf792dd11e63405bad760ac975b922c3c04cb27eef2c8b1e1ccadf0cbe`, 2369 bytes.
