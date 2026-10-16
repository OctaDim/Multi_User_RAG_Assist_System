# Настройки приложения

Приложение запускается из корня проекта двумя командами после подготовки Python-зависимостей, локальных моделей и PostgreSQL:

```sh
python3 backend/main.py
python3 frontend/main.py
```

Backend main проверяет конфигурацию и ресурсы, ждёт доступности PostgreSQL, затем управляет процессами документов, генерации и FastAPI. Генерация владеет отдельным native-процессом; завершение main останавливает всю запущенную им группу процессов. PostgreSQL должен работать отдельно, SMTP предоставляется внешним сервером. Подробности первоначальной настройки: [service-entrypoints](2026-10-16-service-entrypoints.md).

## Владельцы настроек

| Файл | Содержимое |
| --- | --- |
| `backend/config/service.toml` | Python, адрес API, frontend origin, DSN, пути моделей/оригиналов, SMTP, readiness и завершение процессов. |
| `backend/config/policy.toml` | Ограничения ввода, scrypt и случайные токены, сроки аккаунтов, шаблон письма, heartbeat/SSE, интервалы генерации и обработки документов, размер текстовых чанков. |
| `backend/config/runtime.toml` | Генерация и контекст, retrieval/response reserve, E5 length/threads/prefixes, native batch и начальные буферы. |
| `backend/config/ocr.toml` | Фиксированные артефакты моделей, контексты, CPU threads/batch, detector confidence, render/foreground/component thresholds, фрагменты и лимит вывода. |
| `backend/config/documents.toml` | Начальные ограничения и разрешения новых политик документов. |
| `backend/config/prompts.toml` | Исходные RAG и OCR prompts, включая модельные инструкции. |
| `frontend/config/service.toml` | Адрес HTTP-сервера, API origin, задержка переподключения, строки textarea и длина сокращённых ID. |

Общие TOML и `*.local.example.toml` хранятся в Git. Рабочие `service.local.toml`, `policy.local.toml`, `runtime.local.toml`, `ocr.local.toml`, `documents.local.toml`, `prompts.local.toml` исключены точными правилами `.gitignore`. Не помещайте реальные секреты в общие файлы или примеры.

## Локальные переопределения

Создайте нужные `*.local.toml` рядом с общими профилями, используя шаблоны `*.local.example.toml`. Файл содержит только меняемые ключи; остальные наследуются. Например, `backend/config/policy.local.toml`:

```toml
[accounts]
session_seconds = 28800

[ingestion]
chunk_characters = 600
```

Backend `--config /path/to/service.local.toml` или переменная `RAG_SERVICE_CONFIG` выбирает другой service override. Остальные `<profile>.local.toml` читаются из каталога этого выбранного файла; общие defaults продолжают браться из поставляемых backend/config. Путь нормализуется до смены cwd и передаётся дочерним процессам. У frontend отдельный `--config /path/to/service.local.toml`.

Настройки проверяются и кэшируются в пределах процесса. После изменения файлов перезапустите соответствующий main; backend нужно перезапустить целиком. Неизвестные ключи, неправильные типы, несогласованные context/reserve, batch/ubatch, fragment overlap и heartbeat/poll отвергаются до запуска дочерних процессов. Ошибка содержит имя параметра, а не его значение. Проверяются также диапазоны native C-типов и браузерных ограничений. Число retrieval sources ограничено 99 существующим форматом цитат.

Изменение E5 prefix/max_length влияет и на разбиение исходного текста: опубликованные чанки сохраняют точные интервалы и помещаются в выбранный tokenizer limit. Для уже проиндексированных документов смена модели или embedding prefix требует совместимой переиндексации; автоматическая миграция в эту задачу не входит.

## Совместимость и настройки в БД

Новые пароли используют текущие `security.scrypt_*` и `salt_bytes`. Вход сверяет параметры сохранённого хеша с текущим профилем или списком `security.legacy_scrypt`. При повторных сменах профиля сохраняйте в этом списке все профили, которыми созданы существующие пароли. `scrypt_maxmem` должен вмещать как текущий, так и разрешённые исторические профили. Сам формат хеша сохранён.

Ограничения `inputs.password_min/password_max` применяются к регистрации и входу; ужесточение этих ограничений может отклонить ранее допустимый ввод. Это отдельное изменение policy, не смена KDF-профиля. Шаблон verification-письма получает `{origin}`, `{token}`, `{expiry}`; expiry соответствует настроенному сроку.

Административные `max_active` и `step_width` продолжают переопределяться в PostgreSQL. Изменение `documents.toml` задаёт defaults новым политикам; уже сохранённые индивидуальные политики остаются под административным управлением. Миграции, SQLAlchemy ownership и схема БД не менялись.

## Публичные настройки

`GET /api/public-settings` без авторизации возвращает только явно перечисленные input limits и поддерживаемые форматы документов. Фронт применяет их до включения входа и регистрации; если политика недоступна, показывает ошибку и оставляет формы выключенными. Полная backend-конфигурация не сериализуется. UI-only значения выдаются HTTP-сервером фронта через отдельные разрешённые HTML meta-поля.

Сервер фронта раздаёт только index и JavaScript/CSS из src. Python, TOML и переходы за пределы публичных файлов недоступны через GET и HEAD.

## Границы переноса

Повторный поиск охватил исполняемый backend/frontend, точки запуска, конфиги, packaging и миграции. Оставшиеся числовые/строковые литералы классифицированы в [аудите](2026-10-16-configuration-audit.md): HTTP/ASGI/SSE и model token protocols, состояния и роли, CPU-only/greedy execution contracts, vector384, detector640, LOC1000, байтовые диапазоны и индексы, Linux flags/permissions, схема и исторические миграции. Это инварианты совместимости, а не изменяемые настройки установки. CSS и сообщения интерфейса остаются соответствующим продуктовым содержимым.

## Проверка

Новые проверки изменяют реальные local overrides, проверяют совместимость предыдущего scrypt-профиля, сроки в PostgreSQL, E5/native execution, retrieval/context и chunk spans, OCR geometry/model arguments, безопасный public allowlist и ограничения браузерных форм. Исходные prompts сверяются с независимыми SHA-256 baseline. Дополнительно выполнены техническая регрессия и браузерные сценарии регистрации/входа и работы с текстовым документом.

Результаты 2026-10-16:

- Основной технический набор: **344 passed**, 733.57 секунды. Команда: `uv run --project backend --frozen --no-sync pytest -c backend/pyproject.toml backend/tests --ignore=backend/tests/runtime --ignore=backend/tests/browser --ignore=backend/tests/integration -q`, с имеющимися локальными Qwen/E5/OCR и временным PostgreSQL.
- Последние изменения проверок диапазонов и policy: **23 passed** (`test_configured_policy.py` + `test_application_settings.py`); настройки публичного HTTP/DOM: **45 passed** (`test_application_settings.py`, `test_frontend_launcher.py`, `test_public_settings.py`). Наборы частично пересекаются.
- Chromium: **5 passed, 1 deselected** — весь `browser/test_accounts.py` и сценарий загрузки/исправления текстового документа из `browser/test_documents.py`; реальная native PDF-ветка браузерного файла не запускалась в этом дополнительном наборе.
- Проверка harness entrypoint links, `git diff --check`, компиляция Python и проверка всех локальных шаблонов прошли. Все семь точных local config paths игнорируются и не отслеживаются Git.

Проверка с изменённым timeout отдельно подтверждает принудительную остановку реального дочернего процесса, игнорирующего SIGTERM. Интервалы времени допускают дробные секунды; PostgreSQL connect timeout остаётся целым числом.
