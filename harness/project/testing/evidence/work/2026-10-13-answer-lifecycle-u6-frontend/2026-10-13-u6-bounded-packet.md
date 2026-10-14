# U6 bounded inline packet

Base c30e46f26bf2bd0fafad1a907d75f44728c49c5a. Native CE route remains settled; fresh-worker dispatch reached the platform thread limit with no release primitive. U6 is implemented inline. U7 is queued: actual callback/SSE/API/serialization/CORS and source contracts overlap with U6 and need integration review before a concurrent write wave. U1–U5, D1 and D2 foundation are committed; final G4 handwriting quality remains open. Independent U6 uses genuine UI/SMTP-created accounts and real TXT/MD publisher paths. Never substitute seeded ready sources for final real-dependency proof.

Goal capsule: implement the accepted owner question-to-answer lifecycle, early fragments, comprehensible saved history, independent tab/conversation drafts and compact actual-source passport. The original plan/decisions are authority; main plan body is not a progress log. R3/R6/R7/R9/R10/R23–R27/R30/R34, A1/A2 and F1/F2/F6/F7 govern this unit. Keep labeled session-settled decisions, including early fragments, one busy request per shared conversation, stream/prefix semantics, independent drafts, refresh retention and closed-tab discard.

Required reach: existing frontend index/app/api/styles/auth; new frontend conversations/drafts modules; existing answers/API for real new-conversation creation and actual snapshots; main CORS for confirmed heartbeat/event transport; rag prompt/citation projection if required by R6; browser test_answer_lifecycle and G2 production-browser proof. No new framework/build system/SSO/retry broker. Draft and tab state follow the proven U1 navigation/storage mechanism and are owner scoped; signout/account change clear credentials and old drafts/recovery data. One SSE connection per tab, unaffected by in-app conversation navigation. Restore only an actually connected originating tab; never impersonate it from a duplicate/new tab.

Evidence: inspect existing browser account/document/draft tests, server admission/events and actual generation payloads. First add the smallest real-browser failing slice for normal new conversation + independent A/B/tab draft + refresh/no submission + no-ready-source refusal. Then build that behavior. Add subsequent actual generation/passport, lost ACK revision, busy/background/stop, keyboard/mobile/HTML and restore scenarios incrementally. Capture RED before writes and GREEN from actual UI/API/SMTP/database/workers. Test injection may hold transport in tests, but cannot supply successful model/OCR outputs or seed final ready sources.

After completing U6, run ALL accumulated backend tests (unit/runtime/browser/integration) with the real pinned generation/E5/OCR assets and ALL168 active harness tests, no skips/deselections. Preserve full logs and physical process cleanup. Parent owns review, actual manual browser walkthrough, explicit staging/canonical commit. No advance to U7 on a failing final gate. U7 HTTP handoff and U8 real joint/quality acceptance remain later required work.

Definition of done: all U6 scenarios below have executable observed proof, integrated callers/config/UI complete, all prior regressions and harness pass, owned result reviewed and canonically committed. No claim of whole lifecycle/G4 completion until its remaining gates actually pass.

## Original U6 unit

**Goal:** Дать владельцу общий путь ответа с независимыми черновиками и паспортом.

**Requirements:** R3, R6, R7, R9, R10, R23–R27, R30, R34; A1/A2, F1/F2/F6/F7.

**Dependencies:** U1/G2, U3, U5; реальный auth transport G3/G5 нужен для приёмки.

**Files:** Создать `frontend/index.html`, `frontend/src/app.js`, `frontend/src/api.js`, `frontend/src/conversations.js`, `frontend/src/drafts.js`, `frontend/src/styles.css`, `backend/tests/browser/test_answer_lifecycle.py`; дополнить browser proof U1.

**Approach:**

1. Применить state reducer и tab/draft lifetime KTD10; не создавать соединение заново при переключении беседы.
2. Показывать early fragments отдельно от ответа, состояние ожидания/ошибки/прерывания и доступную кнопку stop.
3. Компактный раскрываемый passport строить из KTD6; original citations не переписывать при обновлении отметок источников.
4. Подтверждённый acceptance очищает только отправленную draft revision; отказ и потеря ACK сохраняют редактирование.
5. Использовать семантические элементы, keyboard navigation и сдержанное live-announcement изменений, без озвучивания каждого токена.
6. Публичный API origin задаётся в bootstrap `frontend/index.html`; статические файлы запускаются отдельно от backend, а credentials/CORS проверяются с G3/G5.

**Patterns to follow:** Native controls и общие server operations; browser proof G2, а не предположение об unload.

**Test scenarios:**

1. Covers AE21, AE22. Тексты A/B восстанавливаются только в своей вкладке, без submit или изменения соседней вкладки.
2. Covers AE23, AE24. Refresh восстанавливает черновики и не вызывает новую операцию.
3. Covers AE25, AE26. Закрытая вкладка не восстанавливает черновики; другая вкладка и серверная история сохраняются.
4. Covers AE2, AE31. Отказ busy/no-source оставляет текст и объясняет причину; готовность источника сама не отправляет вопрос.
5. Covers AE19. Background A не отображается как ответ B; возвращение показывает актуальное состояние A.
6. Covers AE1, AE11, AE39. Fragments видны до ответа, паспорт сообщает фактический scope и skip limitations, вывод не отображается как исходная цитата.
7. Пока acceptance ACK задержан, владелец набирает новую revision текста; ACK прежнего вопроса её не стирает.
8. Keyboard/focus доступны для отправки, stop и раскрытия паспорта; документ/модельный HTML не исполняется в UI.
9. Logout/смена аккаунта не оставляет прежние черновики или recovery credentials доступными новому владельцу.

**Verification:** Реальные browser checks подтверждают G2 и поведение UI на серверном API; отсутствие production framework не отменяет accessibility/безопасный rendering.


## Settled decisions and capsule
---
title: "RAG Answer Lifecycle - Plan"
type: feat
date: 2026-10-13
topic: rag-answer-lifecycle
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
deepened: 2026-10-13
---

# RAG Answer Lifecycle - Plan

## Goal Capsule

- **Objective:** Владелец личной библиотеки получает полезные фрагменты до готовности ответа, видит его основания и сохраняет понятную историю при отмене или обрыве соединения.
- **Product authority:** Подтверждённое пользователем 2026-10-13 сводное описание текущего пути и действующий реестр `harness/project/decisions/2026-10-08-rag-architecture-decisions.md`, включая последнюю редакцию RAG-43 и последующие уточнения RAG-44–RAG-62.
- **Scope:** Путь одного вопроса от неотправленного черновика и приёма до ответа, ошибки или отмены, включая ранние фрагменты, ожидание, источники и навигацию между беседами и вкладками.
- **Means:** Общий серверный запрос, сохранённая выдача и независимые contexts выбранной локальной модели — KTD1–KTD4.
- **Execution boundary:** Реализация и её приёмка выполняются по U1–U8 отдельным поручением; отрицательные proof gates останавливают соответствующую зависимую работу.
- **Open blockers:** Вопросы Q01–Q13 из полной ревизии от 2026-10-13 согласованы в RAG-50–RAG-62; открытых продуктовых вопросов этого списка нет. Технические допущения и проверки перечислены ниже и в `harness/project/docs/ideation/2026-10-13-rag-brainstorm-question-audit.md`; условный внешний маршрут не активирован.

---


## Product Contract Key Decisions (settled structure pins)

- **Серверная беседа — общая точка состояния вкладок.** Governs R2, R8, R9, R19; основание — RAG-25/RAG-42.
- **Сохранение прерванного текста.** Governs R11. (session-settled: user-directed — chosen over deleting partial output: сохранение видимого результата без его использования как основания следующего ответа.)
- **Отмена по инициирующей вкладке с ожиданием восстановления.** Governs R12–R16, R20; действует последняя редакция RAG-43 вместо прежней отмены по последней вкладке.
- **Ошибка завершается без автоматического повтора.** Governs R11, R20–R22. (session-settled: user-directed — chosen over one automatic retry: сохранение частичного результата и явная отправка нового вопроса пользователем.)
- **Переключение беседы сохраняет выполняющийся запрос.** Governs R23, R24. (session-settled: user-directed — chosen over immediate cancellation on navigation: сохранение результата в исходной беседе при переключении.)
- **Переключение сохраняет черновик исходной беседы.** Governs R25. (session-settled: user-directed — chosen over clearing the draft on navigation: восстановление набранного текста при возвращении в беседу.)
- **Обновление страницы сохраняет черновики этой вкладки.** Governs R26. (session-settled: user-directed — chosen over clearing drafts on refresh: восстановление отдельных текстов бесед без отправки вопроса.)
- **Закрытие вкладки удаляет её черновики.** Governs R27. (session-settled: user-directed — chosen over restoring drafts on the next app opening: хранение неотправленного текста ограничено сроком открытой вкладки.)
- **Уменьшение лимита сохраняет уже активные запросы.** Governs R5, R28. (session-settled: user-directed — chosen over pausing or cancelling excess active requests: новое ограничение действует на дальнейший допуск.)
- **Сохранённые настройки переживают перезапуск.** Governs R29. (session-settled: user-directed — chosen over resetting admin changes to file defaults on restart: сохранённые переопределения имеют приоритет.)
- **Без готовых источников вопрос сохраняется черновиком.** Governs R30. (session-settled: user-directed — chosen over storing the question with an explanatory result in history: отказ до приёма, без генерации.)
- **Удаление использованного источника останавливает текущий запрос.** Governs R11, R16, R18, R31. (session-settled: user-directed — chosen over completing the current answer after source deletion: остановка и сохранение частичного текста с обеими отметками.)
- **Документ доступен только как целиком готовый источник выбранного режима.** Governs R1, R30, R32, R34. (session-settled: user-directed — chosen over searching successfully extracted pages of a failed document: атомарная готовность всего файла.)
- **OCR-правки сохраняют первоначальную историю.** Governs R18, R33. (session-settled: user-directed — chosen over keeping affected answers in subsequent context: старые ответы и цитаты видимы с отметкой, но не передаются в будущий контекст.)
- **Пропуск рукописей требует явного выбора владельца.** Governs R6, R7, R32, R34. (session-settled: user-directed — chosen over rejecting every mixed PDF without handwriting permission: предупреждение и выбор отмены либо печатного текста с блоками пропусков.)
- **Потеря серверного состояния прерывает запрос без повтора.** Governs R8, R9, R11, R20, R35. (session-settled: user-directed — chosen over automatically restarting the question: сохранённый частичный ответ и повторная отправка владельцем.)
- **Текущий план охватывает один путь пользователя.** Governs R1–R35; другие принятые идеи MVP остаются отдельными областями работы.

<!-- ce-section: work-relationships -->

## Technical Decisions (settled structure pins)

- KTD1. **PostgreSQL определяет приём и конечное состояние запроса.** Governs R2, R8, R10, R17, R19, R30, R35. Общий серверный запрос хранит владельца, беседу, ключ операции, fingerprint входа, этап, причину завершения и версию исполнения. Транзакция под блокировкой беседы повторно проверяет доступ и готовые источники, затем вместе сохраняет вопрос и занимает беседу. Уникальность операции и одного незавершённого запроса обеспечивается также ограничениями БД. Повтор с прежним ключом разрешается после проверки текущего доступа и до проверки занятости; другой payload с тем же ключом отклоняется. Отказ до приёма не создаёт историю или очередь. Основание механизма — [PostgreSQL locking](https://www.postgresql.org/docs/current/explicit-locking.html).

- KTD2. **История и выдача используют сохранённый журнал событий.** Governs R2, R3, R9, R11, R13, R19, R24, R35. В одной транзакции фиксируются очередной текстовый фрагмент, его последовательный номер и изменение запроса; SSE читает только committed события. Snapshot возвращает согласованные состояние, текст и watermark; доставка продолжается после него, без разрыва между replay и live. Идентификаторы беседы и запроса в событии предотвращают смешивание результатов навигации. Формат следует [WHATWG SSE](https://html.spec.whatwg.org/multipage/server-sent-events.html); курсор доставки не предоставляет доступ и не запускает граф. В MVP журнал не обрезается во время выполнения; устаревший или недопустимый курсор возвращает разрешённый snapshot либо отказ.

- KTD3. **Один координатор владеет генерацией для всего сервиса.** Governs R4, R5, R28, R35. Координатор — отдельный процесс внутри backend, общий для API-процессов; очередь находится в PostgreSQL. Выделенное соединение держит service-wide advisory lock, а каждая команда и запись результата несут epoch исполнения. Один deployment supervisor владеет coordinator/native process и прекращает его при потере владения. Замена допускается к загрузке модели только после подтверждённого terminate/reap предшественника; без этого подтверждения replacement заблокирован. Epoch запрещает старые команды, а завершение процесса отдельно доказывает освобождение памяти и reservations. Автоматический failover на другой host этим механизмом не вводится. Новый coordinator прерывает потерянные исполнения после fencing/reap, включая принятые, но ещё не переданные ему вопросы; здоровый API-restart сам их не прерывает. При недоступности coordinator новые вопросы получают объяснимый отказ до приёма. Redis, Celery и дополнительный брокер для этого пути не нужны.

- KTD4. **Шагами llama.cpp управляет координатор через low-level API.** Governs R5, R28. Предпочтительный механизм — существующие [низкоуровневые Python bindings](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/) с одной загруженной моделью и отдельным native context/sampler для каждого активного запроса. Это позволяет выбирать следующую группу runnable запросов и вычислять по одному следующему токену каждому, сохраняя round-robin порядок. Обработка prompt делится на ограниченные порции между такими группами. Размер шага не подменяется размером native batch или числом HTTP completion; speculative decoding отключён. Возможность подтверждается в U1 на выбранной модели и зафиксированной сборке; интерфейс [llama.cpp](https://raw.githubusercontent.com/ggml-org/llama.cpp/master/include/llama.h) сам по себе не доказывает память и скорость. Изменение активного лимита не уничтожает имеющиеся contexts; расширение требует реальной доступной ёмкости. Если поддержка немедленного изменения не доказана, зависимая реализация останавливается, без скрытого clamp, перезапуска или замены R5.

- KTD5. **Переопределения настроек сохраняются в PostgreSQL.** Governs R5, R28, R29. Предлагаемый `backend/config/runtime.toml` задаёт стартовые дефолты; валидированные сохранённые значения и revision имеют приоритет. Координатор читает новую committed revision перед следующим допуском и шагом. Ответ административной операции сообщает сохранённую revision и подтверждение её применения, не выдавая запись в БД за уже применённый лимит. Глобальные записи допускаются только super_admin и аудируются. Параметры, требующие перезапуска, доступны для просмотра и отклоняются при прямой записи API. Диапазоны изменяемых параметров определяются U1, без новых произвольных численных ограничений. Это способ реализовать согласованное сохранение настроек, а не уже установленный конфигурационный файл.

- KTD6. **Поиск и паспорт опираются на целиком опубликованные ревизии.** Governs R1, R3, R6, R7, R18, R30–R34. Граница документов предоставляет owner, document/revision ID, текущую published revision, статус удаления, chunks, координаты и ограничения выбранного режима. Приём фиксирует выбранную область; поиск повторно проверяет её доступность, не расширяя набор. До передачи текста в модель или ранней выдачи сохраняются зависимости запроса от реально используемых ревизий. Паспорт различает выбранные, доступные, найденные и переданные модели источники. Цитаты сверяются с сохранёнными разрешёнными spans; выводы модели отображаются отдельно. При готовых источниках без совпадений вопрос следует R4/R7; отказ R30 применяется только к отсутствию готовых доступных источников.

- KTD7. **Контекст нового вопроса строится заново из допустимой истории.** Governs R11, R17, R18, R20, R33, R35. `AsyncPostgresSaver` сохраняет состояние графа, но не является историей UI или авторитетом доступа. Серверная связь graph `thread_id` с владельцем, беседой, request и context epoch проверяется до каждого обращения к saver. Каждый новый request получает отдельную persistence identity, однозначно связанную с беседой по RAG-29; прежний checkpoint не загружается как input нового вопроса. Backend собирает graph input из разрешённых завершённых сообщений и текущих ревизий. Provenance переданного исторического контекста входит в зависимости нового ответа транзитивно. Общая saver boundary сериализует checkpoint reads/writes и pending writes с проверкой execution/context epochs; invalidation закрывает запись старого исполнения. Его state не используется в новом запросе, а старые ответы и первоначальные цитаты сохраняются независимо. Запуск терминального или потерянного исполнения через resume запрещён. Это ограничение интеграции поверх [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), а не обещание автоматической очистки библиотекой.

- KTD8. **Все причины остановки проходят общий переход и барьер выдачи.** Governs R10, R11, R15–R18, R21, R22, R31, R33, R35. Finish, stop, ошибка, timeout, изменение доступа и удаление источника сериализуются с публикацией результата. Условный переход из незавершённого состояния фиксирует один исход; поздний callback с прежним epoch не меняет историю. Занятость беседы снимается логически, а physical reservation coordinator освобождается только после подтверждённого удаления native context. Необратимая граница выдачи — авторизованный handoff байтов ASGI/transport. Проверка owner/source/request fences и этот handoff участвуют в одном межпроцессном барьере invalidation; ранее прочитанное событие само не разрешает поздний send. Mutation сначала закрывает новые выдачи, затем подтверждается после завершения предшествующих handoffs. Ожидание backpressure не держит DB-lock: неподанные события отменяемы, после ожидания проверка повторяется. Уже handed-off байты отозвать невозможно. Реальная поддержка такого порядка транспортом доказывается в U7/U8, включая replay; один вызов стандартного ASGI send её не подтверждает. OCR-исправление само не добавляет отмену текущего запроса: provenance отмечает также позднее завершившийся ответ старой ревизии и исключает его из будущего контекста по R33.

- KTD9. **Соединение принадлежит вкладке, независимо от открытой беседы.** Governs R9, R12–R16, R19, R20, R23, R24. Сервер связывает запрос с аутентифицированной вкладкой и выдаёт ей proof восстановления; tab ID не заменяет auth. Один tab-level SSE и подтверждения heartbeat обслуживают также фоновые беседы. Разрыв обнаруживается по закрытию соединения либо потере подтверждений, после чего фиксируются deadline и connection epoch. Reconnect и timeout проверяют deadline под одной блокировкой; устаревшее событие прежнего соединения не отменяет восстановившуюся вкладку. Наблюдатель не обновляет presence инициатора. При запоздавшем reconnect сервер сначала завершает просроченное незавершённое исполнение; отложенный запуск timer callback не продлевает R12. Навигация, скрытие вкладки и смена наблюдаемой беседы сами не считаются разрывом.

- KTD10. **Для этого пути достаточно браузерных ES modules.** Governs R3, R6, R7, R9, R23–R27. Предлагаемый frontend использует HTML/CSS и native JS без нового production framework и сборщика. Общий state reducer принимает только авторитетные версии запросов; event handler проверяет принадлежность результата беседе. Черновики хранятся отдельно по владельцу и беседе в tab-local `sessionStorage`, а подтверждение отправки удаляет только отправленную revision черновика. Новая или дублированная вкладка получает самостоятельную identity и proof. [Session storage](https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage) переживает reload и может переживать restore; [pagehide](https://developer.mozilla.org/en-US/docs/Web/API/Window/pagehide_event) не является надёжным сигналом закрытия. Поэтому механизм хранения становится окончательным только после U1: R26/R27 нельзя объявлять выполненными по названию storage. Отрицательный результат требует решения о доказанном конфликте платформы, без ослабления R27. Logout/смена владельца очищают локальные credentials и черновики прежнего владельца.

