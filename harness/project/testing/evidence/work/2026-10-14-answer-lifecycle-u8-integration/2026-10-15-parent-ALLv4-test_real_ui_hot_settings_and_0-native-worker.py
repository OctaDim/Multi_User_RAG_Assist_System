import logging,time
from pathlib import Path
from app.llama_runtime import LlamaContext
logging.basicConfig(level=logging.DEBUG)
original=LlamaContext.advance
marker=Path('/tmp/rag-u8-all-application-v4/test_real_ui_hot_settings_and_0/native-pause');release=Path('/tmp/rag-u8-all-application-v4/test_real_ui_hot_settings_and_0/native-release');armed=Path('/tmp/rag-u8-all-application-v4/test_real_ui_hot_settings_and_0/native-armed')
mode='after'
def advance(self):
    if armed.exists() and not marker.exists() and ('before' in mode or (len(self.output_tokens)>=3 and not self._decoder.getstate()[0])):
        marker.write_text('inside allocated real native context')
        while not release.exists():time.sleep(.01)
        if mode.startswith('fault'):raise RuntimeError('controlled native decode failure')
    return original(self)
LlamaContext.advance=advance
from app.generation import main
main()
