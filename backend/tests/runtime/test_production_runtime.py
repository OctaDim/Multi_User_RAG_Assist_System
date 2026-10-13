"""U4 production boundary, using the pinned native model and unchanged U1 baseline."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
from threading import Event
import tomllib

import llama_cpp as native
import pytest

from app.llama_runtime import LlamaRuntime
from test_generation_contract import MODEL_SHA256, NativeContext


def prompt(question):
    return f"<|im_start|>user\n{question}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


@pytest.fixture(scope="module")
def runtime():
    path = Path(os.environ["RAG_MODEL_PATH"])
    with path.open("rb") as source:
        assert hashlib.file_digest(source, "sha256").hexdigest() == MODEL_SHA256
    config = tomllib.loads(Path("backend/config/runtime.toml").read_text())
    runtime = LlamaRuntime(path, config)
    try:
        yield runtime
    finally:
        outstanding = runtime.allocate("runtime-shutdown", runtime.tokenize(prompt("OK")))
        runtime.close()
        assert outstanding.context is None and outstanding.sampler is None
        assert runtime.model is None
        runtime.close()


def test_independent_production_contexts_match_u1_prefix(runtime):
    expected, contexts = {}, []
    for sequence in range(2):
        baseline = NativeContext(runtime.model, sequence)
        try:
            while len(baseline.output) < 8 and not baseline.done:
                baseline.advance(-1, 0)
            expected[sequence] = baseline.output.copy()
        finally:
            baseline.close()
        tokens = runtime.tokenize(prompt(f"Write the numbers from {sequence + 1} to {sequence + 20}, separated by spaces."))
        contexts.append(runtime.allocate(f"prefix-{sequence}", tokens))
    try:
        assert contexts[0].context != contexts[1].context
        assert contexts[0].sampler != contexts[1].sampler
        for _ in range(64):
            for sequence, context in enumerate(contexts):
                if len(context.output_tokens) < 8 and not context.done:
                    result = context.advance()
                    assert result["position"] == context.position
                    assert context.output_tokens == expected[sequence][:len(context.output_tokens)]
            if all(len(context.output_tokens) == 8 for context in contexts):
                break
        assert [context.output_tokens for context in contexts] == [expected[0], expected[1]]
        survivor = contexts[1]
        pointer, before = survivor.context, survivor.position
        assert contexts[0].close() is True
        assert contexts[0].close() is True
        result = survivor.advance()
        assert result["phase"] == "token" and survivor.position == before + 1
        assert survivor.context == pointer
    finally:
        for context in contexts:
            context.close()


def test_real_eos_and_incremental_russian_utf8(runtime):
    tokens = runtime.tokenize(prompt("Ответь точно: Привет, мир."))
    context = runtime.allocate("russian", tokens)
    pieces, text = [], []
    try:
        for _ in range(128):
            result = context.advance()
            pieces.append(result["piece"])
            text.append(result["text"])
            if result["done"]:
                break
        assert result["reason"] == "eos"
        assert native.llama_vocab_is_eog(runtime.vocab, context.output_tokens[-1])
        assert "".join(text) == b"".join(pieces).decode("utf-8")
        assert any("А" <= letter <= "я" for letter in "".join(text))
        assert context.position == len(tokens) + len(context.output_tokens) - 1
        print({"proof": "production_eos_utf8", "tokens": len(context.output_tokens), "text": "".join(text)}, flush=True)
    finally:
        context.close()


def test_actual_token_budget_has_no_prompt_clamp(runtime):
    tokens = runtime.tokenize(prompt("Контекст " * 5000))
    assert len(tokens) > 4096
    with pytest.raises(ValueError, match="context"):
        runtime.allocate("oversized", tokens)
    context = runtime.allocate("full-budget", tokens[:4096])
    try:
        assert context.n_ctx == native.llama_n_ctx(context.context) == 4096
        assert len(context.prompt_tokens) == 4096
        assert context.position == 0
        for position in range(32, 4097, 32):
            result = context.advance()
            assert result["phase"] == "prefill" and result["position"] == position
        assert result["done"] and result["reason"] == "context_limit"
        assert context.output_tokens == []
        assert context.advance()["position"] == 4096
    finally:
        context.close()
    print({"proof": "production_token_budget", "actual_prompt_tokens": len(tokens), "n_ctx": 4096}, flush=True)


def test_abort_and_close_wait_for_real_native_decode(runtime):
    context = runtime.allocate("inflight", runtime.tokenize(prompt("Write the numbers from 1 to 20.")))
    entered, resume = Event(), Event()

    @native.ggml_abort_callback
    def abort(_):
        entered.set()
        assert resume.wait(15), "Native decode was not released by the test"
        return True

    native.llama_set_abort_callback(context.context, abort, None)
    with ThreadPoolExecutor(max_workers=2) as threads:
        advancing = threads.submit(context.advance)
        try:
            assert entered.wait(15), "The real native abort callback was not reached"
            context.cancel()
            closing = threads.submit(context.close)
            assert not closing.done()
            assert context.context and context.sampler
            resume.set()
            assert advancing.result(15)["reason"] == "cancelled"
            assert closing.result(15) is True
            assert context.context is None and context.sampler is None
            assert context.close() is True
        finally:
            resume.set()
            context.close()


def test_partial_allocation_is_freed_on_sampler_failure(runtime, monkeypatch):
    freed = []
    free = native.llama_free

    def record_free(context):
        freed.append(context)
        free(context)

    monkeypatch.setattr(native, "llama_free", record_free)
    monkeypatch.setattr(native, "llama_sampler_init_greedy", lambda: None)
    with pytest.raises(RuntimeError, match="sampler"):
        runtime.allocate("failed-allocation", runtime.tokenize(prompt("OK")))
    assert len(freed) == 1
