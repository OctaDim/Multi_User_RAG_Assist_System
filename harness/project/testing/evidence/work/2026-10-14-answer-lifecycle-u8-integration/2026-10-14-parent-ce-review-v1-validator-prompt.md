You are the independent validation gate for the code-review findings below. Evaluate every finding separately under fresh inspection and under the shared protected-subject policy below. Outside a protected subject, false positives are common; reject a finding when the cited code does not prove it, it predates and is unaffected by this diff, surrounding code handles it, or it is only an unsupported preference. Inside a protected subject, a rejection requires one of the evidence forms the policy names.

Do not let one finding's outcome influence another. Do not invent new findings.

<findings-to-validate>
[
  {
    "#": 1,
    "autofix_class": "gated_auto",
    "confidence": 100,
    "evidence": [
      "backend/app/ocr.py:93 --     return (gray<245) & (gray<=int(variance.argmax()))",
      "backend/app/ocr.py:88 --     histogram=np.bincount(gray[gray<245].ravel(),minlength=256).astype(float)",
      "backend/app/ocr.py:92 --     variance=(moment[-1]*weight-moment*weight[-1])**2/np.maximum(weight*(weight[-1]-weight),1)",
      "For white plus gray-128 input, the sole histogram bin is 128: below it weight=moment=0, and at/above it weight=H and moment=128H. Every numerator is zero, argmax is 0, and the returned mask contains no pixels.",
      "backend/app/ocr.py:281 --                 'handwriting':handwriting,'skips':skips,'mode':mode,'printed_ink':bool(printed_foreground.any())}",
      "backend/app/ocr.py:284 --         lines=self.recognize(prepared['image'],cancelled) if prepared['printed_ink'] else []",
      "backend/app/document_worker.py:226-237 -- DOCX image bytes are converted to RGB, passed to prepare_image(...,'complete'), then recognized and staged; lines 242-245 publish a successful revision without requiring nonempty page text."
    ],
    "file": "backend/app/ocr.py",
    "first_evidence": "backend/app/ocr.py:93 --     return (gray<245) & (gray<=int(variance.argmax()))",
    "independent_reviewers": [
      "correctness"
    ],
    "line": 93,
    "owner": "downstream-resolver",
    "pre_existing": false,
    "requires_verification": true,
    "reviewers": [
      "correctness"
    ],
    "severity": "P2",
    "suggested_fix": "Before calculating the variance, detect a histogram with exactly one occupied bin and return the gray<245 foreground mask (equivalently threshold at that occupied bin). Keep the existing all-white case. Verify a white-background embedded DOCX PNG whose text pixels all have grayscale value 128 reaches recognition and publishes its text rather than an empty page.",
    "title": "Single-color gray ink is silently discarded",
    "why_it_matters": "A supported DOCX image containing crisp gray or colored text on white can publish with an empty OCR page even though its text is visible. When every foreground pixel has the same nonzero grayscale value, the background-excluding histogram has one occupied bin, every variance is zero, and argmax selects threshold zero; printed_ink therefore becomes false and the printed recognizer is skipped. Handling the singleton histogram explicitly preserves these pixels while retaining the existing threshold behavior for ordinary multilevel scans."
  },
  {
    "#": 2,
    "autofix_class": "manual",
    "confidence": 100,
    "evidence": [
      "backend/tests/integration/test_multilingual_documents.py:228 -- row['actual_words']=re.findall(r'\\w+',row['evaluated_raw_handwriting'].casefold())",
      "backend/tests/integration/test_multilingual_documents.py:230-233 -- exact=row['actual_words']==row['expected_legible_source']; assert exact or exception=='current_Qwen_BE_handwriting',records; row.update({'identity':identity,'acceptance':'exact' if exact else 'user_permitted_current_model_difference', 'exception':exception,'contract':CONTRACT if exception else None})",
      "backend/tests/integration/test_multilingual_documents.py:153 -- ('de',raster_pdf(FIXTURES/'handwritten-de-row5.jpg'),['die','seerose','blüht','auf','dem','teich']),",
      "backend/tests/fixtures/answer_lifecycle/handwriting-primary-provenance-v1.json:15 -- \"text\": \"Die Seerose blüht auf dem Teich.\"",
      "Constructed sequence: the actual model returns 'die seerose blüht auf dem teich?'; casefold plus \\w+ returns ['die','seerose','blüht','auf','dem','teich']; the German be_exception returns None, but exact is True, so the acceptance assertion passes and the evidence record says exact. This is a mechanical guard-fidelity failure, not a claim that the current native run produced this text.",
      "backend/tests/integration/test_actual_printed_documents.py:66 -- assert re.findall(r'\\w+',text.casefold())==expected_words,{'name':name,'recognized':page['text'],'expected':gt}",
      "harness/project/decisions/2026-10-14-ocr-word-types-and-model-specific-exceptions.md:7 -- **По умолчанию ошибки запрещены. Допуск определяется фактическим типом каждого слова и конкретной моделью OCR.**"
    ],
    "file": "backend/tests/integration/test_multilingual_documents.py",
    "first_evidence": "backend/tests/integration/test_multilingual_documents.py:228 -- row['actual_words']=re.findall(r'\\w+',row['evaluated_raw_handwriting'].casefold())",
    "independent_reviewers": [
      "adversarial"
    ],
    "line": 228,
    "owner": "downstream-resolver",
    "pre_existing": false,
    "requires_verification": true,
    "reviewers": [
      "adversarial"
    ],
    "severity": "P2",
    "suggested_fix": "Replace the casefold()/\\w+ equality used for strict OCR acceptance with case- and punctuation-preserving source tokens or complete independently recorded source strings, allowing only layout whitespace differences explicitly handled by the existing page composition. Use the committed German ground_truth.text and faithful independent EN/RU/printed ground truths; preserve the existing per-word Paddle Belarusian glyph exception and current Qwen Belarusian handwriting exception. Add a small matcher regression proving that a case change and a period-to-question-mark change fail strict acceptance, then rerun the actual OCR integration gates without changing the originals or old raw records.",
    "title": "OCR acceptance reports forbidden transcription differences as exact",
    "why_it_matters": "The new OCR acceptance mechanism can pass and label a German, English or Russian transcription as exact after the model changes capitalization or punctuation, although RAG-67 grants no such exception. For the committed German ground truth 'Die Seerose blüht auf dem Teich.', the different output 'die seerose blüht auf dem teich?' becomes the same case-folded word array, reaches exact=True and requires no user permission. The printed PDF/DOCX gate uses the same lossy comparison, so a wrong punctuation mark can also pass that gate. Comparing independently transcribed tokens while retaining case and punctuation prevents these differences from silently receiving an undeclared allowance."
  },
  {
    "#": 3,
    "autofix_class": "gated_auto",
    "confidence": 75,
    "evidence": [
      "backend/app/ocr.py:291 --             lines.sort(key=lambda line:(line['bbox'][1],line['bbox'][0]))",
      "backend/app/ocr.py:285-291 -- The sort is inside mode=='complete' but outside the handwriting loop, so it executes for complete pages with an empty handwriting list.",
      "backend/app/ocr.py:58 --         lines.append({'kind':'printed','text':text,'bbox':bbox,'polygon':polygon})",
      "backend/app/ocr.py:67 --     # Keep the recognizer's printed reading order and insert omissions in their column.",
      "backend/app/ocr.py:76-81 -- compose_page builds the stored text and span offsets in the incoming blocks' order.",
      "backend/app/document_worker.py:211-216,227-237 -- Actual PDF and embedded DOCX OCR results flow from finish_page into stage_page and document publication; embedded DOCX images explicitly use complete mode."
    ],
    "file": "backend/app/ocr.py",
    "first_evidence": "backend/app/ocr.py:291 --             lines.sort(key=lambda line:(line['bbox'][1],line['bbox'][0]))",
    "independent_reviewers": [
      "correctness"
    ],
    "line": 291,
    "owner": "downstream-resolver",
    "pre_existing": false,
    "requires_verification": true,
    "reviewers": [
      "correctness"
    ],
    "severity": "P2",
    "suggested_fix": "Remove the unconditional global y/x sort from finish_page. Preserve the printed lines' returned sequence; insert transcribed handwriting into the corresponding overlapping column using the geometry-based insertion already used by compose_page for skip blocks. At minimum, purely printed complete pages must retain their recognizer order. Verify both a two-column printed page and a mixed page whose handwritten insertion must not reorder the remaining printed lines.",
    "title": "Complete OCR interleaves printed columns",
    "why_it_matters": "A two-column printed page processed in complete mode loses Paddle's reading order, even when there is no handwriting. For returned lines ordered left-top, left-bottom, right-top, right-bottom, the new y/x sort publishes left-top, right-top, left-bottom, right-bottom, mixing the text of separate columns in the document view and source spans. Retaining the recognizer's printed sequence and inserting handwriting within its column avoids changing correct printed page order."
  },
  {
    "#": 4,
    "autofix_class": "gated_auto",
    "confidence": 75,
    "evidence": [
      "frontend/src/app.js:309 -- const value = await api('/settings'); | frontend/src/app.js:311 -- form.replaceChildren(); | frontend/src/app.js:351 -- await showSettings(); | frontend/src/app.js:353 -- refresh.addEventListener('click', () => perform(showSettings,refresh));",
      "frontend/src/app.js:45-57: perform disables only the supplied control; refresh and save remain independently usable, allowing their GET/PATCH operations to overlap.",
      "frontend/src/api.js:14 -- if (token() !== credential) throw new Error('session_changed'); This protects account changes but does not order same-session settings reads.",
      "backend/app/settings.py:27-31: GET captures current settings in a transaction; no frontend ordering constraint exists on delivery of that captured response. Lines 40-43 commit a newer revision and audit the PATCH.",
      "frontend/src/app.js:336-339 builds the preview from every mutable field; line 349 PATCHes the resulting full proposal.",
      "backend/tests/integration/test_answer_lifecycle.py:95-124 and 238-252 exercise sequential preview/save/refresh rather than delaying an older refresh response past a completed save."
    ],
    "file": "frontend/src/app.js",
    "first_evidence": "frontend/src/app.js:309 -- const value = await api('/settings'); | frontend/src/app.js:311 -- form.replaceChildren(); | frontend/src/app.js:351 -- await showSettings(); | frontend/src/app.js:353 -- refresh.addEventListener('click', () => perform(showSettings,refresh));",
    "independent_reviewers": [
      "julik-frontend-races"
    ],
    "line": 309,
    "owner": "downstream-resolver",
    "pre_existing": false,
    "requires_verification": true,
    "reviewers": [
      "julik-frontend-races"
    ],
    "severity": "P2",
    "suggested_fix": "Give settings rendering a monotonically increasing request generation: capture it before each GET and discard the response unless it remains current. Invalidate outstanding reads when a PATCH starts, and keep refresh/save serialized while that PATCH and its follow-up read finish. Add a browser scenario that holds a revision-0 refresh response, saves and renders revision 1, then releases the older response and verifies the form still shows revision 1 and its limits. This needs only local state, no new dependency.",
    "title": "Fence overlapping settings reads against completed saves",
    "why_it_matters": "The administrator can see the old global limits and old saved revision after successfully saving new values. Click refresh while a preview is ready, then save: the refresh GET can capture revision 0, the PATCH and its follow-up GET can render revision 1, and the delayed first GET then unconditionally replaces the form with revision 0. A subsequent preview submits both mutable values from that stale form, potentially restoring an old limit when the administrator only intended to change the other field."
  }
]
</findings-to-validate>

<diff>
/tmp/compound-engineering-1000/ce-code-review/20261014-180301-33f78c23/diff.patch
</diff>

<scope-context>
{"mode": "standalone", "base": "122554c808d34ccb1ea679891efb58102b61a1a6", "diff_a": "122554c808d34ccb1ea679891efb58102b61a1a6", "diff_b": null, "pr": {"number": null, "url": null, "title": null, "body": null, "base_ref_name": null, "head_ref_oid": null, "head_ref": null, "base_ref": null, "has_prior_comments": false}, "branch": "octadim/create-plan-1", "head_sha": "122554c808d34ccb1ea679891efb58102b61a1a6", "files": "/tmp/compound-engineering-1000/ce-code-review/20261014-180301-33f78c23/files.txt", "diff": "/tmp/compound-engineering-1000/ce-code-review/20261014-180301-33f78c23/diff.patch", "tree_is_reviewed_head": true, "untracked_excluded": ["harness/project/handoffs/", "harness/project/testing/evidence/work/2026-10-14-answer-lifecycle-u8-integration/"]}
</scope-context>

<protected-subject-policy>
Return status "confirmed", "rejected", or "unresolved". Never use lack of disproof as evidence of confirmation.

Set protected_subject to the best-fitting key below, or JSON null when none applies:
- memory-safety: allocation sizes, buffer lengths, index bounds, use-after-free, invalid memory access, or null dereferences.
- concurrency: locks, atomics, data races, ordering, or synchronization whose failure can affect observable behavior.
- data-loss: destructive writes, deletes, truncation, overwrite-in-place, or irreversible migrations and backfills.
- authorization-authentication: identity, permissions, ownership, session/token handling, or privilege boundaries.
- injection: attacker-influenced or untrusted data that can alter SQL, commands, templates, paths, or markup across a trust boundary, including stored input. Text assembly alone is not proof.
- public-contract: an evidenced compatibility concern involving an externally consumed response field, status code, error path, default, message, or published signature. An internal export or intentional contract change alone is not a defect.
- secrets-exposure: hardcoded credentials, API keys, tokens, or private keys in source or configuration; credentials, session tokens, or personal data written to logs, error messages, URLs, or responses; secrets committed to a repository or shipped in a built artifact.
- cryptography: weak or broken algorithms and modes, a fast general-purpose hash used for passwords, static or predictable keys, salts, or IVs, disabled certificate or signature verification, insufficient randomness, or a misused primitive whose failure breaks a security guarantee.

For every subject, confirm only when inspected evidence establishes the issue, the diff introduces or newly exposes it, and surrounding code or applicable runtime guarantees do not prevent it.

A finding that is real in the code may still describe a state that never occurs. For every finding, name the precondition the defect needs (the input, data shape, or ordering) and say what would show it occurs or is reachable: a test, a query against available data, a caller that produces it. When that evidence is in reach with the budget, obtain it; when it is not, confirm on the code alone and state in `reason` that incidence was not measured. Unmeasured incidence does not lower confidence or block confirmation; it is what the reader needs to weigh the severity.

Treat a finding as protected when the actual failure it alleges falls within a subject above. Read its category, title, and body together; keywords only prompt inspection and never establish protection. A naming preference about a token helper is not a token-handling defect. Your classification cannot remove protection established by the claim; the consumer applies this test independently.

On a protected subject, reject only by citing specific evidence that refutes the claim or establishes that it is unrelated pre-existing behavior: quote the file and line number that refutes it, name the version-specific or configuration-specific documentation and the version in force, give short-hash provenance, or cite a discriminating test result. Test evidence must identify the reviewed revision, engine/runtime version, configuration, exercised trigger, assertion, and observed result, and explain why it disproves the exact claim. A general passing suite or a test that did not exercise the alleged trigger is not disproof. An assumed framework guarantee is not evidence. Without one of these evidence forms, return status "unresolved", not "rejected". Inspect existing test evidence or use a read-only reproduction within your authority; do not mutate files or application state to obtain it.

If a protected claim remains uncertain, return status "unresolved" and state the missing evidence. Low confidence alone does not justify rejecting or confirming it.

Outside protected subjects, keep the ordinary conservative evidence bar: after inspection, reject an unsupported claim and explain why. Missing required inspection is different from inspected-but-unsupported evidence. If the cited file or required context cannot be accessed, return status "unresolved" for any subject, state the access limit, and do not guess.

Classify the claim itself, not its title. Never raise severity or confidence to preserve it. Do not invent findings or propose that uncertainty is a confirmed defect.
</protected-subject-policy>

For local-aligned scope, inspect the cited files, callers, guards, project contracts, and targeted history with read-only tools. For pr-remote or branch-remote scope, use the provided diff and reviewed head ref, never the unrelated workspace copy.

Budget: the batch has 15 minutes of wall clock and about five tool calls per finding. Inspect findings in the order given. When the budget runs out, stop inspecting and give every remaining finding `"status": "unresolved"` with the reason `budget exhausted, uninspected`; never guess a verdict you did not inspect.

Write the JSON object below to `/tmp/compound-engineering-1000/ce-code-review/20261014-180301-33f78c23/validator-verdicts.json` before you return, then return the same object:
{
  "verdicts": [
    {
      "#": <input stable number>,
      "status": "confirmed" | "rejected" | "unresolved",
      "protected_subject": "<one of the eight policy keys>" | null,
      "reason": "<one sentence grounded in inspected evidence, or naming the evidence you could not obtain>"
    }
  ]
}

Each entry carries exactly those four fields. Return one verdict for every input # exactly once; unknown, duplicate, or missing numbers and invalid status or subject values are malformed output. Do not emit the legacy `validated` boolean. No prose outside JSON. Writing the verdicts file above is the one permitted write; do not edit project files, commit, push, or otherwise mutate the checkout.

Parent native ALL frozen and running. No pytest/native/browser/server jobs allowed; read-only inspection or pure isolated arithmetic only. Source changes forbidden. Fresh startup follows user AGENTS and exact rule order except README.human.md. Latest RAG67 authoritative; read sanitized plan if needed.
