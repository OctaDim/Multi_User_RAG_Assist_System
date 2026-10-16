# Аудит конфигурационных значений приложения

Дата создания: 2026-10-16. Основание: поручение пользователя после реализации двух точек запуска, коммит `ebd8bcd`.
Первичный статический аудит выполнен до переноса; позиции ниже относятся к исходному состоянию этого коммита. Результат переноса и владельцы параметров описаны в [настройках приложения](2026-10-16-application-settings.md).

## Область

Проверены исполняемые модули `backend/app/`, `backend/main.py`, `frontend/main.py`, HTML/JS фронта, существующие TOML-конфиги и их связь с API, моделями, миграциями и тестами. Исторические ревизии, schema contracts, fixtures и механизм harness не являются настройками установки приложения.

## Уже имеют владельца

- `backend/config/service.toml`: Python окружения, API/CORS origin, DSN/ожидание БД, пути моделей/оригиналов, SMTP, управление новым launcher.
- `frontend/config/service.toml`: HTTP binding, период обработки остановки, API origin и reconnect delay.
- `backend/config/runtime.toml`: модель генерации, max_active/step_width, контекст/потоки и метаданные embedding.
- `backend/config/ocr.toml`: имена, контрольные суммы и закреплённые профили printed/handwriting моделей, размеры их контекстов.
- `backend/config/documents.toml`: лимиты и исходные разрешения документов.
- Административные overrides генерации/документных политик уже сохраняются в БД; перенос defaults не должен создавать второго владельца этих overrides.

## Оставшиеся кандидаты

| Группа | Текущие значения | Источники и связи |
|---|---|---|
| Account input policy | email 3..254, пароль 15..1024, приглашение/verification token до 128, filename до 255 | `api/accounts.py`, `accounts.py`, `api/documents.py`, `documents.py`, `frontend/index.html`; общий источник публичных ограничений должен исключать расхождение HTML/API/domain. |
| Password hashing | scrypt n=131072/r=8/p=1, maxmem=268435456, dklen=32, salt=16 bytes, concurrency=1 | `accounts.py:28,45,49–61`; параметры уже кодируются в хеше, поэтому настраиваемый профиль должен сохранять проверку существующих паролей. |
| Tokens and lifetimes | account/tab token entropy 32 bytes, verification/invitation 1h, session 12h | `accounts.py:124,156,202,212,334,339`, `events.py:45,67,100`; размер сериализованного токена должен соответствовать публичным лимитам. |
| Mail content | тема подтверждения, шаблон письма и формулировка срока действия | `accounts.py:94–96`; отображаемый срок должен соответствовать настройке TTL, а fragment keys остаются протоколом. |
| Tab/SSE timing | grace=10s, ACK=15s, heartbeat=5s, SSE poll=.1s, sweeper=.25s | `events.py:13–14,203`, `api/tabs.py:51,65,67`; связанные интервалы должны иметь одного backend-владельца. |
| Generation scheduling | cancel watcher=.05s, active tick=.01s, idle tick=.05s | `generation.py:242,250`; сохранить отдельные значения active/idle. |
| Generation supervision | graceful/forced reap 3s/3s, DB connect=5s, lease=5s, renewal poll=.1s, worker-ready poll=.05s | `generation.py:309,312,317,371,403,461`; lease и watchdog обязаны использовать одно значение. |
| Retrieval and context | top-k=12, similarity=.75, response reserve=256, дублированный fallback n_ctx=4096 | `sources.py:34`, `rag.py:159,185,235`, `answers.py:25–35`; admission, packing и native runtime должны учитывать один контекст. |
| Embedding execution | tokenizer length=512, ONNX intra-op threads=1 | `rag.py:30,33`; длина ограничена совместимостью закреплённой модели. |
| Ingestion | digest read chunk=1MiB, текстовый chunk=800 chars, cancellation poll=.1s, queue poll=.25s | `document_worker.py:52,133,165,278`; выделение spans и отсутствие потери текста сохраняются. |
| Native generation execution | prefill n_batch/n_ubatch=32, token buffer initial capacity=32, tokenizer capacity headroom=16, повторные defaults потоков4/8 | `llama_runtime.py:13,46,108–110,160,178`; prefill slice и native batch должны оставаться согласованными. |
| OCR execution | detector intra/inter threads=2/1, native threads4/8, batch/ubatch128, CPU layers0, temperature0, max_tokens0 | `ocr.py:125–126,143–144,245,264`; значения профиля не должны получать второй fallback в коде. |
| Raster and detection tuning | render width=1200px, white cutoff245, bbox padding12px, detector confidence=.5, component min-height12/min-pixels30/aspect2.5/max-density.65, union overlap=.8 | `ocr.py:35,89–96,171–175,186,212–216`; пороги настраиваемые, формулы преобразования координат остаются алгоритмом. |
| OCR fragment tuning | fragment limit2400px, overlap128px, foreground cutoff245, spanning width .8, edge tolerance1px, duplicate overlap .8/.5 | `ocr_fragments.py:5,9,44,46,69,76`; overlap меньше limit, один foreground threshold для согласованных стадий. |
| Model prompts | RAG SYSTEM и заключительная инструкция, handwriting transcription prompt, printed Spotting task | `rag.py:141–151,169`, `ocr.py:244,260–263`; сохранять исходные строки/пробелы и специальные токены выбранной модели. |
| Public UI parameters | формы254/15/1024/128, label с числом15, supported file filter, textarea rows4/12, abbreviated ID length8 | `frontend/index.html:20–29,43,51`, `frontend/src/app.js:171`, `conversations.js:145`; формы зависят от backend policy, остальные параметры принадлежат фронту. |

## Не считать свободными настройками установки

- HTTP-коды, методы, заголовки, SSE/ASGI имена, URL-маршруты, MIME и идентификаторы ролей/состояний/ошибок — публичные протоколы.
- SHA-256 идентификаторы сохранённых токенов, one-use semantics, guarded H11/asyncio transport, epoch/lease ownership и host fence — существующие контракты безопасности.
- SQLAlchemy server defaults и ограничения таблиц, ревизии Alembic и их контрольные контракты описывают сохранённую схему, а не локальные настройки.
- Размерность vector384, формат LOC-координат0..1000, байтовые диапазоны изображения0..255 и input geometry детектора640 — модельные/математические контракты. Изменение профиля требует совместимости, а не свободного изменения числа.
- Индексы массивов, шаги обхода координат, increments, сигнал/flag номера Linux и signed BIGINT bound — механика алгоритмов и платформы.
- Fixture values и ожидаемые ответы тестов не должны автоматически брать expected из рабочей конфигурации; иначе проверка потеряет независимость.
- CSS-значения уже находятся в таблице стилей. Русские подписи/сообщения интерфейса — продуктовый контент; отдельная локализация не нужна для настройки эксплуатации.

## Требования к переносу

Сохранить текущие defaults, байты prompt и совместимость существующих паролей/данных. Использовать текущие TOML-владельцы по назначению и отдельный backend-владелец для account/security и transport policy. Общие значения и шаблоны отслеживать, рабочие локальные overrides исключать точными Git-правилами. Передавать браузеру только явный публичный subset; не сериализовать backend-конфиг целиком.

Проверки должны менять настройку и наблюдать результат: истечение TTL, согласованность формы/API, retrieval/context limits, chunk boundaries, OCR geometry/default profile, интервалы supervision и отсутствие секретов в публичном ответе. Перенос defaults сам по себе не является новым измерением качества модели.
