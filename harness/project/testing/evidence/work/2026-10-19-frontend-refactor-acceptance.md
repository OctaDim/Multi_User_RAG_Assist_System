# Приёмка полного рефакторинга фронта

Статус: приёмка рефакторинга фронта R1–R30 завершена. Обычный запуск проверен. Три расширенные native-проверки остаются неуспешными; полный серверный suite не объявляется зелёным.

Основа — [согласованный план](../../../docs/plans/2026-10-18-2335-refactor-frontend-usability-plan.md). Последнее указание пользователя определяет вариант **A: беседа в центре**, основания раскрываются рядом. Промежуточный C сохранён только в исторических записях. Название — «Корпоративная база знаний RAG». Пустой выбор означает все готовые доступные собственные документы; явный выбор ограничивает область.

## Основания проверки

- [Все40 текущих браузерных случаев](2026-10-19-frontend-browser-current-verification.json): реальные SMTP/API/OCR/E5/модель, три инвалидации, редактор, scopes/ACK, роли, retry, клавиатура и длинные меню. Три завершённых последовательных раздела; последний29passed977.49s. Предшествующие отказы сохранены.
- [Финальный снимок46 source/test файлов](2026-10-19-frontend-source-final-v2.json); [текущие reducer проверки](2026-10-19-frontend-reducer-final.junit.xml):3passed. Восемь критических runtime/backend/config файлов байт-в-байт совпадают с базой.

- [Технические проверки: 415 уникальных успешных случаев](2026-10-19-frontend-core-verification.json), включая admission/replay/источники, draft reducer, запуск, API и локальную конфигурацию. Разделённые прогоны и успешные повторы перечислены по nodeid; предшествующие ошибки не удалены.
- [Браузерные проверки: 37 уникальных успешных случаев](2026-10-19-frontend-browser-verification.json). Реальные SMTP, аккаунты, API, документы, OCR, E5 и модель; управляемые отказы дополняют настоящие действия. Это карта успешных случаев, а не заявление об одном непрерывном зелёном прогоне.
- [38-й браузерный случай: timeout чтения статусов](2026-10-19-frontend-refresh-timeout.junit.xml): запрос освобождает управление после настроенного таймаута, сохраняет dirty редактор и допускает успешный ручной повтор.
- [39-й случай и свежие проверки после локальной обратной связи](2026-10-19-frontend-post-feedback.junit.xml): 16 passed, затем отказ transport только на старом ожидаемом тексте состояния. [Точный transport retry](2026-10-19-frontend-transport-final.junit.xml): 1 passed82.63s. Все assertions самого восстановления, контекста, вкладок, черновиков и origin timeout сохранены.
- [Клавиатура, reload, мобильная область чтения и фокус цитаты](2026-10-19-frontend-workspace-final.junit.xml): 3 passed. Отдельный управляемый renderer-тест проверяет сохранность фокуса; реальный model/citation сценарий проверен независимо.
- [Правила и механизм проекта](2026-10-19-frontend-harness.junit.xml): 168 passed.
- [Обычное приложение, финальная проверка](2026-10-19-frontend-ordinary-readiness-final.json): рабочая конфигурация, API/frontend200, здоровая generation lease epoch9,0незавершённых запросов; реальный Chromium1440/768/375 ready/login enabled без JSerrors/overflow.
- [Обычное приложение, первоначальная проверка](2026-10-19-frontend-ordinary-readiness.json): API/frontend HTTP200, здоровая generation lease epoch8, 0 незавершённых запросов; Chromium ready/login enabled без JS errors/overflow на1440/768/375. Позднее при тяжёлом native-прогоне обычный supervisor завершился с ownership connection stalled; после завершения нагрузочных тестов оно восстановлено, свежий epoch9 receipt приведён выше.
- [Заключительная проверка workspace после CSS nowrap](2026-10-19-frontend-workspace-nowrap.junit.xml): 3 passed24.85s; свежие планшетный/мобильный кадры ниже.
- Текущая коллекция: 492 application cases = 415 technical + 40 browser + 28 integration + 9 runtime. Все integration/runtime случаи исполнены; остаточный native-прогон завершился [20 passed / 6 failed](2026-10-19-frontend-native-remainder-01.junit.xml). Все 9 runtime прошли. После [точечных повторов:4passed1failed](2026-10-19-frontend-native-retry-02.junit.xml) имеются34 положительных native-результата и3 незакрытых отказа; полный native suite не объявляется зелёным. [Итоговая карта всех492 случаев](2026-10-19-frontend-final-case-ledger.json) связывает точные nodeid с исходными receipts.
- [Исторический снимок кода до последнего исправления меню](2026-10-19-frontend-source-candidate-v1.json):46 файлов; generation/llama_runtime/db/auth/launcher/backendmain/runtime/policy совпадают с базой задачи. После него изменены меню и синхронизация тестовых действий; финальный снимок должен фиксировать эти изменения. Это не утверждение о зелёном полном native suite.
- [Ход реализации, RED/green, ошибки окружения и исправления](2026-10-19-frontend-refactor-implementation.md). [Руководство по конечному интерфейсу](../../../docs/2026-10-19-frontend-interface.md).

Ниже обозначены реальные модули тестов: **Accounts** — browser/test_accounts.py; **Workspace** — browser/test_frontend_workspace.py; **Conversations** — browser/test_frontend_conversations.py; **Answer** — browser/test_answer_lifecycle.py; **Drafts** — browser/test_draft_lifecycle.py; **Documents** — browser/test_documents.py; **Management** — browser/test_frontend_administration.py; **Invalidation** — browser/test_invalidation.py. Все находятся в backend/tests; точные nodeid и исходные receipts доступны в картах выше.

## Проверка каждого требования

| Требование | Текущее поведение и доказательство |
| --- | --- |
| R1 | index.html/navigation.js/styles.css: одна центральная беседа, отдельные документы/управление; Workspace и снимки chat. |
| R2 | conversations.js выбирает основания конкретного ответа; navigation.js раскрывает aside и возвращает беседу; Conversations selected_old_answer и evidence снимки. |
| R3 | Общие CSS-токены, формы, карточки и диалоги всех разделов; визуальный осмотр 375/768/1440, Accounts/Documents/Management. |
| R4 | Пустые состояния, локальная загрузка/результат/ошибка, bootstrap retry, document report; Workspace policy_failure, Management, Documents, Conversations local submission/creation/selection failure and retry. |
| R5 | title, h1 и aria-label бренда в index.html содержат согласованное название; реальные снимки. |
| R6 | Accounts: регистрация/SMTP/приглашение, повтор после отказа почты, email verification, вход, роль, блокировка/деактивация, выход. |
| R7 | conversations.js: создание и список с названиями по вопросам; Answer independent_conversation, Conversations selected_old_answer. |
| R8 | drafts.js + navigation.js: черновик и источник связаны с owner/tab/conversation; Workspace reload, Answer independent/delayed_ack, Conversations scopes. |
| R9 | Технические reducer/admission/replay и реальные Drafts/Answer restore, duplicate/opener, новая вкладка, новый владелец и поздний ACK. |
| R10 | renderComposer показывает конкретное препятствие и следующий шаг, сохраняет вопрос; Answer no_sources/never_auto_submits, Conversations unavailable scopes. |
| R11 | Состояния поиска/очереди/генерации/завершения и stop feedback; Conversations stop503 и terminal-before-late-POST; Answer actual model. |
| R12 | Ранние основания до текста модели, выбранный старый паспорт, цитата/изменение источника; Answer fragments_precede, Conversations selected_old_answer, Invalidation. |
| R13 | Один pending operation/body, проверка неподтверждённой отправки, SSE recovery без повторной генерации; stream_recovery technical, Answer delayed_ack/old_snapshot. |
| R14 | Documents: TXT и настоящий PDF, режим OCR, отчёт, оригинал, исправление, новая публикация, скачивание и удаление. Original bytes проверены. |
| R15 | documents.js разделяет upload/queued/processing/ready/failed/mode choice; Documents permission_choice, queued_reopen, failed_publication; actual_document_boundaries report. |
| R16 | Editor state независим от списка; dirty dialog/beforeunload, pending publication, сохранность при внешнем удалении; Documents refresh_close_guard/external_delete/failed_publication/queued_reopen. |
| R17 | Native confirm содержит имя и последствия; отмена сохраняет документ/правки, подтверждение удаляет; Documents TXT/delete и dirty guard. |
| R18 | administration.js и role-aware navigation: отдельный раздел аккаунтов/policies/settings; Accounts и Management для реальных ролей. |
| R19 | Foreign library явно readonly с владельцем/возвратом; не меняет собственный onSources inventory; Management reverse_owner_response и refresh. |
| R20 | Preview/save и applied revision различимы; неизменяемые поля readonly; Management save503/manual retry и settings backend tests. |
| R21 | perform/feedback и предметные статусы рядом с формой/кнопкой; локальная причина отклонения вопроса привязана к беседе, сообщения создания/открытия имеют ручной повтор; Workspace policy failure, Conversations local errors/stop503, Documents upload/save failure, Management. |
| R22 | api.js ограничивает ожидание, включая чтение тела; неизвестная запись требует проверки; Documents admitted_upload_timeout, Conversations pending check, Management retry. |
| R23 | Поколения чтения и identity guards в app/documents/administration/conversations; Documents late_open и actual PDF late-mode result preserving B; Management late owner и Answer late ACK/snapshot. |
| R24 | Семантические кнопки/forms/details, видимый focus, native dialogs и focus restore; Workspace keyboard/skip, Conversations citation focus + mobile return, Documents cancel/close. |
| R25 | Responsive один DOM, узкий переключатель chat/evidence и компактные details; отсутствие горизонтального overflow, history >=200px при375x812; Workspace/Conversations и снимки всех разделов. |
| R26 | Пользовательский/модельный текст через textContent; роли и owner checks сохранены; Answer HTML stays text, Accounts и actual_authority matrix, source contract. |
| R27 | Существующие Python entrypoints/config, native ESM без сборщика/новых зависимостей; 415 technical включают четыре реальных main start/shutdown; ordinary-readiness-final receipt подтверждает фактический HTTP/browser/lease epoch9 на рабочей конфигурации. |
| R28 | answers.py/sources.py: [] разрешается в готовые собственные документы под locks при приёме; source/admission/context tests, Conversations actual all-ready owner question. |
| R29 | Непустая область никогда не расширяется; пропавшие IDs удерживаются до снятия пользователем; source contract, Conversations unavailable/removed scope, actual_document_boundaries. |
| R30 | Summary all/selected, сохранённый fingerprint/scope/mode/selected IDs и реальный паспорт; U1 tests, Conversations selected/all, Answer model passport. |

## Сценарии и исключения

| Сценарий | Подтверждение |
| --- | --- |
| F1 | Accounts + Workspace + настоящая authority matrix. |
| F2 | Answer + Conversations + source/admission/recovery technical. |
| F3 | Documents, actual print-only model passport и partial upload/failed report. |
| F4 | Documents с истинным OCR, неизменным оригиналом, dirty/delete и race cases. |
| F5 | Accounts/Management и успешные реальные settings restart/transport проверки; исходные receipts перечислены в implementation record. |
| AE1 | Workspace policy failure → retry → доступные формы. |
| AE2 | Workspace reload + Answer independent drafts + Conversations scopes. |
| AE3 | Conversations stop503 → ручной повтор → terminal. |
| AE4 | Answer delayed ACK/old snapshot; Drafts isolation; source replay. |
| AE5 | Реальные early fragments/citations и безопасный HTML текст. |
| AE6 | Refresh/close/cancel/delete, delayed open/mode, pending/failed correction. |
| AE7 | Роли, owner matrix, foreign readonly и settings save/retry. |
| AE8 | Клавиатура/skip/citation focus, responsive375/768/1440; timeout и локальные ошибки. |
| AE9 | Все готовые собственные источники, исключение чужих/нецелостных, fixed admission scope. |
| AE10 | Явно выбранные документы ограничивают retrieval/history и исчезнувшие IDs не расширяют поиск. |
| AE11 | Нет готовых источников → сохранённый черновик без очереди/истории/auto-submit при готовности. |

## Ревью и остаточные замечания

[Completed review receipt](2026-10-19-frontend-refactor-review.json): status complete, run_id20261019-004909-de28b8cb, десять native lenses плюс независимые merge/validation/report. Verdict **Not ready относится к зафиксированному исходному снимку**; он не переписан на Ready и не выдан за повторное независимое ревью.

Caller исправил и проверил все относящиеся к согласованному охвату находки: #1 позднее открытие документа не прерывает беседу; #2 открытый во время обработки редактор восстанавливает доступность после публикации/ошибки; #5 полнота R16 включает сохранность dirty текста при внешнем удалении и позднем результате PDF mode. Утверждения #3/#4 о происхождении регрессий отклонены validator как уже существовавшие, но сами дефекты входят в #5/R16 и также исправлены. Реальные Documents scenarios passed; фактический PDF test удерживает ответ настоящей принятой записи и проверяет сохранность заменившего редактора. Непроверенная производительность параллельной загрузки изображений длинного PDF не объявляется измеренной и не меняет согласованный функциональный охват.

Дополнительная caller-проверка R21 выявила отсутствие локальных ошибок вопроса/создания/открытия. RED receipts сохранены отдельно; добавлены локальные состояния с generation/operation guards и matching ACK clear. Свежие browser/reducer/actualACK/source/setting/transport проверки прошли. Последующие caller-исправления не выдаются за отдельное независимое повторное ревью.

## Известный результат расширенной серверной проверки

[WholePDF native run04](2026-10-19-frontend-integration-04.junit.xml) завершился FAILED1697.49s. Реально распознаны [15 страниц](2026-10-19-frontend-long-pdf-fifteen-pages.jsonl), достигнут [контрольный отказ на странице16](2026-10-19-frontend-long-pdf-page16-report.png), проверены неизменность оригинала и недоступность целого файла. До вопроса [generation supervisor завершился с Coordinator ownership connection stalled](2026-10-19-frontend-long-pdf-generation.log); admission не создал статьи/запроса, ожидание ответа не прошло. Это не успешное доказательство последующих all/selected ответов именно этого тяжёлого сценария.

В окружении измерены около4GB RAM и существенный swap. Связь отказа с давлением памяти вероятна, но не объявляется доказанным единственным корнем. Соответствующий generation/SQL/session/runtime код не менялся относительно базы. Защитные таймауты/ownership guards не ослаблены ради зелёного результата. Результат отделён от успешных реальных PDF/документов/инвалидации и all/selected сценариев фронта; весь native suite не называется зелёным. Все остальные случаи уже исполнены. Точечные повторы после исправления меню и синхронизации API завершены:4passed1failed. Первоначальные отказы сохранены.


[Совместная нагрузка30аккаунтов, повтор](2026-10-19-frontend-native-retry-02.junit.xml) достигла12реальных контекстов и успешного изменения глобальных настроек. После перекрывающихся OCR и генерации все13запросов были прерваны по tab_timeout; assertion о сохранении12контекстов на измерении памяти не прошёл. [Исходный native log](2026-10-19-frontend-joint-stress-generation.log) и [диагностика запросов/PG](2026-10-19-frontend-joint-interruption-diagnostic.json) сохранены. На момент позднего снимка PG blockers отсутствовали, но это не исключает более раннюю задержку. Единственная причина не доказана; тест не называется успешным. Это третья незакрытая расширенная native-проверка, отдельно от40прошедших браузерных сценариев и нормального PDF→ответа.

Настоящие рукописи EN/RU/DE/BE и запретыOCR прошли после согласованного ожидания API: [результаты](2026-10-19-frontend-handwriting-native-results.json), [8нативных страниц](2026-10-19-frontend-handwriting-native-pages.jsonl). Оба terminal-повтора также прошли. Критерии распознавания, модели и защитные ownership/heartbeat deadlines не изменены.

[Сравнение первого барьера с исходным фронтом](2026-10-19-frontend-baseline-gate.junit.xml):1passed188.97s, десять реальных контекстов. [Точные assets и адаптеры](2026-10-19-frontend-baseline-gate-source.json). Текущий фронт также прошёл этот барьер и достиг12контекстов; поздняя jointOCR-фаза в baseline-пробу не входит. Это не доказательство причины её отказа и не полный baseline suite.

## Проверка длинных списков

Frozen benchmark выявил реальное перекрытие выбора источников списком бесед на 1280×720. Локальная репродукция на настоящих CSS/navigation с длинными контролируемыми списками воспроизвела отказ обычного клика. После исправления детали свернуты при входе на всех ширинах, раскрываются по одной, а список источников прокручивается внутри fieldset. Регрессия проверяет настоящий клик, клавиатуру, сохранность выбора и черновика. Полный нативный benchmark после исправления прошёл608.11s: [30/30 исходных вопросов](2026-10-19-frontend-thirty-question-results.json), [отдельная caller semantic сверка](2026-10-19-frontend-thirty-question-caller-review.json). Геометрическая проверка не подменяет этот модельный результат.

[Свежий browser run01](2026-10-19-frontend-browser-menu-01.junit.xml):10passed1failed (PDF lease). [Plain run02](2026-10-19-frontend-browser-menu-02.junit.xml): нормальный PDF→ответ прошёл без диагностики, затем раннее5s ожидание admission остановило snapshot test. [Run03](2026-10-19-frontend-browser-menu-03.junit.xml) завершился29passed977.49s, включая snapshot и все3 актуальные инвалидации. Итоговая текущая карта40 случаев приведена в начале документа; исторические карты37/39 сохранены отдельно.

## Визуальная проверка

После последнего изменения меню повторно сняты и осмотрены: [беседа1440](2026-10-19-frontend-chat-1440-menu-final.png), [беседа768](2026-10-19-frontend-chat-768-menu-final.png), [беседа375×812](2026-10-19-frontend-chat-375-812-menu-final.png), [основания1440](2026-10-19-frontend-evidence-1440-menu-final.png), [основания375](2026-10-19-frontend-evidence-375-menu-final.png). Свежая галерея соответствует final-v2; остальные кадры ниже сохраняют историю проверок.

Фактические изолированные аккаунты/документы/ответы. Снимки сохранены без редактирования. Полные 375/768/1440 исходники находятся в pytest-56; ниже сохранены ключевые кадры. Основные кадры сняты до последующей точечной CSS-правки #logout nowrap, не меняющей компоновку. Свежие workspace375/768 из pytest-60 проверяют исправленную шапку после неё.

- [Беседа1440](2026-10-19-frontend-chat-1440.png), [беседа375x812](2026-10-19-frontend-chat-375-812.png).
- [Основания1440](2026-10-19-frontend-evidence-1440.png), [основания375](2026-10-19-frontend-evidence-375.png).
- [Документы1440](2026-10-19-frontend-library-1440.png), [документы375](2026-10-19-frontend-library-375.png).
- [Управление1440](2026-10-19-frontend-administration-1440.png), [управление375](2026-10-19-frontend-administration-375.png).
- [Редактор PDF1440](2026-10-19-frontend-pdf-editor-1440.png), [редактор375](2026-10-19-frontend-pdf-editor-375.png).
- [Вход1440](2026-10-19-frontend-auth-1440.png), [вход768](2026-10-19-frontend-auth-768.png), [вход375](2026-10-19-frontend-auth-375.png).
- [Финальная шапка и workspace768](2026-10-19-frontend-workspace-768-final.png), [workspace375](2026-10-19-frontend-workspace-375-final.png).
- После последнего изменения обратной связи: [беседа1440](2026-10-19-frontend-chat-1440-final.png), [основания1440](2026-10-19-frontend-evidence-1440-final.png), [беседа375x812](2026-10-19-frontend-chat-375-812-final.png), [локальная ошибка вопроса375](2026-10-19-frontend-question-error-375.png).
- Планшетные исходные кадры: [беседа](2026-10-19-frontend-chat-768.png), [основания](2026-10-19-frontend-evidence-768.png), [документы](2026-10-19-frontend-library-768.png), [управление](2026-10-19-frontend-administration-768.png), [PDF](2026-10-19-frontend-pdf-editor-768.png). Обнаруженный здесь перенос кнопки выхода исправлен и отдельно переснят в final workspace768.

## Завершение

Согласованный вариант A, название и необязательный выбор источников реализованы; все существующие фронтовые действия, состояния, контекст, guards, адаптивность и клавиатура проверены. Обычные frontend/backend оставлены доступными по рабочей конфигурации: http://127.0.0.1:55848/. Из489успешно подтверждённых application случаев40браузерных относятся к текущему финальному интерфейсу; три расширенных native-отказа перечислены отдельно. Настройки/guards не ослаблялись, полный native suite не заявляется успешным. Независимое повторное ревью последующих caller-правок не заявляется. Пользовательские документы и прежние evidence сохранены.
