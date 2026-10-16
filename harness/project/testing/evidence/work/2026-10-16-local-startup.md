# Локальная подготовка запуска WSL — 2026-10-16

Настройка PostgreSQL, моделей и постоянного конфигурационного файла завершена; обычный запуск и остановка проверены отдельно от тестовых fixtures. Codex-ревью выполнено, замечание исправлено, заключительный интегрированный набор прошёл.

## PostgreSQL и конфигурация

Установлены пакеты Ubuntu PostgreSQL 16.15 и postgresql-16-pgvector 0.6.0. Свободный до установки порт 5432 занят созданным кластером 16/main. PostgreSQL работает на loopback, postgresql.service enabled, start.conf=auto; перезапуск всей WSL не выполнялся.

Созданы БД rag_assist и владелец rag_assist_user: NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION. Расширение vector 0.6.0 установлено администратором postgres в public этой БД. TCP login от приложения и SELECT с vector прошли. Existing Alembic upgrade достиг 0007_checkpoints; public содержит 30 таблиц.

Фактический DSN и пути моделей записаны в backend/config/service.local.toml, mode 0600. Git check-ignore подтвердил исключение, git ls-files подтвердил отсутствие отслеживания. Пароли в этот отчёт и Git не включаются.

## Модельный набор

Девять неизменённых файлов перенесены из backend/.venv/rag-native-models в rag/local_models командой python3 backend/prepare_models.py --source backend/.venv/rag-native-models --move. Проверены исходники, staging и назначение; verify_installation повторно проверил фактическую конфигурацию и полный набор. Пустой прежний каталог и scaffold-only backup удалены. Сами веса, JSON/tokenizer companions, staging и backup исключены; scaffold и manifest видимы Git.

Источники и закреплённые upstream identities сохранены в [metadata](2026-10-16-local-startup-model-primary-metadata-v1.json). Manifest: backend/config/models.toml. Все 5 native библиотек совпали с ранее проверенным U1 baseline environment-v1.json; Python-окружение и native-сборка не заменялись.

## Выполненные проверки

- U1: uv run --project backend --frozen pytest -c backend/pyproject.toml backend/tests/test_model_artifacts.py -q → 19 passed. Предварительно новый operational tuning regression был RED: 17 passed, 1 failed с отклонением runtime.generation.max_active; после сужения compatibility-профиля проверка прошла.
- Реальная генерация на перенесённой Qwen дала local ready. с EOS за 2.25 секунды.
- E5 выполнил кодирование двух текстов: 384 компоненты, L2-нормировка проверена.
- DocumentOCR загрузил printed+handwriting модели, проекторы и D-FINE; detector inference выполнен; printed OCR прочитал Local setup check 123.
- Исходный журнал реального последовательного model smoke: [log](2026-10-16-local-startup-model-function-v1.log). Тест использовал фактический локальный service config, без временного DSN и без смены идентичности моделей.

## Проверки main и жизненного цикла

Интегрированный набор из Verification Contract плана запущен через uv с путями трёх перенесённых моделей для fixture-based smoke: test_model_artifacts.py, test_startup_bootstrap.py, test_backend_launcher.py, test_frontend_launcher.py, test_launch_configuration.py, test_resources.py, test_supervisor_imports.py → **85 passed in 117.92s**. После замены двух ручных циклов SHA-256 на stdlib hashlib.file_digest и удаления повествовательных комментариев повторены затронутые model/bootstrap tests → **35 passed in 1.75s**. Настроенных lint/typecheck-команд для этой области нет; они не объявляются пройденными.

Main проверяет Python, locked зависимости, однократное восстановление через uv, сохранение native fingerprint, полный модельный набор и совместимость до импортов компонентов. Отрицательные регрессии покрывают отсутствие uv/зависимостей/моделей, неудачное восстановление, несовместимые профили и native build. Ранние owned probe/uv и их потомки останавливаются сигналами; основные компоненты сохраняют существующий supervisor.

Отдельный [ordinary smoke](2026-10-16-local-startup-ordinary-smoke-v1.py) запускает ровно python3 backend/main.py и python3 frontend/main.py из корня проекта. Все унаследованные RAG_* удаляются; временный TOML, --config и тестовый DSN не используются. Проверены HTTP API public-settings, CORS для 8080, HTML с API origin 8000, здоровый generation lease и native_spawn. Перед каждым запуском оба порта свободны; чужие процессы не останавливаются.

[Результаты](2026-10-16-local-startup-ordinary-results-v1.json): цикл SIGINT — четыре дочерних backend-компонента, все восемь наблюдавшихся owned PID исчезли; повторный запуск и SIGTERM — четыре компонента, все десять наблюдавшихся PID исчезли. В наблюдаемый набор входят и уже завершившиеся bootstrap probes. Оба main вернули 0, 8000/8080 освободились, постоянный PostgreSQL после каждой остановки отвечал на SELECT 1. Во фронте при остановке оставалось открытым неполное HTTP-соединение; дочерних процессов у фронта нет.

Неизменённые сырые журналы: [backend SIGINT](2026-10-16-local-startup-ordinary-backend-sigint-v1.log), [backend SIGTERM](2026-10-16-local-startup-ordinary-backend-sigterm-v1.log), [frontend SIGINT](2026-10-16-local-startup-ordinary-frontend-sigint-v1.log), [frontend SIGTERM](2026-10-16-local-startup-ordinary-frontend-sigterm-v1.log).

## Ревью и исправление

Выполнен полный ce-code-review mode:agent с base 4c267bf и явным планом. Receipt status=complete, verdict=Ready with fixes, run_id=20261016-134607-04944614; временные артефакты /tmp/compound-engineering-1000/ce-code-review/20261016-134607-04944614. Семь направлений Codex: correctness, project-standards, testing, maintainability, security, reliability, adversarial. Отдельный validator подтвердил единственное замечание P2 #1: успешная подготовка в существующий пустой каталог либо повторное использование полного набора без .gitignore не восстанавливали исключения Git.

Замечание проверено независимо настоящими git init/check-ignore на двух временных установках. Две новые регрессии сначала дали 2 failed, 19 deselected; после исправления подготовка создаёт default scaffold до публикации либо восстанавливает его для проверенного reuse, сохраняя существующий scaffold. Изменение применено в родительском контексте после получения receipt; повторное полное ревью не запускалось.

Testing отметил пробел прямого покрытия prerequisite run_owned: timeout и нормальный выход leader при живом потомке. Добавлены два реальных stdlib subprocess-сценария с SIGTERM-игнорирующим потомком, проверкой reaping и сохранности независимого процесса. Затронутые model/bootstrap tests вместе с четырьмя новыми сценариями → 39 passed in 3.74s. Заключительный интегрированный набор из семи файлов Verification Contract, с фактическими путями перенесённых моделей: **89 passed in 79.75s (0:01:19)**. Пропусков и ошибок нет.

В исходниках и документации git diff --check проходит. Два исходных trailing spaces в сыром model-function log сохранены без изменений как часть неизменяемого результата; проверка whitespace исключает только raw .log. Фактические private DSN/password не найдены в изменениях и сохранённых доказательствах. После проверок PostgreSQL отвечает на pg_isready, postgresql.service enabled.

Неприменённых подтверждённых замечаний ревью нет.

Не проверялся свежий старт всей WSL или воспроизводимая native-пересборка на новой машине. SMTP не настроен; отправка подтверждений email не является результатом этой подготовки.

## Состояние после проверки

После заключительных 89 тестов отдельно запущены обычные python3 backend/main.py и python3 frontend/main.py. Оба HTTP endpoint вернули 200, generation lease здоров, подключение выполнено как rag_assist_user к rag_assist. Оба раздела оставлены работающими; результат относится к указанному моменту времени: [final running](2026-10-16-local-startup-final-running-v1.json).
