# Реальные зависимости G3/G4: рабочие технические заметки

2026-10-13. Статус: подготовка зависимостей; реализации/выбора OCR и снятия gates
этот документ не подтверждает. Дополняет
[lifecycle plan](2026-10-13-0244-feat-rag-answer-lifecycle-plan.md).

Пользователь уточнил, что реальные тестовые аккаунты и документы нужно создавать
через E2E и реальные действия в браузерном интерфейсе сервиса. SQL fixtures
остаются только компонентными проверками. U4 сохранён в a45679b после 80 app и
168 harness tests; в работе U5. Дальнейшая реализация должна соблюдать тот же
полный регрессионный gate после каждого U.

## Необходимый пользовательский путь

G3 требует настоящую регистрацию email/password, отправку verification link через
SMTP, потребление ссылки в браузере и обычный login. Пароли и случайные session/
verification secrets нельзя хранить открытым текстом. API не возвращает
verification token как тестовый обход; local test SMTP receiver — отдельная
инфраструктура теста, а не production endpoint. Verified не обходит active/
disabled. Роли/owner проверяются на сервере; paid не становится условием MVP.
Admin mutations должны пройти тот же epoch/terminal/transport barrier, что U7.
Безопасный bootstrap super_admin должен быть операторским и отдельным от обычной
регистрации; конкретный интерфейс ещё не реализован.

G4 требует настоящую загрузку original, фонового worker и атомарной публикации
целой ревизии; file/page failure не публикует частично готовые chunks. Форматы,
права, quotas, mixed-PDF выбор, добровольная OCR correction и неизменный original
определяются RAG-12/13/35/51/59/60/61. UI upload/correction/delete вызывает общие
серверные mutations sources, provenance и checkpoints, не вставляет published
records напрямую. Первоначальные цитаты сохраняются после correction; новый
поиск использует исправленную целую ревизию.

Список применимых частей: accounts/auth/session schema и issuer API; SMTP sender
и local test receiver; owner/admin UI; original storage и upload API; processing
worker и whole publisher; E5 chunks; original/page view и correction; CORS и
независимый static frontend; browser/E2E scenarios. Уже существующие principal,
common terminal transition, settings, sources/change_source, E5Embedder,
migrations и LangGraph guards нужно переиспользовать. Это необходимые зависимости
приёмки выбранного lifecycle, не заявка на завершение всех остальных областей MVP.

## OCR: найденные кандидаты, доказательств пока нет

Официальный PP-OCRv5 multilingual перечисляет русский/белорусский/украинский
для East Slavic recognizer и английский/немецкий для Latin recognizer. Языковая
поддержка сама не доказывает требуемое качество рукописей на данном host.
[Документация PP-OCRv5 multilingual](https://paddlepaddle.github.io/PaddleOCR/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html).

PaddleOCR-VL имеет раздельные layout и recognition стадии; документация разрешает
x64 CPU и подчёркивает, что standalone VLM не равен полному document pipeline.
Следовательно, element OCR нужно соединить с реальным page detection/reading
order, а не объявлять один VLM готовым publisher.
[Официальный pipeline](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PaddleOCR-VL.html).

Официальный PaddleOCR-VL-1.5 GGUF поддерживает llama.cpp и имеет отдельные model/
mmproj файлы (на исследованной странице 936/882 MB). Установленный
llama-cpp-python 0.3.36 уже содержит MTMDChatHandler и mtmd bindings; конкретная
совместимость PaddleOCR, скорость/память и multilingual handwriting не проверены.
Кандидат позволяет начать proof без второго ML framework, но ещё не выбран.
[Официальные GGUF инструкции](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.5-GGUF),
[файлы](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.5-GGUF/tree/main).

PP-DocLayoutV3 config не содержит отдельной handwriting label. Нельзя использовать
его text class как доказанный printed/handwritten separator. При запрете HWR
нужна классификация до recognition; распознать всё и затем скрыть рукописи
нарушает RAG-61.
[Официальный config](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_safetensors/blob/main/config.json).

monkt/doctype — опубликованный MIT MobileNetV3 ONNX classifier с отдельными
document_handwritten/document_printed и input 320×320; файл 12.5 MB. Это кандидат
для detection-only proof на существующем ONNX Runtime. Его model card не
подтверждает классификацию отдельных смешанных page regions: crop calibration
и целый mixed PDF обязательны до выбора; заявленная автором скорость не является
нашим измерением.
[Model card](https://huggingface.co/monkt/doctype),
[файлы](https://huggingface.co/monkt/doctype/tree/main).

Ни OCR weights, ни classifier weights пока не скачаны; новый engine не установлен
и production код на основании этой разведки не добавлен. Первое применение должно
фиксировать revision/SHA256, реальные входные PDF, detection до OCR, разрешённые
crop inputs, recognized output и whole publication. Synthetic handwriting font
не выдаётся за реальный рукописный документ; fixture publisher не закрывает G4.
