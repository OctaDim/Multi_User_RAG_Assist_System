# U4: общий генератор, physical cancellation и полная регрессия

Дата: 2026-10-13. Прикладной этап U4 проверен; интеграционная приёмка всего
lifecycle, G3–G5 и U5–U8 остаётся открытой. Основание: U4/KTD3–KTD5/KTD8
[плана](../../../../docs/plans/2026-10-13-0244-feat-rag-answer-lifecycle-plan.md).
Исходный commit: f417842. Это прикладные результаты, не приёмка механизма harness.

## Результат

`rag-generation` запускает один supervisor и native worker для всех API-процессов.
Одна Qwen-модель обслуживает отдельные context/sampler. Coordinator продвигает
ограниченную группу запросов по round robin, перечитывает committed settings перед
каждым допуском и сохраняет прежние contexts при уменьшении лимита. Удаление context
подтверждается реальным close ACK; логическое завершение не освобождает physical
reservation преждевременно. Ошибки сохраняют уже committed prefix, исключают его
из будущего контекста и не создают автоматического повтора или пустого assistant.

Advisory connection и execution epoch запрещают старые записи. Унаследованный
Linux flock, PID/start-time record и подтверждённый terminate/reap отдельно
исключают одновременную загрузку replacement-модели. Worker получает PDEATHSIG;
неподтверждённый predecessor блокирует замену. Механизм закреплён за одним
host/UID/mount namespace; автоматическое межхостовое переключение не реализовано.
Принятые, searching, queued и generating запросы после потери исполнения получают
общий terminal transition, completed сохраняется.

Migration 003 отделяет heartbeat lease от строки service epoch. Admission и
checkpoint/native guards блокируют service row, а supervisor обновляет только
lease того же epoch. Совпадение epoch обязательно для healthy; старый cleanup
не может погасить новый lease. Уже committed migrations 001/002 не изменены.

## Доказательства и исправленные дефекты

Поведение изменено. До реализации проверены admission/history/settings/source/
graph/native тесты и их реальные callers. Добавлены scheduler, production runtime,
service recovery и two-API integration проверки; существующий admission тест
расширен состоянием первоначального `-infinity` lease. Использована test-first
стратегия и отдельная characterization перед упрощением allocation cleanup.

- [scheduler-red-v1.txt](scheduler-red-v1.txt) и
  [supervisor-red-v1.txt](supervisor-red-v1.txt) сохраняют исходные отрицательные
  проверки; focused результаты находятся в `scheduler-green-v1.txt`,
  `scheduler-supervisor-green-v1.txt` и `scheduler-supervisor-green-v2.txt`.
- [allocation-cleanup-characterization-v1.txt](allocation-cleanup-characterization-v1.txt):
  1 passed, 2.33 s. Ошибка native allocation освобождает reservation, не создаёт
  пустого ответа и разрешает новый явно отправленный вопрос. После этого удалены
  лишние проверки состояния allocation future.
- [unavailable-infinity-red-v1.txt](unavailable-infinity-red-v1.txt) воспроизводит
  Psycopg DataError при чтении `-infinity` как datetime. Guard теперь получает
  вычисленный SQL healthy, без декодирования бесконечного timestamp.
- Первый полный прогон [parent-all-app-v1.txt](parent-all-app-v1.txt):
  1 failed, 77 passed, 218.15 s; harness — 168 passed, 32.17 s. Native supervisor
  ошибочно принимал блокировку service row обычным запросом за потерю владения.
  [heartbeat-lock-red-v1.txt](heartbeat-lock-red-v1.txt) отдельно воспроизводит
  этот дефект при удержании FOR SHARE на одну секунду: 1 failed, 9.09 s.
  После выделения lease [heartbeat-lock-green-v1.txt](heartbeat-lock-green-v1.txt)
  даёт 1 passed, 11.59 s. Финальный набор проверяет оба режима SHARE и UPDATE.

Native unit использует настоящие Qwen weights и неизменённый U1 baseline:
interleaving, UTF-8, EOS, полный 4096 context, abort внутри C, освобождение
context/sampler и shutdown. См.
[результаты native worker](../2026-10-13-answer-lifecycle-u4-native/result-20261013-native-v1.json).
Two-API тест доказывает 12 contexts, очередь 13-го, fair prefill rounds при
3→2→4, hot admission 12→6→12, неизменные pointers, потерю acceptance ACK,
здоровый API restart и 19 реальных release ACKs. Его отдельный
[отчёт](../2026-10-13-answer-lifecycle-u4-multi-api/2026-10-13-u4-multi-api-report.md)
сохраняет focused результаты; canonical rerun находится здесь с prefix
`parent-full-v2`. Prefill trace не выдаётся за доказательство sampled-token EOS.

## Авторитетная полная проверка после последнего изменения

По прямому требованию пользователя следующий U допускается только после всех
накопленных прикладных тестов и всех активных harness tests, без замены одного
набора другим. Исторические inbox-копии не являются активными тестовыми roots.

```sh
xvfb-run -a uv run --project backend --frozen --cache-dir /tmp/rag-answer-lifecycle-uv-cache pytest -c backend/pyproject.toml backend/tests --basetemp /tmp/rag-u4-full-v2 -q -s
uv run --project backend --frozen --cache-dir /tmp/rag-answer-lifecycle-uv-cache pytest -c pytest.ini -q
```

- [parent-all-app-v2.txt](parent-all-app-v2.txt): **80 passed, 192.19 s**, без skips.
  Включены все U1 browser/runtime, U2, U3 и U4 тесты; реальные PostgreSQL,
  E5 ONNX, Qwen, два API и Chromium/Xvfb.
- [parent-all-harness-v2.txt](parent-all-harness-v2.txt): **168 passed, 25.51 s**, без skips.
- `python3 -m compileall -q backend/app backend/tests`, `git diff --check` и
  `uv run --project backend --frozen ... rag-generation --help` успешны.
  ONNX help emitted an environment telemetry-ID persistence warning;
  it did not fail the command or load Qwen weights.

Canonical recovery fault удерживает callback внутри настоящего native C decode,
затем завершает только собственную advisory connection. Predecessor PID 176183
подтверждённо reaped до replacement PID 176267 (epochs 2→3). Сохранены пять
символов prefix; единственный generating state не запускается повторно. Raw
first/second/competing/healthy supervisor logs скопированы из owned pytest tmp
без изменения оригиналов. Все subprocess tests выполняют собственный teardown.

Три readonly simplify reviews не выявили оставшихся actionable findings.
Применены: минимальная первая request projection, applied_revision UPDATE только
при изменении и characterisation-backed allocation cleanup. Повторная quality
проверка lease fix подтверждает epoch matching и независимость heartbeat от
service locks. Ускорение численно не заявляется.

## Границы доказательства

Principal/session/tab и source publication в DB-focused тестах — явные contract
fixtures. Они не закрывают реальный issuer, email verification, upload/OCR или
G3/G4. По ответу пользователя реальные тестовые аккаунты и документы должны
создаваться через E2E и браузерный интерфейс сервиса; эти зависимости ещё нужны
для финальной приёмки. SSE/transport handoff barrier, UI/citations, U5–U8,
самостоятельное frontend/backend размещение и joint OCR load пока не проверены.
Нет доказательства ёмкости выше 12 и нет нового произвольного runtime cap.
Версии и hashes Qwen/E5 сохраняются в U1/U3 и native/multi-API evidence.

Raw logs сохранены отдельными путями; неудачные прогоны не перезаписаны.
`2026-10-13-raw-hashes.json` связывает неизменяемые логи этого каталога с SHA256.
