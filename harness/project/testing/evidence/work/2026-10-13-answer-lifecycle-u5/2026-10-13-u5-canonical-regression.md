# U5: canonical regression и parent review

2026-10-13. Исходный commit a45679b. Код U5 проверен; реальный G3/G4 issuer/
publisher, browser/proxy U8 и необратимый transport handoff U7/U8 остаются
открытыми. Основание — U5/KTD2/KTD8/KTD9
[плана](../../../../docs/plans/2026-10-13-0244-feat-rag-answer-lifecycle-plan.md).
Это прикладной результат, не приёмка механизма harness.

## Реализованное поведение

Приём нового вопроса требует подтверждённого stream challenge ACK своей вкладки.
Один tab-level SSE обслуживает все её фоновые беседы. Heartbeat и connection
epoch позволяют обнаружить потерю соединения независимо от видимости вкладки;
deadline на десять секунд принадлежит инициатору, а не наблюдателю. Только
своевременный ACK reconnect сбрасывает действующий grace. Поздний connect сначала
завершает просроченные запросы и может подтвердить новый connection для нового
явного вопроса; terminal запрос не запускается повторно.

Stop/failure/completion сериализованы с deadline. Model/saver guards проверяют
origin до позднего callback даже при задержке timer. API workers обслуживают
общий durable deadline независимо от гибели соседнего API. Lock order использует
tab до conversation; account SHARE не повышается до UPDATE. Snapshot/replay
brief service UPDATE ждёт предшествующих writers перед watermark, поэтому
меньший uncommitted event ID не теряется после большего committed ID.

DB read authorization отпускается до сетевого ожидания. Это необходимый
компонент, но не доказанный KTD8 handoff: пока StreamResponse может передать
ранее прочитанное событие после mutation. Реальный transport fence и его fault
proof остаются обязательной работой U7/U8.

## Evidence и parent изменения

[Отчёт implementation worker](2026-10-13-u5-implementation-verification.md)
сохраняет все RED/GREEN, точные callers, 23 новых тестовых случая и границы
доказательства. Его окончательный focused run: 60 passed, 2 real-asset cases
deselected, 26.72 s. Ни model/browser, ни полную регрессию worker не заявляет.

Три readonly simplify reviews завершены: reuse — без findings; quality — удалить
неактуальный комментарий о RED; efficiency — прекратить повторный polling
исторических terminal tabs и заменить 3N history round trips пакетными запросами.
Все три конкретных изменения применены без ослабления guards.

- [parent-idle-red-snapshot-characterization-v1.txt](parent-idle-red-snapshot-characterization-v1.txt):
  **1 failed, 1 passed, 23 deselected, 4.76 s**. Реальный FOR UPDATE lock
  неиспользуемой просроченной вкладки блокировал expiry другого инициатора до
  test timeout. Отдельный characterization заранее подтвердил формат snapshots
  нескольких собственных бесед, пустой беседы, порядок сообщений/requests,
  watermarks и отсутствие чужой беседы.
- Expired-deadline arm теперь выбирает только tabs с unfinished origin requests;
  connected/expired-ACK arm сохранён. Старый deadline остаётся для отказа late ACK.
- Новый `answers.histories` выполняет три history queries для всего проверенного
  набора conversations. Однобеседный snapshot и tab snapshot используют его;
  только что введённый непубликовавшийся `answers.history` и оба callers заменены.
  Сортировка и empty watermark 0 сохранены, общий barrier не изменён.
- [parent-simplify-green-v1.txt](parent-simplify-green-v1.txt): **62 passed,
  2 deselected, 26.30 s**. Добавлены два parent теста; измеренного ускорения
  throughput не заявляется.

## Полная проверка после последнего изменения

По прямому требованию пользователя выполнены все накопленные application tests
U1–U5 и все активные harness tests, с отдельными roots и неизменяемыми логами:

```sh
xvfb-run -a uv run --project backend --frozen --cache-dir /tmp/rag-answer-lifecycle-uv-cache pytest -c backend/pyproject.toml backend/tests --basetemp /tmp/rag-u5-full-v1 -q -s
uv run --project backend --frozen --cache-dir /tmp/rag-answer-lifecycle-uv-cache pytest -c pytest.ini -q
```

- [parent-all-app-v1.txt](parent-all-app-v1.txt): **105 passed, 205.55 s**, без
  skips/deselections. Включены все прежние U1 browser/runtime, U2/U3/U4 и U5
  проверки, реальные PostgreSQL, Qwen/E5, Chromium/Xvfb и два API.
- [parent-all-harness-v1.txt](parent-all-harness-v1.txt): **168 passed, 26.14 s**,
  без skips/deselections. Корневой pytest.ini охватывает восемь активных test files;
  других активных test*.py вне этого root не обнаружено. Inbox archives не
  подменяют активные tests и не перезапускаются как дополнительный suite.
- Compileall и git diff --check прошли. Отдельные lint/typecheck инструменты в
  проекте не настроены; они не заменены фиктивной успешной проверкой.

Прежний U4 multi-API/native тест теперь создаёт настоящий tab через POST API,
держит SSE и одноразовые heartbeat ACKs на сохраняющемся втором API, а все
19 conversations работают в фоне этой вкладки. Native fairness, hot limits,
ACK loss, API restart и real close ACKs снова проходят. Исторический U4 отчёт
описывает свой прежний fixture setup и не переписан; новый raw prefix здесь —
`parent-full-v1`. Все owned processes/thread закрыты тестовым teardown.
Recovery fault также повторён: native PID 187472 reaped до replacement 187533,
epochs 2→3, сохранён prefix из пяти символов; модель повторно вопрос не запускает.

Raw subprocess logs и новые хэши сохранены рядом без перезаписи прежних прогонов.
Миграции 001–003 не изменены; presence — новая controlled migration 004.

## Оставшиеся границы

Реальные SMTP verification/account flows и original upload/OCR/correction UI ещё
нужно реализовать, затем создавать тестовые сущности через пользовательский UI
и E2E по уточнению пользователя. Contract fixtures этого не доказывают.
Frontend/reducer, фактический browser/proxy heartbeat, source mutation transport
barrier, U6–U8 и G3–G5 не объявлены завершёнными. Runtime capacity выше 12,
joint OCR load и другие browser engines не проверены.
