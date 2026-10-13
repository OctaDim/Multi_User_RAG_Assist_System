# D1 parent review outcomes

Scope: substantive app paths in worker byte-freeze-v1, parent SMTP retry regression, unchanged HEAD 42a51a5 base. Human guides were excluded from reads. No transport, document, OCR, or final G3/G4 claim.

The ce-simplify-code reuse reviewer ran as /root/d1_reuse_review and completed. A second reviewer dispatch returned `agent thread limit reached`; the platform exposes no thread-release primitive. Parent performed the quality and efficiency passes inline with the full freshly read persona assets. All three outcomes were collected before production edits.

Reuse: applied one finding in Coordinator.guard. originating_session already checks verified/active/disabled under account/session share locks. The later guard retains the account epoch, owner, source, terminal and execution checks; finalizing bypass remains unchanged.

Quality: no further behavior-preserving change justified. Password KDF stays outside DB transaction/event loop; SMTP awaits outside transaction; external input validation, exact-origin CORS, textContent and visible labels retained. Role/no-op changes retain personal sessions and requests; access loss uses shared terminal transition.

Efficiency: no further behavior-preserving change justified. KDF serialization bounds the measured algorithm memory per process; owner mutation selects only affected requests/tabs/conversations. Repeated hashing during registration retry could be avoided only with more branch/race behavior; no speculative optimization applied. No configured separate linter/typechecker exists; compile and full regression are parent acceptance.

Separate behavioral fix: actual SMTP 550 during invited UI signup leaves a committed account and consumed invitation. The form previously retried the consumed invitation, returning registration_conflict. Parent-invitation-mail-retry-red-v1 captured the browser failure before production change. The form now clears the already-consumed invitation after mail_delivery_failed, while retaining the original password for resend. The new browser test follows actual local SMTP failure, resend, received link, confirmation and login as super_admin. No successful delivery is mocked.

Applied simplification counts: reuse 1, quality 0, efficiency 0. Low-value efficiency suggestion skipped 1. Final regression/commit pending at creation; a separate canonical report records their actual outcomes.
