# Frontend refactor implementation evidence

## U1: optional source scope

Behavior changed: yes. Inspected admission, sources, RAG context tests and actual paths. Worker added/strengthened those three suites before production writes: 7 failed, 1 passed, 48 deselected (empty [] rejected and mode metadata absent). Worker focused green: 56 passed in 79.74s. Parent inspected actual six-file diff and authoritatively ran backend/.venv/bin/python /tmp/run-rag-front-tests.py backend/tests/test_admission.py backend/tests/test_source_contract.py backend/tests/test_rag_context.py -q --tb=short --show-capture=no: 56 passed in 70.09s. Existing local model paths passed from service configuration; fixtures isolated DB/owners. Temporary PostgreSQL socket permissions required escalation. No schema, lifecycle or wildcard changes.

## U2: three-area shell, auth and shared operations

Behavior changed: yes. Before production writes, launcher injection test plus new workspace browser tests failed: 3 failed in 31.56s, specifically missing request-timeout meta, chat area and bootstrap retry control. Styling/layout uses chosen C and deliberate browser verification instead of style unit tests.

Parent authoritative command: backend/.venv/bin/pytest backend/tests/test_frontend_launcher.py backend/tests/browser/test_frontend_workspace.py backend/tests/browser/test_accounts.py -q --tb=short: 33 passed in 45.12s. Actual isolated API/SMTP signup, verification, login, roles, disable/soft-delete/logout, public policy failure/retry and navigation at 1440/768/375 passed. Launcher HTTP allowlist/HEAD, config injection and shutdown/restart passed. JavaScript syntax and git diff --check passed. No dependencies added.

This remains an open implementation record; whole-goal acceptance is not complete.

## U3 and latest layout direction A

User explicitly superseded C with A (central conversation, on-demand adjacent evidence, separate documents/admin). Plan and source shell updated; C is historical only.

Behavior changed: yes. Worker inspected reducers/lifecycle, observed new scope test fail before production edits (missing selectSources), then 3 reducer tests passed. Parent initial browser/reducer batch: 6 passed/3 failed in 182.04s; real failures exposed focus removal on unavailable-source uncheck and late create overriding navigation. Fixed stable source checkbox and selection intent generation. Subsequent tests exposed fixture timing (reading selected conversation before create completed) and a role locator excluding hidden stop controls; corrected those waits/locators while preserving assertions.

Latest evidence: selected old answer/citation/mobile/reload scenario passed in second batch; targeted scopes and stop503/terminal-before-late-POST passed 2 in 28.99s. Existing real early-fragments and delayed-ACK/independent-conversations scenarios passed 2 in 95.95s. Initial batch also passed 3 reducers, 2 A workspace/policy-retry tests and existing independent-draft/no-source test. Existing local models used, actual isolated SMTP/API/document worker/generation retained. No dependency installation or mock-only answer proof.

Ordinary frontend: initially found existing configured port 55848 occupied by project frontend PID18915; actual HTTP200 still contained unresolved new timeout placeholder because old launcher code was loaded. Verified cwd and exactly python frontend/main.py, restarted that stateless frontend only, preserving config. New owned session19876 ordinary command python3 frontend/main.py listens 127.0.0.1:55848; HTTP200 serves A and numeric request-timeout-ms30000. Backend/API not restarted in this step.

## U4: documents and editor

Behavior changed: yes. Inspected actual documents API/state and existing two browser document scenarios. Before production replacement, new editor refresh/guard/conflicting-save scenario failed in 38.30s at missing processing-refresh action. Extracted independent Documents controller, preserved editor/URLs across list refresh, guarded discard/delete, separated queued from published correction, preserved owner/read-only context, guarded late reads and partial upload uncertainty. Local operation feedback and focus restoration included.

Initial command (documents + accounts + workspace) gave 8 passed/1 failed in 176.09s: PDF worker had been given backend directory as RAG_OCR_MODEL_PATH by the temporary runner when handwriting config was empty. Fixed test preparation to use only four model environment values from canonical launch_environment, including its generation fallback (no production DSN/SMTP injection). PDF-only retry passed 1 in 88.56s, real native OCR and unchanged original.

Strengthened existing TXT/guard scenarios to check queued save visibly unavailable, preserved working text and late first-document read cannot replace a second selected document. Targeted latest two tests passed 2 in 16.37s. Actual signup/SMTP/upload/E5/download/correction/new revision/delete cancellation and confirmation exercised. Failed save retained editor text; repeated status read did not clear it. Account/navigation checks remained green; no dependencies, schema or production local overrides changed.

## U5: administration

Behavior changed: yes. New real-role/settings/library test failed before implementation at missing management reload control (12.28s). Extracted accounts/policy/settings controller; load generations prevent stale reads. Policy loads have an explicit retry; settings keep preview/save/applied revision. Foreign context clears previous library immediately, preserves read-only owner on refresh and focuses the destination after successful navigation. Roles now have Russian labels; backend values/access unchanged.

Initial management+account suite: 4 passed/1 failed in 34.91s; only failure assumed fresh settings started at revision1, while real isolated DB starts at0 and correct save produced1. Corrected transition assertion to baseline revision +1, preserving exact one successful write after a controlled503. Targeted management test then passed1 in9.62s. Actual owner-library reverse response, policy/role permissions, form preservation, manual retry count and unapplied revision state were asserted; no data or schema migration.
