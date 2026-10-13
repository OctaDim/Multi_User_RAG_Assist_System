# D1 worker result — implementation/local verification complete

Created 2026-10-13. Application evidence only. Base HEAD remained
`42a51a5372f98b1a319178bb287d01d2e7af34df`.
Authority: [bounded packet](2026-10-13-d1-bounded-packet.md), SHA256
`9b5e78536da1df102a8dff04e609f24fa1a7b77ff4f0fabe140e357f6db70a87`.
Native CE/shared-workspace worker. Parent owns review, full regression, staging,
canonical commits, integration and remaining lifecycle gates.

## Result

Real email/password registration creates an unverified ordinary account and its
initial personal empty conversation. Configured SMTP sends a one-hour verification
link with its credential in the URL fragment. Successful confirmation consumes all
account verification links atomically, without changing active/disabled flags.
Registration retries with the original password can resend after a transport
failure; out-of-order email delivery does not invalidate an unused, unexpired link.
Verification never returns a secret. Normal login issues an opaque 12-hour session.
Passwords use salted OpenSSL scrypt via Python hashlib (`n=131072,r=8,p=1`), outside
the API event loop, with constant-time digest comparison and one KDF operation per
API process to bound its 128 MiB working memory. No dependencies were added.
Evidence: [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
and [Python hashlib](https://docs.python.org/3/library/hashlib.html#hashlib.scrypt).

The operator-only CLI creates an email-bound one-use super_admin invitation;
ordinary registration UI consumes it and email still must be confirmed. Protected
account mutations record public before/after values. Super_admin provisions roles;
admin can block/soft-delete ordinary users and cannot change roles or access foreign
history/global settings. Sessions and accepted executions survive no-op and
role-only changes while personal access remains permitted. Actual access loss
increments the account epoch, revokes sessions and uses the existing shared
terminal transition. Logout revokes only its originating session's executions.
Documents, messages and checkpoints are retained.

New requests require an originating non-secret session identity, with an owner FK.
Saver/coordinator guards recheck that session before future writes/publication.
Migration005 preserves prior history and interrupts pre-existing unfinished rows
whose originating session cannot be proven. Migrations001–004 were untouched.
Mutations take write locks before session revocation; terminal processing locks only
tabs/conversations belonging to affected unfinished requests, rather than every
conversation of the owner. No network await holds a DB transaction lock.

The independent static HTML/ES module UI supports signup, mailbox-link confirmation,
login, personal empty history, logout, roles/block/soft-delete controls, exact-origin
CORS, visible labels and narrow screens. Password/token validation errors do not
echo rejected input. Frontend uses textContent and clears tab credentials/drafts
on logout/owner switch. It needs no production framework or build tool.

## Verification evidence

`behavior_changed: true`. Existing tests/callers inspected: principal/bearer,
admission/stop/snapshot/common transition, GuardedSaver/run_graph, every coordinator
guard caller, tab/event reads/deadlines, source mutation, settings authorization,
migration/resource packaging and every account/session/request INSERT under backend.
Existing test files inspected included conftest, test_admission, test_http,
test_rag_context, test_scheduler, test_stream_recovery, test_source_contract,
test_settings and browser/test_draft_lifecycle.

New tests: tests/test_accounts.py (14 collected cases), tests/browser/test_accounts.py
(2 cases), real local SMTP/browser mailbox helper tests/mailbox.py. Existing fixture
and admission uniqueness clone now carry session identity. Existing HTTP/admission,
coordinator/scheduler, tab recovery and nine named non-native RAG tests were used
unchanged except the necessary fixture/clone schema adaptation.

- [Initial RED](2026-10-13-d1-red-registration.log): registration returned 404 before
  any production write. Test used real PostgreSQL and an owned SMTP receiver.
- [Clean final boundary RED](2026-10-13-d1-red-final-boundaries-clean.log): 3 actual
  failures before the respective fixes: unused resent link was refused, no-op
  cancelled the accepted request, promotion cancelled the accepted request.
- [Current focused GREEN](2026-10-13-d1-focused-green-v3.log): **78 passed in 62.00s**,
  no skips/deselections. Successful browser accounts were created through actual
  UI/SMTP/link/login/operator CLI/admin forms on actual `.venv/bin/rag-api`.
  API/static/mailbox origins were independent; successful traffic was not mocked.
  Real Chromium checked desktop and 375px width. All owned processes were reaped.
- `git diff --check`: passed.
- [Frozen bytes](2026-10-13-d1-byte-freeze-v1.json): SHA256 of all 21 owned application
  paths, source packet and immutable raw logs. No app edits after this snapshot.

Focused GREEN command from backend (existing venv, owned local sockets required):

```sh
.venv/bin/python -m pytest tests/test_accounts.py tests/test_admission.py tests/test_http.py tests/test_scheduler.py tests/test_stream_recovery.py tests/test_rag_context.py::test_actual_async_graph_commits_fragments_before_model_callback tests/test_rag_context.py::test_not_ready_selected_and_unmatched_ready_sources_are_distinct tests/test_rag_context.py::test_interrupted_text_is_visible_but_absent_from_new_graph_and_checkpoint tests/test_rag_context.py::test_transitive_history_provenance_removes_derived_text_and_keeps_ui tests/test_rag_context.py::test_delayed_checkpoint_and_pending_writes_are_denied_after_correction tests/test_rag_context.py::test_correction_before_late_complete_marks_original_without_cancelling tests/test_rag_context.py::test_deselected_source_cannot_reenter_current_model_scope_through_history tests/test_rag_context.py::test_every_saver_operation_rechecks_access_identity_and_epochs tests/test_rag_context.py::test_malicious_doc_cannot_expand_scope_and_invented_quotes_are_rejected tests/browser/test_accounts.py -q -s --tb=short --assert=plain
```

Earlier actual observations are retained, not promoted to successes: sandbox setup
could not write pgserver's `/run/user/1000` lock until the authorized escalation;
browser test launch via `python -m app.main` did not start an API and was replaced
with the existing rag-api entrypoint; a broad test_rag_context invocation produced
45 passes plus two setup errors for missing RAG_E5_DIR/RAG_MODEL_PATH (no native
model loaded); [combined attempt v1](2026-10-13-d1-focused-green-v1.log) failed
collection because both account modules had the same basename. A minimal browser
package namespace fixed that actual full-collection collision. [v2](2026-10-13-d1-focused-green-v2.log)
passed 75 cases before the final three boundary cases/fixes.

The earlier [resend RED raw log](2026-10-13-d1-red-resend.log) contains a verification
proof expanded by pytest's assertion renderer. Its disposable DB was fully dropped;
the proof is unusable. The raw bytes remain immutable. The clean RED above supersedes
it for review; final evidence capture used plain assertions to prevent credential
expansion. No live proof/session/password is recorded in the final evidence.

## Owned changed paths

```text
backend/app/accounts.py
backend/app/api/accounts.py
backend/app/answers.py
backend/app/auth.py
backend/app/generation.py
backend/app/main.py
backend/app/rag.py
backend/migrations/005_accounts.sql
backend/tests/conftest.py
backend/tests/test_admission.py
backend/tests/test_accounts.py
backend/tests/mailbox.py
backend/tests/browser/test_accounts.py
backend/tests/browser/__init__.py
frontend/README.human.md
frontend/index.html
frontend/src/README.human.md
frontend/src/api.js
frontend/src/app.js
frontend/src/auth.js
frontend/src/styles.css
```

Owned evidence additions are this report, the byte snapshot and six raw logs named
above. Parent-created packet/guide, dirty plans/notes and D2 OCR evidence were not
edited. No Git index/commit/push, installs, new subagents or full/native suites were
performed. The two inadvertent model-fixture setup attempts above remain explicit.

## Deliberate boundaries and return metadata

No SSO, billing, recovery, broker, retry worker, alternate provider, model fallback,
document upload/OCR/permissions/quotas, answers/draft/passport UI or rate-limit
product controls were built. D2 and U6 own those declared dependent surfaces.
Only owned local SMTP was exercised; real external SMTP TLS/auth deployment was not
tested. Existing SQL principals/documents remain component-only regression fixtures,
not the real-issuer browser acceptance accounts.

Manual browser walk outside pytest, real documents/OCR, actual irreversible ASGI
transport handoff (U7/U8), full application/runtime/browser/integration/harness
regression and canonical commit remain parent-owned. **G3 and the entire lifecycle
are not complete.** Physical native cancellation proof is unchanged and was not
rerun by this worker.

Return metadata: `status=complete` for D1 implementation/local verification only;
`u_ids_attempted=[D1]`; `u_ids_completed=[D1]`; `behavior_change=true`;
`implementation_engine_binding=null`; requested/actual route native CE via Codex
collaboration shared-workspace worker; requested_model=null; actual_model=unverified
(no model receipt); requested_effort=null; fallback_reason=null; run_id=null;
source_kind=plan (bounded packet); source_digest as above; plan_checkpoint=null;
blockers=[]; recovery_path=null; settled_decision_conflicts=[];
standalone_shipping_skipped=true. Receipt: implementation and focused verification
complete, owned test resources reaped, no detached worker processes, parent review/
authoritative verification/integration/canonical commit pending.
