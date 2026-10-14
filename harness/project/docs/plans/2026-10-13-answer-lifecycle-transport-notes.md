# U7 transport proof: рабочая гипотеза

2026-10-13. Статус: исследование; код и proof ещё отсутствуют. Не закрывает KTD8,
U7/U8 или G5. U5 реализуется отдельно; его per-read auth не равен handoff fence.

В установленном Uvicorn 0.54.0 `h11_impl.py` response send сначала ожидает
write-flow drain, затем синхронно кодирует h11 event и вызывает transport.write.
H11Protocol создаёт cycle и планирует ASGI task; run_asgi передаёт cycle.send
приложению. Эти наблюдения проверены в локальном pinned source и
[официальном tag 0.54.0](https://github.com/Kludex/uvicorn/blob/0.54.0/uvicorn/protocols/http/h11_impl.py).
Старый snapshot/event payload не является разрешением последующей выдачи.

Предполагаемый минимальный путь, который ещё нужно опровергнуть тестами:

1. Специализированный H11Protocol подключает общий guarded send к созданному
   cycle до запуска ASGI task, без копирования всего protocol implementation.
2. Защищённый ответ передаёт внутренний authorization/serialization callback;
   tokens и proofs остаются headers и не попадают в transport logs.
3. Ожидание drain происходит без DB locks. После drain берутся те же owner/
   session/source/request fences, что у invalidation. Payload повторно проверяется
   и при необходимости строится из текущего committed состояния.
4. Если flow снова paused, locks отпускаются до повторного drain. При готовом
   flow синхронный transport.write выполняется внутри DB barrier, без сетевого
   await. Нельзя предположить это свойство для иной версии/protocol.
5. Revoke запрещает всякий protected payload. Used-source delete подавляет старые
   pending/replay output events; сохранённая история после terminal отображает
   прерванный prefix с актуальными source flags. OCR correction сохраняет текущую
   генерацию старой ревизии, но выдача показывает актуальные отметки.
6. Generic ASGI deployment без нужного transport extension должен отказать
   защищённому stream, а не незаметно использовать недоказанный fallback.

Обязательная проверка: реальные два API-процесса, socket backpressure и pause
между подготовкой события и handoff; revoke/delete завершается, затем drain
освобождается — старые неподанные bytes не передаются. Отдельно проверить replay,
snapshot и OCR flags. Test injection допускается только в тестовом launcher;
production flags для обхода fences не нужны. Byte writes до mutation confirmation
неотзывны; удерживать locks во время drain нельзя.

Гипотезу необходимо проверить по фактическому U5 API и всем middleware. Не
реализованы protocol subclass, callback boundary или тестовая fault injection.
