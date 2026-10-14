# U8 serial continuation v3 — 2026-10-14

The plan remains active; U8 is NOT accepted. Continue the SAME user-authorized native Compound Engineering `ce-work` implementation. HEAD `122554c808d34ccb1ea679891efb58102b61a1a6`, branch `octadim/create-plan-1`. Parent owns final ALL application/harness gates, manual acceptance, fresh reviews, staging/commit/delivery. No worker index mutation or shipping. No new route/permission question.

## Latest user authority: RAG-64

Read `harness/project/decisions/2026-10-14-printed-and-handwritten-ocr-models-contract.md` FIRST for current OCR choices. It supersedes all-Qwen RAG-63; preserve both historical decisions.

- Printed image OCR: ORIGINAL PaddleOCR-VL 1.5 and original projector, genuine trained `Spotting:`/LOC output.
- Handwritten image OCR: Qwen3.5-2B Q4_K_M plus matching F16 projector, plain native transcription and honest source-region coordinates.
- Belarusian HANDWRITTEN errors are explicitly permitted. This does not waive printed BE or RU/EN/DE checks, masking/security, whole publication, originals/revision history, strict frozen RAG30, ALL regressions/harness tests.
- D-FINE and measured nonrecognizing connected-stroke detection are allowed. Mask handwritten pixels BEFORE ANY printed recognizer; forbidden handwriting is NEVER passed to Qwen.
- No further 4B/9B candidates or downloads. Original eight model artifacts/five native libraries remain unchanged.

The CURRENT production `backend/app/ocr.py` and `backend/config/ocr.toml` still implement the now-SUPERSEDED all-Qwen profile. They are NOT final/accepted. Next worker must implement RAG-64 promptly, remove unused printed-Qwen experimental code, and verify.

## Ownership and cleanup

Previous leaf `/root/u8_finish_acceptance` releases source/tests/fixtures/worker evidence ownership on return. ALL handles closed: 7200/15257/11398/50728/45977, all exit1 (failed/superseded focused runs). No live owned native job or API/browser job.

Actual host cleanup receipt `2026-10-14-worker-cleanup-observation-v20.json` checked native PIDs 111739,108420,108168,112763,109225,111490 absent, and no v18/v19 temp argv process. Stop attempt v19 found no pytest: it had already completed; NO SIGINT was sent. Exact current source freeze: `2026-10-14-worker-source-freeze-for-continuation-v20.json`, 91 paths, unchanged from v19 before/after. Plan SHA `a8aa22842c61f6e6a23dcf99f2314e8730458894cfa130eff120c38e9a72f435` unchanged.

Use existing frozen `uv`, cache `/tmp/rag-answer-lifecycle-uv-cache`, `backend/.venv`; no pip/apt/new framework/browser install. Serialize heavy native runs on 5783MiB RAM/10000MiB swap. Actual pgserver/browser tests need `require_escalated` automatic review; no rejection occurred.

## Durable assets and final environment

F16 projector copied/hash-verified to ignored durable local asset:

`backend/.venv/rag-native-models/ocr/mmproj-F16.gguf`, 668227264 bytes, SHA `7035e9cb8d7c6a9681d07eef9a364783e86ea4cd73faab2eabb4f43a101830c7`.

Source `/tmp/rag-u8-worker-qwen-ocr-projector-F16.gguf`; pinned URL/revision/provenance in `2026-10-14-fixed-qwen-ocr-durable-projector-v1.json`. Original selected Qwen weight unchanged SHA `aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223`. Original Paddle/model projector SHA in RAG-64.

Commands used:

```sh
UV_CACHE_DIR=/tmp/rag-answer-lifecycle-uv-cache \
RAG_MODEL_PATH=$PWD/backend/.venv/rag-native-models/Qwen3.5-2B-Q4_K_M.gguf \
RAG_E5_DIR=$PWD/backend/.venv/rag-native-models/e5 \
RAG_OCR_DIR=$PWD/backend/.venv/rag-native-models/ocr \
RAG_OCR_PROJECTOR_PATH=$PWD/backend/.venv/rag-native-models/ocr/mmproj-F16.gguf \
uv run --frozen --project backend pytest <owned focused nodes> -q -s --basetemp=/tmp/<NEW-name>
```

Adapt naming/config to fixed TWO roles, not configurable model alternatives. Both models require actual abort/close and memory/joint proof. Existing `test_actual_native_abort_and_close_wait_for_c_return` is baseline and must remain; `.model` historically represented printed Paddle. Preserve existing old test bodies. New profile test added at bottom of `test_document_ocr.py` currently expects all-Qwen, and MUST be corrected to RAG-64.

## Concrete completed changes/proofs this leaf

1. Separate lifecycle file/page failure dialog implemented in frontend app/index: file, stage, page, cause, whole unready exclusion, skip mode. Existing ready revision is distinguished on failed correction. Dialog DOM is erased on logout/library owner reset. No wider MVP export feature added.
2. Actual RED v15: missing report button, 1failed54.02s before production change. v16 boundary case passed; old Paddle twenty-page run safely interrupted after user changed contract. Immutable raw and interruption receipt retained; no whole20page claim from v16.
3. Actual model-selection RED v17: Paddle path differed from user-fixed2B,1failed7.89s. This is historical all-Qwen authority, now superseded RAG-64.
4. v18: 9passed4failed269.65s. Fixed2B/F16 actual native load and abort/close PASS. Report boundary failed because test asserted cleared DOM before asynchronous logout completed; fixed observation by awaiting authentication/empty report. Both native20page cases had15 real completions+page16fault but detector-only crops dropped printed100. Original RU had no detector box and blank OCR/no skip marker. EN/DE native anchors correct, BE raw retained.
5. v19: 11passed2failed489.70s. Report boundary including logout/new-owner cleanup PASS. Both20page cases genuinely processed15 native pages (100 present), failed ONLY page16 via failure hook, showed separate report, saved immutable originalSHA, no available revision,15 staging rows. They failed LATER because test tried to check failed-file checkbox: UI intentionally renders only READY sources. Fix test: actual issued-owner direct API failed-only document scope must reject409; UI zero-ready-selection refusal preserves draft/history; then select real healthy neighbor via UI. No fabricated UI checkbox.
6. v19 four-language word-anchor/mask test mechanically passed, but QUALITY IS NOT ACCEPTED: EN extra invented date, RU extra `ВЫБЕРИТЕ`, and BE background phrases. Raw results/copies retained. Strengthen EN/RU/DE source GT to reject extraneous text while keeping only permitted BE handwriting errors. Word matches alone are insufficient.

All completed v18/v19 sublogs, JSON/JSONL, screenshots and original PDFs copied immutably under NEW `2026-10-14-fixed-qwen-ocr-v18-*`/`v19-*` names. Main logs, negative/superseded receipts and earlier receipts never overwritten. New ordinary evidence v21+ or descriptive fresh names. Parent-* remains parent-owned.

## Measured detector/image findings and next code work

Current all-Qwen printed path MUST be removed and replaced with Paddle Spotting on hand-masked original pixels. Keep genuine LOC parser unchanged; do not invent Qwen LOC tokens.

Original RU is red cursive on gray paper. Actual D-FINE gives NO box on original or raster-page, top hand score0.157; autocontrast/threshold/green-channel three actual probes also no box. Do NOT report argmax as root cause. Original pixel-only adaptive Otsu/8-connected analysis finds ONE component `[16,15,458,151]`,7690 pixels, aspect3.25. Current `ink_mask` and `connected_handwriting` derive this from pixels with no text/GT, but fallback currently runs ONLY when D-FINE found no hands — security gap.

Parent requested concrete fix: compute components on ORIGINAL image; union missed cursive components even when another hand region is already detected. Expand known D-FINE boxes to whole intersecting connected ink components. v19 actual residual hand fragment at `[909,356,934,381]` lay just past English hand box end905 and was wrongly fed to printed recognizer. Add SAME ORIGINAL EN+RU mixed-page regression proving detected English plus missed RU are both masked before printed recognition. Keep confidence/source labels honest, no fabricated confidence for connected ink.

Foreground threshold MUST be computed from ORIGINAL image before masking and reused. Recomputing Otsu after erasing hands shifts threshold upward into gray paper texture, producing noise crops and hallucinated date/words. Current source has NOT yet applied this correction. Parent explicitly retains this fix for classification/noise safety under hybrid OCR. Remove superseded `printed_ink_regions`/printed-Qwen calls rather than leave abandoned production paths. A few-pixel JPEG noise suppression was considered but NOT implemented; with Paddle printed path, calibrate whether still needed instead of adding unused logic.

Actual standalone env bug corrected: lazy `os.environ.get('RAG_OCR_MODEL_PATH') or os.environ['RAG_MODEL_PATH']` avoids eagerly indexing missing generator env with an explicit OCR path. Carry correct lazy selection into fixed handwritten role as needed.

## Remaining U8 work inherited from parent

- Hybrid OCR adoption/proofs above, exact original non-BE handwriting, permitted BE raw reporting, true printed four-language PDF/DOCX and forbidden pixel masks; originals, coordinates, whole publication and revision history.
- Revised terminal twoAPI/observer proxy/fresh explicit question/checkpoint exclusion test and settings restart adapted fixture still UNRUN. Current authored `test_terminal_lifecycle.py` has actual next UI prompt and excludes stopped/failed partial while retaining completed history; no reason to redo old U1–U7 units.
- AE9 genuine account revoke while queued/streaming; AE28 actual new limit admission at6 then5; real native output isolation; oversize/tokenizer refusal + draft retention and historical fragment clarity.
- Exact executable coverage v2 remains historical/stale: G1 jointv6 actually passed; supplement NEW truthful v3 after proofs, don't rewrite completed earlier table/receipts. Four-language test now BE-only conditional references historical RAG-63; update reference to latest RAG-64 without changing originals/GT or frozen30 controls.
- Parent owns final headed fresh-DB manual, ALL application baseline201+new and all168 harness without filters/skips, independent semantic/citation audit of any fresh30 answers, fresh CE reviews, final ce-code-review receipt and exact-owned-path Git commit.

Do not claim U8 accepted from focused proof. Frozen30 questions/facts/corpus/hash never change. Goal remains active; no worker goal completion or final delivery claim.
