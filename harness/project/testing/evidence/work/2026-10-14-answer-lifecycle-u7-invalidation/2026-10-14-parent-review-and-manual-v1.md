# U7 parent review and separate manual browser walkthrough

Created 2026-10-14. Ordinary application evidence. This supplements the completed
worker result without changing that report or any original logs.
The complete U7 application/harness gate passed. Canonical commit is pending
the final explicit-file-list and staged-byte checks at this record's closure.

## Review and changes

The parent inspected the actual U7 tree and preserved the immutable plan body.
The HEAD baseline contains 118 named test functions across 23 Python files;
all 118 remain present. Parametrization produced 158 cases in the accepted U6
gate. Existing HTTP assertions remain, now exercised through the real H11 client.

Three fresh read-only CE simplification reviewers completed:
`/root/u7_reuse_review`, `/root/u7_quality_review`,
`/root/u7_efficiency_review`. The efficiency reviewer was initially queued after
an actual thread-capacity rejection and successfully dispatched after capacity
became available; no cleanup operation or retired-worker retasking was invented.

- Reuse: no findings; existing projection, source-flag and vocabulary helpers
  already cover the relevant repeated work.
- Quality: applied both findings. Removed the unused LiveClient constructor
  argument together with its only caller; replaced the nested forbidden-byte
  conditional in the backpressure test with an explicit equivalent mapping.
- Efficiency: applied one finding. The preparing guard no longer executes the
  stale-revision SELECT whose result it previously ignored. Non-preparation
  stale-source validation and preparation's source-deletion check remain.
- Efficiency: skipped the header-projection separation. Authorization and
  projection currently share endpoint helpers with differing refusal conditions
  and lock ordering. The proposed restructuring did not establish equivalence
  for every such condition; the centralized checks remain on both handoffs.
  Repeated header/body projections remain a known potential optimization.

Applied counts: reuse 0, quality 2, efficiency 1; skipped 1. No safety check was
removed. Production handoff/session/source/tab/role validation is unchanged by
these simplifications. Their verification is the full application/harness gate.
No standalone linter or typechecker is configured. Python compileall, Node
syntax checks for all five JS modules and source-only git diff --check passed.

## Separate manual walkthrough

The parent started an independent headed Chromium 131 under Xvfb, a newly
migrated PostgreSQL database with zero accounts/documents, actual SMTP/mailbox,
separate static frontend/API, document worker and production native supervisor.
This was an agent-operated interactive walkthrough, not human attestation and
not a replay of the three worker browser tests. The exact launcher, transcript,
original scanned PDF, JSON observation and screenshots use the reserved
`parent-manual-invalidation-*` filenames in this directory.

1. An operator invitation was issued through the real CLI, then redeemed by
   browser registration, SMTP verification and login. The owner separately
   registered, verified email and logged in through the UI; no SQL principal
   seeding or role promotion was performed.
2. The owner uploaded a TXT file through the UI; the real worker/E5 publisher
   made it ready. The owner sent a question while the actual native process was
   paused before tokens. The operator blocked the owner through the account
   form. After resume/reload, protected access was closed.
3. The operator restored the owner, who logged in anew. The old question stayed
   interrupted with no empty assistant and no automatic restart.
4. A new UI-submitted question reached a committed native prefix. A read-only
   DB observer froze the actual process with SIGSTOP at that boundary. The
   operator soft-deleted the owner through the UI; SIGCONT restored execution.
   Access closed. After account restoration and new login, the saved prefix
   remained interrupted and the two original questions did not restart.
5. A newly created scanned PDF was uploaded through the UI and recognized by
   the actual OCR model, indexed by E5, and displayed alongside its original PNG.
   The OCR text contained the annual budget of 100 euros. The owner selected
   only that PDF and obtained a completed Qwen answer and its exact citation.
6. The owner corrected the OCR through the document form from 100 to 10.
   Complete publication updated the history's corrected/excluded labels while
   preserving the original 100 quotation. A subsequent real native answer and
   its citation used 10. Read-only inspection of the actual saved checkpoint
   showed a prompt containing 10 euros, no 100 euros, and an empty eligible
   history. The original PDF's SHA256 still matched the upload bytes.
7. The owner deleted the PDF through the UI. Completed historical answers and
   original quotations remained visible with the original filename and current
   deleted/excluded labels. The history still had exactly four questions, with
   states interrupted, interrupted, completed, completed; no automatic question
   appeared.
8. Desktop 1280px and mobile 375px screenshots were captured and visually
   inspected, including deletion views. No horizontal overflow or pageerror was
   observed. Logout returned to authentication. All owned native/service/browser,
   SMTP and PostgreSQL resources were closed/reaped; the terminal ended with
   exit 0 and explicit completion assertions.

Controlled native pauses synchronize mutations with real computation; neither
model output, OCR result, upload publication nor successful response was mocked.
The generated printed scan is a bounded test document, not an external held-out
quality corpus or genuine handwriting sample.

Raw transcript preserves driver mistakes: the first refresh action used an
incorrect button label and timed out, then the existing DOM button was used;
bare REPL screenshot calls echoed PNG bytes and caused a stdout BlockingIOError.
The actual files were already saved, later screenshots suppressed return values,
and the subsequent assertions/visual inspections completed. These are not
product failures or acceptance successes attributed to failed commands.

The real model still emitted the fact-free phrase "Supported claim" from the
system citation example. The bounded answers supplied the correct budgets and
quotes, but this is not a held-out quality acceptance certificate. U8's full
AE matrix, joint load, 30/30 quality and known handwriting-crop miss remain open.

## Complete regression gate

The parent froze the 21 owned application paths, manifests and immutable plan
before the complete test runs; hashes are in `parent-source-before-all-v1.json`.
No application source edit is permitted during that run.

- All active harness tests: **168 passed, 25.46s**, no skip/deselection/ignore;
  original log `parent-all-harness-v1.log`, process exit 0.
- All previous and new application tests, including runtime/browser/integration:
  **201 passed, 1003.78s**, pinned actual models, no skip/deselection/ignore.
  Original log `parent-all-application-v1.log`; session 73062 completed exit 0.

All 24 frozen source/manifest/plan hashes remained identical throughout that
gate; all 118 prior named test functions remain. Eighty-one direct physical
child process logs were preserved byte-for-byte (2481375 bytes), with source
paths/hashes in `2026-10-14-parent-all-child-logs-v1.json`. Pytest current aliases
and Chromium profile logs were not followed. U7 implementation, focused proofs,
review, separate manual walk and full regression acceptance are complete.
The full U1–U8 objective remains active; no U8 quality/load/G4 completion is claimed.
