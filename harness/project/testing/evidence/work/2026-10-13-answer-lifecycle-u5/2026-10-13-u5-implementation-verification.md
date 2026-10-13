# U5 implementation and focused verification

Created: 2026-10-13. Application work evidence; U5 implementation frozen for parent review and accumulated regression. Native CE route was already authorized. Base: a45679bef131e14532d5e0609dc73dbc6bd8ed5e. This is component/backend delivery evidence, not whole-lifecycle acceptance.

## Changed application paths

- `backend/app/events.py`: authenticated tab registration, connection epochs, one-use heartbeat challenges, confirmed presence, durable grace/deadline processing, owner-filtered committed snapshot/replay read boundary.
- `backend/app/api/tabs.py`: tab registration, header-only proof/epoch/challenge ACK, one authenticated tab-level fetch SSE stream for all owner conversations; DB transactions end before network yields/poll waits.
- `backend/migrations/004_tab_presence.sql`: additive presence/challenge columns and due index. Applied migrations 001/002/003 unchanged.
- `backend/app/answers.py`: require confirmed live originating presence for new admission; preserve current-access/proof checked operation dedupe; use tab-before-conversation order; common history projection and service barrier for consistent snapshot watermark.
- `backend/app/main.py`: register tab routes and durable deadline sweeper in every API process; lifespan owns/cancels its task.
- `backend/app/rag.py`, `backend/app/generation.py`: check the originating tab deadline before delayed search/model/saver publication, even when timer processing is delayed. Final terminal cleanup remains available after expiry.
- `backend/tests/test_stream_recovery.py`: 23 new component/real PostgreSQL and real HTTP tests (including parametrized cases).
- `backend/tests/conftest.py`: component-only account/source fixtures establish projected presence through normal connect/challenge/ACK functions; fixtures explicitly do not claim G3/G4 issuer/publisher/browser acceptance.
- `backend/tests/integration/test_multi_process.py`: old real U4 HTTP/native caller creates a real tab through HTTP and holds one actual SSE plus heartbeat ACK thread on the surviving second API for all 19 background conversations. Thread stop/join and process cleanup retained. Native integration not rerun by U5 implementer.

`backend/app/api/answers.py` needs no signature/route change: existing HTTP admission calls the strengthened shared `answers.admit`. Existing fixture-backed admission callers share the updated environment presence. No Git index writes/commits/pushes; no dependency installs or actual model loads.

## Behavior changed

Admission no longer accepts possession of a tab proof as evidence of a live originating connection. A new question requires the server's stream challenge to have been ACKed. Dedupe of an already accepted operation remains possible after current auth/ownership/proof checks and does not create a second question or graph identity.

Disconnect sets a durable 10-second grace deadline for all unfinished originating requests, including accepted/searching and background conversations. Heartbeat loss detection uses a 15-second ACK lease; grace starts at detected lease expiry, independently of timer callback delay. Observers cannot renew initiator presence. Epoch changes fence stale close/ACK callbacks. A pending reconnect retains the prior grace deadline; only a timely challenge ACK clears it. Late reconnect first settles expired operations, then can establish new confirmed presence for a new explicit question. Terminal requests never resume.

Lock order is service → current account/session → documents when required → originating tab → conversation(s sorted) → request(s). Presence processing does not acquire document write locks. One tab per deadline transaction avoids holding A's conversation while waiting on B's tab lock. Model/saver reads now take tab SHARE before conversation/request. Existing source mutation paths do not lock tabs. Account SHARE is never promoted to UPDATE.

Snapshot and tab replay reads briefly take the existing service UPDATE barrier. Existing production writers already take service SHARE, so a lower allocated but uncommitted event ID must commit before the read watermark can advance past it, including writes in different conversations. The barrier is released before network delivery or backpressure. This deliberately serializes these short DB reads against service writers; throughput is not measured here.

## Existing tests inspected and used

Inspected `test_admission.py`, `test_http.py`, `test_scheduler.py`, `test_rag_context.py`, `conftest.py`, and the actual HTTP/native caller in `integration/test_multi_process.py`, together with production guards, transitions, source invalidation and all tab/admit/snapshot callers located by ripgrep.

Focused regression uses `test_stream_recovery.py`, `test_admission.py`, `test_http.py`, `test_scheduler.py`, and `test_rag_context.py` with `-k 'not test_real_'`. The existing HTTP/admission/scheduler/context tests remain behaviorally unchanged except the shared component fixture now confirms presence. All runtime doubles remain test-only.

## RED and GREEN

Original immutable logs are stored beside this report.

- `2026-10-13-u5-red-01.log`: test launch blocked by uv default cache read-only path; infrastructure failure, not behavioral RED.
- `2026-10-13-u5-red-02.log`: moved uv cache to `/tmp`; pgserver setup blocked by sandbox `/run/user/1000` lockfile; infrastructure failure, not behavioral RED.
- `2026-10-13-u5-red-03.log`: authorized local PostgreSQL execution, **expected behavioral RED** before production edits: `test_admission_requires_confirmed_connection` failed `DID NOT RAISE AccessError` because proof-only admission still succeeded.
- `2026-10-13-u5-green-01.log`: initial recovery suite, **14 passed**.
- `2026-10-13-u5-green-02.log`: focused files, **56 passed, 2 setup errors**. `test_rag_context.py` also contains two real-asset tests; missing `RAG_E5_DIR`/`RAG_MODEL_PATH` stopped those fixtures. No native model was loaded. These cases were then explicitly excluded from this implementer's scope.
- `2026-10-13-u5-green-03.log`: expanded model-free focused suite, **60 passed, 2 deselected**.
- `2026-10-13-u5-reconnect-regression-red-01.log`: **expected regression RED** for reconnect at t=9 / ACK at t=11. This additional test was added after the deadline retention fix, so this is honestly a replay of the old `connect` deadline-clearing bug, not a claim of preimplementation chronology. A temporary script replaced only the stored deadline argument with `None`, ran this one test, and restored the exact current `events.py` bytes in `finally`; failed `DID NOT RAISE AccessError` as expected.
- `2026-10-13-u5-green-04.log`: final focused command below, **60 passed, 2 deselected in 26.72 seconds**. Adds explicit fresh admission after expiry and timely t=9.5 ACK / exact t=10 expiry race coverage. `git diff --check` passed.

Final command:

```sh
UV_CACHE_DIR=/tmp/u5-uv-cache uv run --project backend --no-sync pytest backend/tests/test_stream_recovery.py backend/tests/test_admission.py backend/tests/test_http.py backend/tests/test_scheduler.py backend/tests/test_rag_context.py -k 'not test_real_' -q
```

PostgreSQL/HTTP runs used authorized sandbox escalation for real local sockets/pgserver. No logical 10-second grace sleeps were used: tests control the normal shared time reader or advance the persisted lease in the real API death test. Short polling waits only observe real DB locks/process readiness.

## Tests added/changed and evidence limits

Added coverage proves accepted/searching/queued/generating grace; timely recovery; observer independence; immediate stop/failure and completion preservation; late reconnect expiry without waiting for a timer callback; stale epoch close/ACK rejection; owner/proof checks; multiple background conversations and missed ACK detection; one-use stream challenges; pending reconnect's late ACK cannot extend original grace; fresh explicit question after timeout; exact deadline race serialization; snapshot/replay consistency across lower-uncommitted and higher-committed IDs on two PostgreSQL connections; immutable redelivery IDs and monotonic cursor progress; session revocation checked per replay; no second native context allocation/operation on recovery using a test runtime; stale search callback blocked before fragments or graph start.

The actual HTTP test starts two normal `rag-api` processes with no native generation process. It receives initial SSE challenge on API1, ACKs/admitted through API2, reads shared state, kills API1, advances the durable lease and observes API2 interrupt the same operation without starting a graph. Its auth/document entities are explicitly component fixtures, so this is not real account issuer/document publisher or user browser acceptance.

No test exceptions are claimed for new nontrivial logic. New migration/presence/read/route behavior is exercised by the added DB and actual HTTP tests. Existing real native integration caller adaptation was inspected but remains unrun here; parent owns its real-model regression. U6 still must prove the browser reducer ignores duplicate IDs rather than appending a prefix twice; U5 proves stable duplicate event identity and snapshot/cursor behavior.

## Remaining gates and considered-but-not-built

- **KTD8 actual irreversible transport handoff/revoke/backpressure fence: U7/U8 remains unimplemented/unproven.** `events.read` rechecks auth/proof/epoch/current connection for every DB read/replay and provides the common read boundary, but Starlette `StreamingResponse`/ASGI send does not prove a shared invalidation fence at actual byte handoff. A revoke or source/request mutation after DB read but before transport send is still a transport gate. No DB locks are knowingly held while awaiting network backpressure.
- **Real browser/proxy heartbeat and hidden-tab behavior: U8 unrun.** No visibility/navigation flag is used as disconnect. Exact browser timing, throttling and proxy behavior still need real UI acceptance.
- **G3/G4 real account issuer/document publisher and user UI/browser acceptance:** not closed by component fixtures. The user-required actual E2E creation remains U8 prerequisites.
- Full accumulated application/native/runtime/browser/integration and all active harness tests are parent's responsibility after U5 review; not claimed by this focused report.
- No second journal/event allocator, broker, production framework, retry/fallback/resume mechanism, arbitrary admission cap, test-only production export/flag, or owner-wide lock was added. The existing service barrier is the smallest current-schema fix for cross-conversation commit-order gaps.
