# Повтор четырёх технических сценариев с согласованными сроками

Дата создания: 2026-10-15. Статус: повтор выполнен, два сценария остаются непройденными.
Дополнение к [отчёту переноса](2026-10-15-sqlalchemy-alembic.md); прежние результаты сохраняются.

Пользователь явно разрешил увеличить только тестовые сроки: готовность OCR — 300 секунд, появление ответа — 120 секунд, завершение ответа — 180 секунд, обработка многостраничного PDF — 2000 секунд. В тесте управляемой остановки native-контекста достижение границы также ожидается до 120 секунд. Проверки содержимого, доступа, исключения старого контекста и атомарности не изменены.

Проверены заданные пользователем параметры приложения: `generation.Supervisor.own` уже использует `lease_seconds = 5`; `events.ACK_TIMEOUT = 15`, `events.GRACE = 10`. Эти значения не зависят от тестового окружения, распространяются на production и не требуют правки. Настройки пула и другие production-таймауты не менялись.

Коллекция подтвердила ровно четыре выбранных сценария:

- `tests/browser/test_invalidation.py::test_real_ocr_mutation_preserves_original_and_excludes_future_context[before-delete]`
- `tests/browser/test_invalidation.py::test_real_ocr_mutation_preserves_original_and_excludes_future_context[after-delete]`
- `tests/browser/test_answer_lifecycle.py::test_actual_print_only_pdf_limitations_reach_answer_passport`
- `tests/integration/test_actual_page_failure.py::test_actual_twenty_page_failure_excludes_fifteen_native_successes_and_keeps_neighbor[whole-pdf]`

Запуск: `uv run --offline --project backend --frozen pytest -c backend/pyproject.toml <четыре узла выше> -vv --basetemp=/tmp/rag-timeout-repeat-20261015 --junitxml=/tmp/rag-timeout-repeat-20261015.xml`. Используются закреплённые модели Qwen/E5/OCR из `backend/.venv/rag-native-models`, реальный Chromium и временная PostgreSQL. Полный stdout/stderr: `/tmp/rag-timeout-repeat-20261015.log`; журналы отдельных процессов — в basetemp.

Проверка качества 30/30 отсутствует в выбранных узлах и не запускалась. `git diff --check` после изменения сроков прошёл.

Промежуточно: before-delete и after-delete прошли. Паспорт PDF завершился FAILED; его supervisor сообщил `Coordinator ownership connection stalled`. Многостраничный сценарий ещё выполняется; его supervisor также сообщил эту ошибку, OCR продолжает работу. Итоговые assertions и сводка будут сохранены после штатного завершения всех четырёх тестов.

## Итог

Штатное завершение pytest, exit 1: **2 passed / 2 failed in 1888.42s (31:28)**. Никаких прерываний прогона или ручных остановок не потребовалось. Продолжительность отдельных случаев ниже взята из JUnit и включает их setup/teardown.

| Сценарий | Результат | Секунды |
|---|---|---:|
| Удаление до начала ответа | PASS | 131.047 |
| Удаление после начала ответа | PASS | 102.017 |
| Паспорт ответа по print-only PDF | FAIL | 208.251 |
| Многостраничный whole-PDF | FAIL | 1446.286 |

Паспорт: `#history .answer-text` не появился за 120000 мс. В журнале supervisor — `Coordinator ownership connection stalled`, в API — HTTP 503 на POST answers. Тест не дошёл до проверки содержимого паспорта.

Whole-PDF: все 15 страниц действительно обработаны; пройдены проверки отказа страницы 16, отсутствия published revision/доступной source revision, сохранения оригинального SHA256, наличия 15 staged страниц и HTTP 409 при явном выборе неготового источника. Сценарий остановился на последней проверке: `#history article` с «Завершён» не появился за 180000 мс. Supervisor ранее сообщил ту же ошибку владения, POST answers по здоровому соседнему источнику вернул HTTP 503. Лимит OCR в 2000 секунд не был причиной этого отказа.

Успех двух сценариев удаления увеличивает совокупное покрытие текущей реализации до **317 уникальных успешных технических случаев из 319**. Это сумма документированных отдельных прогонов, а не один полностью зелёный запуск. Остаются паспорт PDF и whole-PDF. Сроки приложения по-прежнему ровно 5 секунд и 15 + 10 секунд; увеличивались только согласованные тестовые ожидания. Конкретная причина потери владения координатором не установлена; ошибки не переклассифицированы в успешную приёмку.

Неизменяемые копии исходных результатов:

- [Полный вывод pytest](2026-10-15-sqlalchemy-timeout-repeat.pytest.log), SHA256 `bb79e945017b68ef216bbfed0974abd82f2757b5780894bbb06c7bcf12cffdb8`.
- [JUnit](2026-10-15-sqlalchemy-timeout-repeat.junit.xml), SHA256 `74ec5359ab5b48bcc00a2df5773d1bb7140198ec208367795ceb47fcaa0f5995`.
- [Supervisor whole-PDF](2026-10-15-sqlalchemy-timeout-repeat.whole-pdf-supervisor.log), SHA256 `b91f05547198e98e6ede40d23710eb9d57b012c176652fe9e5f6f810228106cc`.
- [Supervisor паспорта PDF](2026-10-15-sqlalchemy-timeout-repeat.passport-supervisor.log), SHA256 `565d5836283f971cc3d96caebb9c831c00e897fb95c5911c663081b267eff7ab`.

Временная PostgreSQL остановлена фикстурой: postmaster.pid отсутствует. Проверка списка процессов не обнаружила процессов этого прогона, document worker или generation worker. Рабочая БД и read-only образец не затрагивались. Заключительный коммит остаётся отложенным по правилу failed checks из comm-commit-task-stages; текущие изменения сохранены.
