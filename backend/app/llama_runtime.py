"""CPU llama.cpp weights shared by independently owned request contexts."""

import codecs
import ctypes
import os
from threading import Event, Lock

import llama_cpp as native

from app.configuration import load_settings


def tokenize_vocab(vocab, text):
    data = text.encode('utf-8')
    capacity = len(data) + load_settings('runtime')['native']['token_capacity_padding']
    while True:
        buffer = (native.llama_token * capacity)()
        size = native.llama_tokenize(vocab, data, len(data), buffer, capacity, True, True)
        if size >= 0:
            return list(buffer[:size])
        capacity = -size


class Vocabulary:
    """Exact pinned tokenizer for admission; no weights or generation contexts."""
    def __init__(self, model_path):
        native.llama_backend_init()
        params = native.llama_model_default_params()
        params.vocab_only = True
        params.n_gpu_layers = 0
        self.model = native.llama_model_load_from_file(os.fsencode(model_path), params)
        if not self.model:
            raise RuntimeError('Could not load native vocabulary')
        self.vocab = native.llama_model_get_vocab(self.model)

    def tokenize(self, text):
        return tokenize_vocab(self.vocab, text)

    def close(self):
        native.llama_model_free(self.model)
        self.model = None
        # Backend state is process-wide; another runtime can still own it.


class LlamaRuntime:
    def __init__(self, model_path, config):
        profile = load_settings('runtime')
        self.config = profile['generation'] | config.get("generation", config)
        self.native_config = profile['native']
        self.n_ctx = self.config['n_ctx']
        self._lock = Lock()
        self._contexts = {}
        self._closed = False
        native.llama_backend_init()
        params = native.llama_model_default_params()
        params.n_gpu_layers = 0
        self.model = native.llama_model_load_from_file(os.fsencode(model_path), params)
        if not self.model:
            native.llama_backend_free()
            raise RuntimeError("Could not load native model")
        self.vocab = native.llama_model_get_vocab(self.model)

    def tokenize(self, text):
        with self._lock:
            if self._closed:
                raise RuntimeError("Runtime is closed")
            return tokenize_vocab(self.vocab, text)

    def allocate(self, request_id, tokens):
        with self._lock:
            if self._closed:
                raise RuntimeError("Runtime is closed")
            if request_id in self._contexts:
                raise ValueError("Request already owns a native context")
            if not tokens or len(tokens) > self.n_ctx:
                raise ValueError("Prompt does not fit native context")
            context = LlamaContext(self, request_id, tokens)
            self._contexts[request_id] = context
            return context

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            contexts = list(self._contexts.values())
        for context in contexts:
            context.cancel()
        for context in contexts:
            context.close()
        native.llama_model_free(self.model)
        self.model = None
        native.llama_backend_free()


class LlamaContext:
    def __init__(self, runtime, request_id, tokens):
        self.runtime, self.request_id = runtime, request_id
        self.context = self.sampler = None
        self._lock = Lock()
        self._cancelled = Event()
        self._abort_callback = native.ggml_abort_callback(lambda _: self._cancelled.is_set())
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self.prompt_tokens = list(tokens)
        self.position = 0
        self.output_tokens = []
        self.done = False
        self.reason = None
        params = native.llama_context_default_params()
        params.n_ctx = runtime.n_ctx
        params.n_seq_max = 1
        params.n_batch = params.n_ubatch = runtime.native_config['prefill_batch']
        params.n_threads = runtime.config['n_threads']
        params.n_threads_batch = runtime.config['n_threads_batch']
        params.abort_callback = self._abort_callback
        try:
            self.context = native.llama_init_from_model(runtime.model, params)
            if not self.context:
                raise RuntimeError("Could not allocate native context")
            self.n_ctx = native.llama_n_ctx(self.context)
            if len(tokens) > self.n_ctx:
                raise ValueError("Prompt does not fit actual native context")
            self.sampler = native.llama_sampler_init_greedy()
            if not self.sampler:
                raise RuntimeError("Could not allocate native sampler")
        except BaseException:
            if self.sampler:
                native.llama_sampler_free(self.sampler)
            if self.context:
                native.llama_free(self.context)
            self.context = self.sampler = None
            raise

    def cancel(self):
        self._cancelled.set()

    def _result(self, phase, token=None, piece=b"", text=""):
        return {"phase": phase, "token": token, "piece": piece, "text": text,
                "done": self.done, "reason": self.reason, "position": self.position}

    def _decode(self, tokens):
        batch = native.llama_batch_init(len(tokens), 0, 1)
        try:
            batch.n_tokens = len(tokens)
            for index, token in enumerate(tokens):
                batch.token[index] = token
                batch.pos[index] = self.position + index
                batch.n_seq_id[index] = 1
                batch.seq_id[index][0] = 0
                batch.logits[index] = index == len(tokens) - 1
            status = native.llama_decode(self.context, batch)
            if status == 0:
                self.position += len(tokens)
            elif status == 2 and self._cancelled.is_set():
                # An aborted context may contain partial ubatches; it is released, never reused.
                self.done, self.reason = True, "cancelled"
            else:
                self.done, self.reason = True, "error"
                raise RuntimeError(f"Native decode failed: {status}")
        finally:
            native.llama_batch_free(batch)

    def _piece(self, token):
        capacity = self.runtime.native_config['piece_capacity']
        while True:
            buffer = ctypes.create_string_buffer(capacity)
            size = native.llama_token_to_piece(self.runtime.vocab, token, buffer, capacity, 0, False)
            if size >= 0:
                return buffer.raw[:size]
            capacity = -size

    def advance(self):
        """Evaluate one configured prompt batch or sample/evaluate one output token."""
        with self._lock:
            if self.context is None:
                raise RuntimeError("Native context is closed")
            if self._cancelled.is_set():
                self.done, self.reason = True, "cancelled"
            if self.done:
                return self._result("done")
            if self.position < len(self.prompt_tokens):
                self._decode(self.prompt_tokens[self.position:self.position + self.runtime.native_config['prefill_batch']])
                if self._cancelled.is_set():
                    self.done, self.reason = True, "cancelled"
                elif self.position == self.n_ctx:
                    self.done, self.reason = True, "context_limit"
                return self._result("prefill")
            if self.position >= self.n_ctx:
                self.done, self.reason = True, "context_limit"
                return self._result("done")
            token = native.llama_sampler_sample(self.sampler, self.context, -1)
            if native.llama_vocab_is_eog(self.runtime.vocab, token):
                self.output_tokens.append(token)
                self.done, self.reason = True, "eos"
                return self._result("token", token=token, text=self._decoder.decode(b"", final=True))
            self._decode([token])
            if self._cancelled.is_set():
                self.done, self.reason = True, "cancelled"
                return self._result("done")
            self.output_tokens.append(token)
            piece = self._piece(token)
            text = self._decoder.decode(piece)
            if self.position == self.n_ctx:
                self.done, self.reason = True, "context_limit"
            return self._result("token", token=token, piece=piece, text=text)

    def close(self):
        """Return the release ACK only after decode, sampler free and context free."""
        self.cancel()
        with self._lock:
            if self.context is not None:
                native.llama_sampler_free(self.sampler)
                native.llama_free(self.context)
                self.context = self.sampler = None
                self.done = True
                with self.runtime._lock:
                    self.runtime._contexts.pop(self.request_id, None)
        return True
