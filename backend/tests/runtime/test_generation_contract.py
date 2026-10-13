"""U1/G1: native contexts sharing one model; no HTTP completion or mock tokens."""

from collections import deque
import ctypes
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import resource
from time import perf_counter

import llama_cpp as native
import pytest


MODEL_SHA256 = "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223"


def trace(event, **fields):
    print(json.dumps({"event": event, "seconds": perf_counter(), **fields}), flush=True)


@pytest.fixture(scope="module")
def model():
    path = Path(os.environ["RAG_MODEL_PATH"])
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    assert digest == MODEL_SHA256, "G1 requires the agreed Qwen3.5-2B Q4_K_M revision"
    native.llama_backend_init()
    params = native.llama_model_default_params()
    params.n_gpu_layers = 0
    weights = native.llama_model_load_from_file(os.fsencode(path), params)
    assert weights, "The selected native build could not load the agreed model"
    trace("model", sha256=digest, bindings=version("llama-cpp-python"), system=native.llama_print_system_info().decode())
    try:
        yield weights
    finally:
        native.llama_model_free(weights)
        native.llama_backend_free()


class NativeContext:
    """Test-owned reservation; every advance calls the low-level native API."""

    def __init__(self, model, sequence, question=None):
        self.sequence = sequence
        self.vocab = native.llama_model_get_vocab(model)
        params = native.llama_context_default_params()
        params.n_ctx = 4096
        params.n_seq_max = 1
        params.n_batch = params.n_ubatch = 32
        params.n_threads = 4
        params.n_threads_batch = 8
        self.context = native.llama_init_from_model(model, params)
        assert self.context, f"Could not allocate native context {sequence}"
        self.sampler = native.llama_sampler_init_greedy()
        assert self.sampler
        self.position = 0
        self.output = []
        self.done = False
        question = question or f"Write the numbers from {sequence + 1} to {sequence + 20}, separated by spaces."
        prompt = (
            "<|im_start|>user\n"
            f"{question}"
            "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        ).encode()
        buffer = (native.llama_token * (len(prompt) + 16))()
        size = native.llama_tokenize(self.vocab, prompt, len(prompt), buffer, len(buffer), True, True)
        assert 0 < size < 4096
        self.prompt = deque(buffer[:size])
        trace("allocate", sequence=sequence, context=int(self.context), sampler=ctypes.cast(self.sampler, ctypes.c_void_p).value, n_ctx=native.llama_n_ctx(self.context))

    def decode(self, tokens):
        batch = native.llama_batch_init(len(tokens), 0, 1)
        try:
            batch.n_tokens = len(tokens)
            for index, token in enumerate(tokens):
                batch.token[index] = token
                batch.pos[index] = self.position + index
                batch.n_seq_id[index] = 1
                batch.seq_id[index][0] = 0
                batch.logits[index] = index == len(tokens) - 1
            assert native.llama_decode(self.context, batch) == 0
            self.position += len(tokens)
        finally:
            native.llama_batch_free(batch)

    def advance(self, step, revision):
        if self.prompt:
            portion = [self.prompt.popleft() for _ in range(min(32, len(self.prompt)))]
            self.decode(portion)
            trace("prefill", sequence=self.sequence, step=step, revision=revision, count=len(portion))
            return
        token = native.llama_sampler_sample(self.sampler, self.context, -1)
        self.output.append(token)
        self.done = native.llama_vocab_is_eog(self.vocab, token)
        if not self.done:
            self.decode([token])
        trace("token", sequence=self.sequence, step=step, revision=revision, token=token, eos=self.done)

    def close(self):
        native.llama_sampler_free(self.sampler)
        native.llama_free(self.context)
        trace("release", sequence=self.sequence, context=int(self.context))


def test_native_twelve_contexts_hot_limits_and_fair_steps(model):
    expected = {}
    for sequence in range(13):
        standalone = NativeContext(model, sequence)
        try:
            while len(standalone.output) < 8 and not standalone.done:
                standalone.advance(-1, 0)
            expected[sequence] = standalone.output.copy()
        finally:
            standalone.close()

    active = {}
    queue = deque(range(13))
    runnable = deque()
    limit, width, revision, step = 12, 3, 1, 0

    def admit():
        while queue and len(active) < limit:
            sequence = queue.popleft()
            trace("admit", sequence=sequence, previously_active=len(active), limit=limit, revision=revision)
            active[sequence] = NativeContext(model, sequence)
            runnable.append(sequence)
        trace("capacity", active=len(active), waiting=list(queue), limit=limit, width=width, revision=revision, max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

    def tick():
        nonlocal step
        group = [runnable.popleft() for _ in range(min(width, len(runnable)))]
        assert len(group) <= width and len(set(group)) == len(group)
        for sequence in group:
            context = active[sequence]
            if not context.done:
                context.advance(step, revision)
                assert context.output == expected[sequence][:len(context.output)]
            runnable.append(sequence)
        trace("step", step=step, revision=revision, sequences=group)
        step += 1
        return group

    def cancel(sequence):
        active.pop(sequence).close()
        runnable.remove(sequence)

    try:
        admit()
        assert len(active) == 12 and list(queue) == [12]
        pointers = {sequence: int(context.context) for sequence, context in active.items()}
        assert len(set(pointers.values())) == 12
        for _ in range(4):
            served = [sequence for _ in range(4) for sequence in tick()]
            assert sorted(served) == list(range(12))

        cancel(0)
        cancel(1)
        limit, revision = 6, 2
        admit()
        assert len(active) == 10 and list(queue) == [12]
        for sequence in range(2, 7):
            cancel(sequence)
            if len(active) >= 6:
                admit()
                assert list(queue) == [12]
        assert len(active) == 5
        admit()
        assert len(active) == 6 and not queue

        width, revision = 2, 3
        for _ in range(3):
            assert len(tick()) == 2
        limit, width, revision = 12, 4, 4
        queue.extend(range(6))
        admit()
        assert len(active) == 12
        for sequence in range(7, 12):
            assert int(active[sequence].context) == pointers[sequence]
        served = [sequence for _ in range(3) for sequence in tick()]
        assert sorted(served) == sorted(active)
        trace("proof", result="passed", revision=revision)
    finally:
        for context in active.values():
            context.close()


def test_native_eos_releases_one_context_without_stalling_another(model):
    short = NativeContext(model, 20, "Reply with exactly OK and nothing else.")
    survivor = NativeContext(model, 21)
    short_closed = False
    try:
        for step in range(64):
            short.advance(step, 1)
            survivor.advance(step, 1)
            if short.done:
                break
        assert short.done, "The real EOS scenario did not reach an end token"
        assert not survivor.done
        pointer = int(survivor.context)
        before = len(survivor.output)
        short.close()
        short_closed = True
        for step in range(4):
            survivor.advance(64 + step, 1)
        assert len(survivor.output) > before
        assert int(survivor.context) == pointer
    finally:
        if not short_closed:
            short.close()
        survivor.close()
