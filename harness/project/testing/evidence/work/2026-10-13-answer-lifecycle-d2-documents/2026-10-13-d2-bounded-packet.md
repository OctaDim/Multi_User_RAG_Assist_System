# D2: real document publisher prerequisite

Base a7a7047dd23006dc190af108a7763af412d40759. Native CE route remains selected. Parent implements inline: fresh reviewer dispatch already hit the platform's agent thread limit; there is no supported release primitive. No engine/route/model switch or new user decision is inferred.

## Goal capsule


- **Objective:** Владелец личной библиотеки получает полезные фрагменты до готовности ответа, видит его основания и сохраняет понятную историю при отмене или обрыве соединения.
- **Product authority:** Подтверждённое пользователем 2026-10-13 сводное описание текущего пути и действующий реестр `harness/project/decisions/2026-10-08-rag-architecture-decisions.md`, включая последнюю редакцию RAG-43 и последующие уточнения RAG-44–RAG-62.
- **Scope:** Путь одного вопроса от неотправленного черновика и приёма до ответа, ошибки или отмены, включая ранние фрагменты, ожидание, источники и навигацию между беседами и вкладками.
- **Means:** Общий серверный запрос, сохранённая выдача и независимые contexts выбранной локальной модели — KTD1–KTD4.
- **Execution boundary:** Реализация и её приёмка выполняются по U1–U8 отдельным поручением; отрицательные proof gates останавливают соответствующую зависимую работу.
- **Open blockers:** Вопросы Q01–Q13 из полной ревизии от 2026-10-13 согласованы в RAG-50–RAG-62; открытых продуктовых вопросов этого списка нет. Технические допущения и проверки перечислены ниже и в `harness/project/docs/ideation/2026-10-13-rag-brainstorm-question-audit.md`; условный внешний маршрут не активирован.


## Authority and bounded scope

User requires real test accounts/documents through actual E2E and manual browser UI. G4 requires a genuine original upload, processing worker, whole revision publication, actual E5 vectors, owner original/page view, voluntary correction/new whole index and delete using existing source fence. Existing fixture publishers cannot close G4. This is the minimal necessary dependency of the accepted lifecycle, not all other MVP product areas.

Touch app/documents.py, document_worker.py, api/documents.py, controlled migration006, config/document defaults, account registration policy initialization, main router/CORS, dependency manifest/lock only for actual required Pillow/pdfium. Extend existing frontend with document upload/status/view/correction/delete/skip choice and personal permissions/quotas administrative controls needed by these paths. Tests must cover actual PostgreSQL/storage and real API/UI-created inputs, not seed ready revisions. Original storage is an operator-configured filesystem location; client filenames never determine paths. Actual files/pages are hashed/retained and ready only after complete processing. Existing migrations001–005 remain immutable.

RAG12/13/21/23/35/51/52/54/55/59/60/61 apply: five initial permissions enabled; owner cannot set them; admin changes personal permissions/quotas but cannot read foreign content; paid ignored; five numerical limits come from config/new account defaults and are individually checked atomically against concurrent reservations. Reduced quotas do not cancel admitted operations, which retain snapshots. Permission/access loss prevents new forbidden actions and stops affected jobs at safe boundaries. Existing documents/history retained. Advanced global default comparison/picking, batch recommendation and export report design remain separate declared plan areas; do not expand them merely because their contracts are linked.

Upload one or more originals through ordinary browser/API. Validated UTF-8 TXT/Markdown, DOCX zip/XML with no external entities or zip path extraction, real PDF page rendering/OCR. Whole file success publishes all pages/chunks together; any technical page failure publishes none. Real E5Embedder reused. Original and page text linked, suspicious text editable voluntarily; correction creates immutable new revision and uses change_source, preserving old citations/context exclusion. Delete uses change_source, never unrelated file removal.

PDF with handwriting disallowed requires explicit owner cancel/print-only choice before recognition/publication. Detection precedes OCR; forbidden handwriting pixels never enter OCR. Retain ALL non-handwritten pixels, including regions the detector calls formula/unknown; page classifier failed region proof and is rejected. Spatial skip blocks/reasons/limitations tied to actual page coordinates; skip chunks excluded from retrieval. No automatic OCR when permission is restored. Use proven D-FINE ONNX and PaddleOCR GGUF CPU candidates only after exact artifact/config checks; all other-language/held-out accuracy and joint load remain actual U8 gates, not claims from one constructed PDF.

## Evidence already obtained

Candidate proof directory d2-ocr-proof contains exact revisions/SHA/native logs. Printed four-language lines matched; genuine handwritten title/author crop matched; a constructed real-raster mixed PDF retained all five printed lines after automatic handwriting masking and omitted the title/author. Both ended at EOS. Page classifier failed crops and remains rejected. The dedicated detector classifies handwriting before OCR but mislabels printed lines as formula; only handwriting masks may filter recognition input. Entire original immutable. Native probe reaped. These are technical candidate probes, not production G4, multilingual handwriting accuracy or 30/30 quality.

## Incremental delivery and verification

First establish real non-PDF upload/storage/text extraction/E5 whole publication + actual UI with RED before production writes. Then integrate actual PDF rendering/detection/native OCR, skip choice and correction. Shared API/policy/job/storage contracts must be carried through every caller/config/test before acceptance. No synthetic handwriting font masquerades as a real handwritten input. Failed logs stay immutable. All deps managed with uv and exact versions; no pip/apt/second ML framework.

Every substantial integration and EVERY U runs ALL accumulated application/runtime/browser/integration regressions and ALL168 active harness cases before advancement; no skips/deselections. Parent owns canonical commits and actual independent browser walkthroughs. Physical transport/replay revocation remains U7; UI/data checks alone do not upgrade it. Final real-source RAG/AE/full joint gates remain U8.

## Shared design pins

KTD1 transactional request/source publication, KTD2 durable events, KTD3 one existing generation coordinator, KTD6 immutable source revision/provenance, KTD7 guarded context and KTD8 common terminal/source fence are retained. No publishing partial revision, no graph resume/auto retry, no billing/fallback/SSO, no silently reduced cap/quality requirement. HTTP/socket waits/native work never hold DB barrier locks. Original storage must never be served directly by static frontend. Security, input validation, accessibility and data-loss protection are not simplification targets.

## Done

Real browser-created account can upload/observe whole ready sources, view immutable originals and correction history, correct/delete, obtain valid search vectors and obey permissions/limits/skip choice. Focused RED/GREEN, complete regression evidence, application ownership/review and canonical commit recorded. Only then claim D2 implementation; G4/lifecycle acceptance remains conditional on actual integrated scenarios.
