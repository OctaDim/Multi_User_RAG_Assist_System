# Облегчение supervisor без изменения lease и GC

Создано: 2026-10-15. Проверки завершены успешно; результаты и ограничения ниже.
Обычный отчёт приложения, не материал механизма harness.

Пользователь явно разрешил следующий отдельный шаг: убрать из supervisor загрузку
`app.rag`, NumPy, ONNX и LangGraph, перенести эти импорты в native worker,
измерить память и повторить проверки. Lease 5 секунд, пулы и политика GC сохраняются.
Это продолжение [этапа OCR](2026-10-15-ocr-context-and-fragments.md), где финальный
паспорт вновь не прошёл из-за потери владения координатором.

Изменение `backend/app/generation.py`: удалён импорт `E5Embedder, run_graph`
на уровне модуля. `run_graph` импортируется в `Coordinator.prepare_next`,
`E5Embedder` — в `worker` после подтверждения supervisor через start pipe,
рядом с существующим отложенным `LlamaRuntime`.
Граф и embedding продолжают работать в native worker; supervisor не выполняет их.

Новый тест `backend/tests/test_supervisor_imports.py` запускает свежий Python
из другого cwd, реально импортирует Supervisor и проверяет загруженные модули.
До изменения: **1 failed in 1.47s**, найдено семейство `app.rag/NumPy/ONNX/LangGraph`.
После: **1 passed in 0.62s**, тяжёлые модули отсутствуют.

| Измерение после импорта в свежем процессе | До | После |
| --- | ---: | ---: |
| VmRSS, KiB | 142228 | 67988 |
| Объекты `gc.get_objects()` | 164378 | 90328 |
| ru_maxrss, KiB | 144076 | 101636 |

Это отдельные измерения импорта, не RSS работающего supervisor под нагрузкой.
VmRSS уменьшился на 74240 KiB; GC не отключался и не замораживался.
ru_maxrss включает предысторию дочернего процесса и не используется как текущая память.
Меньший heap не является доказательством отсутствия любых будущих page-in задержек.
Исходные измерения: [до](2026-10-15-light-supervisor-before.json),
[после](2026-10-15-light-supervisor-after.json),
[RED log](2026-10-15-light-supervisor-red.pytest.log),
[GREEN log](2026-10-15-light-supervisor-green.pytest.log).

Во время первого PDF получен отдельный read-only
[снимок действующего supervisor](2026-10-15-light-supervisor-active.json):
VmRSS 11616 KiB, VmSwap 44084 KiB, два потока, отсутствуют mappings библиотек
NumPy/ONNX/llama. Это один момент под давлением памяти, не пиковая величина
и не сравнение с таким же моментом прежнего процесса.

Регрессия `test_supervisor_imports.py test_service_recovery.py
test_service_ownership_lease.py test_scheduler.py test_rag_context.py tests/runtime`:
**46 passed in 156.19s (0:02:36)**. Настоящая PostgreSQL, native runtime/E5,
сценарии подтверждённого lease 0.8/5.5 s, потеря keeper, завершение ребёнка
до замены, молчащий TCP-сервер, планировщик и RAG прошли.
Сохранены [log](2026-10-15-light-supervisor-regression.pytest.log)
и [JUnit](2026-10-15-light-supervisor-regression.junit.xml).

Запущен plain повтор двух исходных сценариев с новым supervisor:

```sh
uv run --project backend --frozen --offline pytest \
  backend/tests/browser/test_answer_lifecycle.py::test_actual_print_only_pdf_limitations_reach_answer_passport \
  'backend/tests/integration/test_actual_page_failure.py::test_actual_twenty_page_failure_excludes_fifteen_native_successes_and_keeps_neighbor[whole-pdf]' \
  -v --basetemp=/tmp/rag-light-supervisor-pdf-20261015 \
  --junitxml=/tmp/rag-light-supervisor-pdf-20261015.xml
```

Окружение: существующие pinned-модели из `backend/.venv/rag-native-models`,
UV_CACHE_DIR=/tmp/rag-u1-uv-cache; локальные сокеты разрешены для pytest/asyncio,
браузера и временной PostgreSQL. Диагностических плагинов и изменений GC нет.
Итог: **2 passed in 963.69s (0:16:03)**.
Паспорт PDF — 120.676 s, whole-pdf — 842.510 s.
Whole-pdf прошёл все 15 настоящих native OCR-страниц, отказ страницы 16,
непубликацию повреждённого файла и ответ по исправному соседнему документу.
Сообщений `Coordinator ownership connection stalled` в этом прогоне нет.
Сохранены [log](2026-10-15-light-supervisor-pdf.pytest.log)
и [JUnit](2026-10-15-light-supervisor-pdf.junit.xml).

Финальный wheel собран offline и установлен в отдельный `/tmp` target без
разрешения зависимостей. Из другого cwd подтверждены отсутствие тяжёлых импортов
supervisor, работа упакованного `ocr_fragments`, контексты 16384/4096 и семь
упакованных Alembic-ревизий. Это проверка установленного артефакта с существующими
pinned-зависимостями, не чистая установка зависимостей и не миграция рабочей БД.
[Исходный результат](2026-10-15-final-wheel-proof.json) содержит SHA256 wheel.

Финальная [коллекция](2026-10-15-final-technical-collection.log):
**338/339 tests collected (1 deselected)**. 319 исходных технических сценариев
и 19 добавленных OCR/import-сценариев имеют успешные результаты в совокупности
описанных запусков; единого чистого прогона всей коллекции не выполнялось.
Прежние неуспехи сохранены в своих отчётах, не переобозначены как успешные.
AST-проверка приложения не нашла прямых строковых execute/scalar, create_all
или exec_driver_sql; она дополняет реальные проверки запросов и транзакций.
`git diff --check` прошёл. Тестовые pytest/generation/documents-процессы завершены.

Проверка качества 30/30 ответов и цитат полностью исключена.
Код сохранён локально: `4398854` (SQLAlchemy runtime/supervisor),
`ab0d15f` (OCR и тестовые ожидания). Два посторонних пользовательских документа
исключены из коммитов. Публикация, push и изменение рабочей БД не выполнялись.
