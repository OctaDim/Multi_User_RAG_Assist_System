# U8 primary OCR guidance after genuine Cyrillic handwriting failure

Date: 2026-10-14. Read-only parent research. No model downloads, dependency changes, native runs, or production changes performed.

The [official PaddleOCR-VL-1.5 GGUF instructions](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.5-GGUF) specify `Spotting:` and a projector image budget of `clip.vision.image_max_pixels = 1605632`. The [official 1.5 model example](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.5) doubles image dimensions with LANCZOS when both are below 1500, and sets spotting's maximum pixels to `2048 * 28 * 28`. These are concrete preprocessing checks for the existing profile; they do not establish that a change fixes the observed script errors. Do not alter pinned original assets in place.

Read-only inspection of installed `llama_cpp/llama_chat_format.py` shows `MTMDChatHandler._init_mtmd_context` obtains default parameters and sets GPU use, timings, threads, and flash attention. It does not explicitly set image token budgets. Installed `mtmd_cpp.py` exposes `image_min_tokens` and `image_max_tokens`. Their effective defaults and the actual projector metadata still require measurement; no values were inferred here.

The [official 1.6 model](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6) and [official 1.6 GGUF](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF) are possible native-compatible candidates. The authors describe architecture compatibility with 1.5. This is an upstream claim, not verification against this repository's pinned runtime or Cyrillic inputs.

[Table 6 of the official 1.6 report](https://arxiv.org/html/2606.03264v1) reports Chinese and English handwriting categories. It does not report a Russian/Belarusian handwriting category. General multilingual support does not discharge the observed handwriting gate. No documented language-specific spotting prompt was found in the inspected model examples; their task prompts are `OCR:` and `Spotting:`.

The [official PP-OCRv5 multilingual documentation](https://paddlepaddle.github.io/PaddleOCR/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html) describes dedicated East Slavic recognition for Russian, Belarusian, and Ukrainian. It does not prove recognition of the actual cursive inputs tested here. No additional recognizer was selected or installed by this research.

Any diagnosis comparing OCR and spotting must retain exact input/transform/runtime records. Production must retain actual coordinates/provenance, whole-document publication, and masking of forbidden handwriting pixels before recognition. A model card, language hint, transliteration, or a hardcoded replacement for a known answer is not a successful genuine-input test.
